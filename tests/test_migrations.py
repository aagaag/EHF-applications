from __future__ import annotations

import hashlib
import importlib
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIRECTORY = ROOT / "database" / "migrations"
VALIDATION_DIRECTORY = ROOT / "database" / "tests"
DATABASE_SCRIPT = ROOT / "scripts" / "test-database.ps1"
PYTHON = Path(
    r"C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime"
    r"\dependencies\python\python.exe"
)
PUBLISHED_003_MIGRATION_SHA256 = bytes.fromhex(
    "472fdfb22cb2ea46f786059905e8c1f9491b7081e145bb8731f9b0c6dd4349ac"
)
CURRENT_003_VALIDATOR_SHA256 = bytes.fromhex(
    "6997f8b31030b9b71190e67062d719d49b93cd67bdd7e43f4ded8f61a773c0ee"
)


def migrations_module() -> ModuleType:
    return importlib.import_module("app.migrations")


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.rows: list[tuple[Any, ...]] = []

    def execute(self, statement: str, *parameters: Any) -> "FakeCursor":
        normalized = " ".join(statement.split())
        if "SELECT OBJECT_ID" in normalized:
            table_exists = self.connection.table_exists or self.connection.pending_table_exists
            self.rows = [(1 if table_exists else None,)]
        elif "SELECT MigrationVersion" in normalized:
            records = self.connection.records | self.connection.pending_records
            self.rows = [
                (version, name, checksum)
                for version, (name, checksum) in sorted(records.items())
            ]
        elif "INSERT dbo.SchemaMigration" in normalized:
            version, name, checksum = parameters
            self.connection.pending_records[int(version)] = (str(name), bytes(checksum))
            self.rows = []
        else:
            if self.connection.failure_marker and self.connection.failure_marker in statement:
                raise RuntimeError(self.connection.failure_message)
            self.connection.executed_batches.append(statement)
            if "CREATE TABLE dbo.SchemaMigration" in statement:
                self.connection.pending_table_exists = True
            self.rows = []
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.rows)


class FakeConnection:
    def __init__(self) -> None:
        self.table_exists = False
        self.pending_table_exists = False
        self.records: dict[int, tuple[str, bytes]] = {}
        self.pending_records: dict[int, tuple[str, bytes]] = {}
        self.executed_batches: list[str] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.failure_marker: str | None = None
        self.failure_message = ""

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.table_exists = self.table_exists or self.pending_table_exists
        self.records.update(self.pending_records)
        self.pending_table_exists = False
        self.pending_records.clear()
        self.commit_count += 1

    def rollback(self) -> None:
        self.pending_table_exists = False
        self.pending_records.clear()
        self.rollback_count += 1


def write_migration(directory: Path, filename: str, sql: str) -> Path:
    path = directory / filename
    path.write_bytes(sql.encode("utf-8"))
    return path


def test_discovers_numbered_migrations_in_version_order_with_sha256(tmp_path: Path) -> None:
    """Break caught: filesystem order or a non-SHA-256 digest could define schema history."""
    module = migrations_module()
    later = write_migration(tmp_path, "010_later.sql", "SELECT 10;\n")
    first = write_migration(tmp_path, "001_first.sql", "SELECT 1;\n")
    write_migration(tmp_path, "notes.sql", "SELECT 99;\n")

    discovered = module.discover_migrations(tmp_path)

    assert [migration.version for migration in discovered] == [1, 10]
    assert [migration.name for migration in discovered] == ["first", "later"]
    assert discovered[0].path == first
    assert discovered[1].path == later
    assert discovered[0].checksum == hashlib.sha256(b"SELECT 1;\n").digest()


def test_applies_all_pending_migrations_and_records_checksums_in_one_transaction(
    tmp_path: Path,
) -> None:
    """Break caught: partial commits could record schema history without all pending DDL."""
    module = migrations_module()
    write_migration(
        tmp_path,
        "001_contract.sql",
        "CREATE TABLE dbo.SchemaMigration (MigrationVersion int);\n",
    )
    write_migration(tmp_path, "002_core.sql", "-- APPLY CORE\nSELECT 2;\n")
    migrations = module.discover_migrations(tmp_path)
    connection = FakeConnection()

    applied = module.apply_migrations(connection, migrations)

    assert applied == 2
    assert connection.commit_count == 1
    assert connection.rollback_count == 0
    assert connection.records == {
        migration.version: (migration.name, migration.checksum) for migration in migrations
    }


def test_refuses_checksum_drift_before_applying_any_pending_migration(tmp_path: Path) -> None:
    """Break caught: editing applied history could silently redefine a deployed schema."""
    module = migrations_module()
    write_migration(tmp_path, "001_contract.sql", "SELECT N'changed';\n")
    write_migration(tmp_path, "002_pending.sql", "-- MUST NOT RUN\nSELECT 2;\n")
    migrations = module.discover_migrations(tmp_path)
    connection = FakeConnection()
    connection.table_exists = True
    connection.records[1] = ("contract", hashlib.sha256(b"SELECT N'original';\n").digest())

    with pytest.raises(module.MigrationError, match="checksum"):
        module.apply_migrations(connection, migrations)

    assert connection.executed_batches == []
    assert connection.commit_count == 0


def test_refuses_non_prefix_history_before_replaying_an_earlier_gap(tmp_path: Path) -> None:
    """Break caught: an older missing migration could run after a recorded newer version."""
    module = migrations_module()
    write_migration(tmp_path, "001_contract.sql", "SELECT 1;\n")
    write_migration(tmp_path, "002_core.sql", "SELECT 2;\n")
    migrations = module.discover_migrations(tmp_path)
    connection = FakeConnection()
    connection.table_exists = True
    connection.records[2] = ("core", migrations[1].checksum)

    with pytest.raises(module.MigrationError, match="prefix"):
        module.apply_migrations(connection, migrations)

    assert connection.executed_batches == []
    assert connection.commit_count == 0


def test_failed_migration_rolls_back_once_and_redacts_sql_credentials_and_parameters(
    tmp_path: Path,
) -> None:
    """Break caught: an exception could leak sensitive SQL/input or leave a partial schema."""
    module = migrations_module()
    synthetic_password = "synthetic-password-never-log"
    raw_parameter = "synthetic-applicant-value-never-log"
    write_migration(
        tmp_path,
        "001_contract.sql",
        "CREATE TABLE dbo.SchemaMigration (MigrationVersion int);\n",
    )
    write_migration(
        tmp_path,
        "002_failure.sql",
        f"-- FAIL HERE {synthetic_password}\nSELECT 2;\n",
    )
    connection = FakeConnection()
    connection.failure_marker = "FAIL HERE"
    connection.failure_message = f"driver exposed {synthetic_password} and {raw_parameter}"

    with pytest.raises(module.MigrationError) as raised:
        module.apply_migrations(connection, module.discover_migrations(tmp_path))

    message = str(raised.value)
    assert synthetic_password not in message
    assert raw_parameter not in message
    assert "SELECT" not in message
    assert connection.records == {}
    assert connection.commit_count == 0
    assert connection.rollback_count == 1


def test_second_run_is_an_idempotent_noop(tmp_path: Path) -> None:
    """Break caught: rerunning an unchanged release could replay DDL or duplicate history."""
    module = migrations_module()
    write_migration(
        tmp_path,
        "001_contract.sql",
        "CREATE TABLE dbo.SchemaMigration (MigrationVersion int);\n",
    )
    write_migration(tmp_path, "002_core.sql", "SELECT 2;\n")
    migrations = module.discover_migrations(tmp_path)
    connection = FakeConnection()

    assert module.apply_migrations(connection, migrations) == 2
    first_batches = list(connection.executed_batches)
    assert module.apply_migrations(connection, migrations) == 0

    assert connection.executed_batches == first_batches
    assert connection.commit_count == 1


def test_published_003_migration_and_current_validator_are_byte_stable() -> None:
    """Break caught: migration drift or unreviewed validator changes could strand validation."""
    migration_payload = (
        MIGRATION_DIRECTORY / "003_audit_and_preferences.sql"
    ).read_bytes()
    validator_payload = (
        VALIDATION_DIRECTORY / "003_validate_audit_and_preferences.sql"
    ).read_bytes()

    assert hashlib.sha256(migration_payload).digest() == PUBLISHED_003_MIGRATION_SHA256
    assert hashlib.sha256(validator_payload).digest() == CURRENT_003_VALIDATOR_SHA256


def test_original_003_prefix_upgrades_through_document_permissions() -> None:
    """Break caught: an original-003 database could skip the document security release."""
    module = migrations_module()
    migrations = module.discover_migrations(MIGRATION_DIRECTORY)
    connection = FakeConnection()
    connection.table_exists = True
    for migration in migrations[:2]:
        connection.records[migration.version] = (migration.name, migration.checksum)
    connection.records[3] = (
        "audit_and_preferences",
        PUBLISHED_003_MIGRATION_SHA256,
    )

    applied = module.apply_migrations(connection, migrations)

    assert applied == 6
    assert sorted(connection.records) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert connection.records[3][1] == PUBLISHED_003_MIGRATION_SHA256
    for migration in migrations[3:]:
        assert connection.records[migration.version] == (
            migration.name,
            migration.checksum,
        )
    assert connection.executed_batches == [
        "SET XACT_ABORT ON;",
        *(migration.sql for migration in migrations[3:]),
    ]
    assert connection.commit_count == 1


def test_repository_003_drift_still_blocks_004() -> None:
    """Break caught: a mismatched published 003 could be ignored when 004 is pending."""
    module = migrations_module()
    migrations = module.discover_migrations(MIGRATION_DIRECTORY)
    connection = FakeConnection()
    connection.table_exists = True
    for migration in migrations[:2]:
        connection.records[migration.version] = (migration.name, migration.checksum)
    connection.records[3] = ("audit_and_preferences", bytes(32))

    with pytest.raises(module.MigrationError, match="003 checksum"):
        module.apply_migrations(connection, migrations)

    assert connection.executed_batches == []
    assert connection.commit_count == 0


def test_fresh_repository_run_applies_all_nine_migrations() -> None:
    """Break caught: a new database could omit 009 or apply the release out of order."""
    module = migrations_module()
    migrations = module.discover_migrations(MIGRATION_DIRECTORY)
    connection = FakeConnection()

    applied = module.apply_migrations(connection, migrations)

    assert [migration.version for migration in migrations] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert applied == 9
    assert connection.records == {
        migration.version: (migration.name, migration.checksum)
        for migration in migrations
    }
    assert connection.commit_count == 1


def test_connection_string_uses_only_ehf_names_and_task_2_secret_reader() -> None:
    """Break caught: EHF could inherit the Finances 2 database identity or credential path."""
    module = importlib.import_module("app.db")

    class SyntheticSettings:
        def read_sql_credential(self) -> str:
            return "synthetic-secret"

    value = module.connection_string(
        SyntheticSettings(),
        {
            "EHF_SQL_SERVER": "tcp:ehf-db.invalid,1433",
            "EHF_SQL_DATABASE": "EHFApplications_Test_Unit",
            "EHF_SQL_USER": "ehf_test",
            "FINANCES2_DB_NAME": "must-not-be-used",
        },
    )

    assert "SERVER=tcp:ehf-db.invalid,1433" in value
    assert "DATABASE=EHFApplications_Test_Unit" in value
    assert "UID=ehf_test" in value
    assert "PWD=synthetic-secret" in value
    assert "must-not-be-used" not in value


def test_connection_string_brace_escapes_password_delimiters() -> None:
    """Break caught: password punctuation could inject an ODBC connection-string field."""
    module = importlib.import_module("app.db")

    class SyntheticSettings:
        def read_sql_credential(self) -> str:
            return "synthetic;secret}value"

    value = module.connection_string(SyntheticSettings(), {})

    assert "PWD={synthetic;secret}}value};" in value
    assert "PWD=synthetic;secret}value;" not in value


def test_connection_session_error_is_redacted_and_connection_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: driver text from session setup could expose the connection secret."""
    module = importlib.import_module("app.db")
    synthetic_password = "session-secret-never-log"

    class SyntheticSettings:
        def read_sql_credential(self) -> str:
            return synthetic_password

    class SyntheticDriverError(Exception):
        pass

    class BrokenConnection:
        def __init__(self) -> None:
            self.closed = False

        def execute(self, _statement: str) -> None:
            raise SyntheticDriverError(f"driver echoed {synthetic_password}")

        def close(self) -> None:
            self.closed = True

    connection = BrokenConnection()
    fake_pyodbc = SimpleNamespace(
        Error=SyntheticDriverError,
        connect=lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setitem(sys.modules, "pyodbc", fake_pyodbc)

    with pytest.raises(module.DatabaseError) as raised:
        with module.connect(SyntheticSettings(), environ={}):
            pass

    assert synthetic_password not in str(raised.value)
    assert connection.closed is True


def sql_table_blocks() -> dict[str, str]:
    blocks: dict[str, str] = {}
    for path in sorted(MIGRATION_DIRECTORY.glob("[0-9][0-9][0-9]_*.sql")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"CREATE TABLE dbo\.(\w+)\s*\((.*?)^\);",
            source,
            flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
        ):
            blocks[match.group(1)] = match.group(2)
    return blocks


def test_sql_contract_files_and_validators_exist() -> None:
    """Break caught: a release could omit one ordered schema or validation artifact."""
    assert [path.name for path in sorted(MIGRATION_DIRECTORY.glob("*.sql"))] == [
        "001_database_contract.sql",
        "002_application_core.sql",
        "003_audit_and_preferences.sql",
        "004_audit_and_preference_hardening.sql",
        "005_application_permissions.sql",
        "006_user_preference_read.sql",
        "007_document_store.sql",
        "008_import_provenance.sql",
        "009_document_permissions.sql",
    ]
    assert [path.name for path in sorted(VALIDATION_DIRECTORY.glob("*.sql"))] == [
        "001_validate_database_contract.sql",
        "002_validate_application_core.sql",
        "003_validate_audit_and_preferences.sql",
        "004_validate_audit_and_preference_hardening.sql",
        "005_validate_application_permissions.sql",
        "006_validate_user_preference_read.sql",
        "007_validate_document_store.sql",
        "008_validate_import_provenance.sql",
        "009_validate_document_permissions.sql",
    ]


def test_every_table_has_a_primary_key_and_database_generated_utc_timestamp() -> None:
    """Break caught: a core entity could lack stable identity or auditable UTC creation time."""
    blocks = sql_table_blocks()

    assert set(blocks) == {
        "SchemaMigration",
        "FellowshipCall",
        "Applicant",
        "ApplicantContact",
        "Application",
        "EmploymentAffiliation",
        "Qualification",
        "EligibilityDeclaration",
        "Bibliometrics",
        "ContributionStatement",
        "FieldProvenance",
        "ApplicationSectionVersion",
        "AuditEvent",
        "UserPreference",
        "DocumentSlot",
        "Document",
        "StoredObject",
        "DocumentVersion",
        "Recommendation",
        "ImportRun",
        "ImportRow",
        "SourceOccurrence",
        "CallSourceOccurrence",
        "ImportException",
        "ClassificationDecision",
    }
    for table_name, block in blocks.items():
        assert re.search(r"\bPRIMARY KEY\b", block, flags=re.IGNORECASE), table_name
        assert re.search(
            r"\b(?:Applied|Created|Recorded|Occurred|Started|Observed|Decided)AtUtc\s+datetime2\(7\)",
            block,
            flags=re.IGNORECASE,
        ), table_name
        assert "SYSUTCDATETIME()" in block, table_name


def test_mutable_tables_have_rowversion_and_immutable_tables_reject_update_delete() -> None:
    """Break caught: concurrent writes or historical-record mutation could go undetected."""
    blocks = sql_table_blocks()
    mutable_tables = {
        "FellowshipCall",
        "Applicant",
        "ApplicantContact",
        "Application",
        "EmploymentAffiliation",
        "Qualification",
        "EligibilityDeclaration",
        "Bibliometrics",
        "ContributionStatement",
        "UserPreference",
    }
    for table_name in mutable_tables:
        assert re.search(r"\bRowVersion\s+rowversion\b", blocks[table_name], re.IGNORECASE)

    all_sql = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(MIGRATION_DIRECTORY.glob("*.sql"))
    )
    for table_name in {
        "SchemaMigration",
        "FieldProvenance",
        "ApplicationSectionVersion",
        "AuditEvent",
        "StoredObject",
        "DocumentVersion",
        "ImportRow",
        "SourceOccurrence",
        "ClassificationDecision",
    }:
        assert re.search(
            rf"CREATE TRIGGER .*?\s+ON\s+dbo\.{table_name}.*?"
            r"INSTEAD\s+OF\s+UPDATE,\s*DELETE",
            all_sql,
            flags=re.IGNORECASE | re.DOTALL,
        ), table_name


def test_provenance_and_section_history_have_independent_versions() -> None:
    """Break caught: field history could depend on section versions or timestamp uniqueness."""
    blocks = sql_table_blocks()

    for table_name in {"FieldProvenance", "ApplicationSectionVersion"}:
        assert re.search(
            r"\bVersionNumber\s+int\s+NOT NULL\b",
            blocks[table_name],
            flags=re.IGNORECASE,
        ), table_name
        assert re.search(
            r"\bCHECK\s*\(VersionNumber\s*>\s*0\)",
            blocks[table_name],
            flags=re.IGNORECASE,
        ), table_name


def test_audit_payload_policy_normalizes_aliases_at_every_json_depth() -> None:
    """Break caught: casing, separators, aliases, or nesting could bypass redaction policy."""
    migration = (
        MIGRATION_DIRECTORY / "004_audit_and_preference_hardening.sql"
    ).read_text(encoding="utf-8")
    validator = (
        VALIDATION_DIRECTORY / "004_validate_audit_and_preference_hardening.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE FUNCTION dbo.IsAuditPayloadKeyProhibited" in migration
    assert re.search(
        r"ALTER TRIGGER dbo\.TR_AuditEvent_RejectSensitivePayload.*?UNION ALL.*?"
        r"dbo\.IsAuditPayloadKeyProhibited\(JsonKey\)\s*=\s*1",
        migration,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for separator in ("_", "-", " ", ".", "/"):
        assert re.search(
            rf"REPLACE\s*\(.*?N''{re.escape(separator)}''\s*,\s*N''''\s*\)",
            migration,
            flags=re.IGNORECASE | re.DOTALL,
        ), separator

    assert re.search(
        r"IF\s+@NormalizedKey\s+IN\s*\(.*?\)\s*RETURN\s+0\s*;\s*"
        r"RETURN\s+1\s*;",
        migration,
        flags=re.IGNORECASE | re.DOTALL,
    ), "audit payload keys must be explicitly allowed and unknown keys rejected"

    for prohibited_alias in (
        "apiToken",
        "API-TOKEN",
        "clientSecret",
        "client_secret",
        "otpValue",
        "otp.value",
        "resumeDocument",
        "resume-document",
        "incomingRequestBody",
        "incoming/request/body",
        "credentialBlob",
        "rawFileBytes",
        "unexpectedMetadata",
    ):
        assert prohibited_alias.casefold() in validator.casefold(), prohibited_alias
    assert re.search(
        r'\{"after":\{"before":\{"apiToken":"prohibited"\}\}\}',
        validator,
        flags=re.IGNORECASE,
    ), "validator must reach a prohibited key through allowed nested object keys"

    for allowed_fact in ("applicationId", "documentId", "requestId", "before", "after"):
        assert allowed_fact.casefold() in validator.casefold(), allowed_fact


def test_user_preference_guard_uses_unspoofable_module_execution_context() -> None:
    """Break caught: a table-DML caller could forge session state and skip auditing."""
    migration = (
        MIGRATION_DIRECTORY / "004_audit_and_preference_hardening.sql"
    ).read_text(encoding="utf-8")
    validator = (
        VALIDATION_DIRECTORY / "004_validate_audit_and_preference_hardening.sql"
    ).read_text(encoding="utf-8")

    assert "SESSION_CONTEXT" not in migration
    assert "EXECUTE AS OWNER" not in migration
    assert "CREATE USER EHFPreferenceProcedureExecutor WITHOUT LOGIN" in migration
    assert (
        "DENY IMPERSONATE ON USER::EHFPreferenceProcedureExecutor TO public"
        in migration
    )
    assert re.search(
        r"ALTER PROCEDURE dbo\.SetUserPreference.*?END;\s*'\);\s*"
        r"DENY IMPERSONATE ON USER::EHFPreferenceProcedureExecutor TO public",
        migration,
        flags=re.IGNORECASE | re.DOTALL,
    ), "bind the module execution context before denying runtime impersonation"
    assert re.search(
        r"ALTER TRIGGER dbo\.TR_UserPreference_ProcedureOnly.*?"
        r"AFTER\s+INSERT,\s*UPDATE,\s*DELETE.*?"
        r"USER_NAME\(\)\s*<>\s*N''EHFPreferenceProcedureExecutor''",
        migration,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert re.search(
        r"ALTER PROCEDURE dbo\.SetUserPreference.*?"
        r"WITH\s+EXECUTE\s+AS\s+''EHFPreferenceProcedureExecutor''\s+AS",
        migration,
        flags=re.IGNORECASE | re.DOTALL,
    )

    for contract_fragment in (
        "DATABASE_PRINCIPAL_ID(N'EHFPreferenceProcedureExecutor')",
        "execute_as_principal_id",
        "HAS_PERMS_BY_NAME",
        "IMPERSONATE",
        "CREATE USER EHFPreferenceDmlValidator WITHOUT LOGIN",
        "GRANT INSERT, UPDATE, DELETE ON dbo.UserPreference",
        "GRANT EXECUTE ON dbo.SetUserPreference",
        "EXECUTE AS USER = N'EHFPreferenceDmlValidator'",
        "EHF.UserPreferenceProcedure",
        "EXEC dbo.SetUserPreference",
        "REVERT",
    ):
        assert contract_fragment.casefold() in validator.casefold(), contract_fragment


def test_database_script_requires_and_applies_009() -> None:
    """Break caught: the isolated harness could stop before the document boundary release."""
    script = DATABASE_SCRIPT.read_text(encoding="utf-8")

    assert "004_audit_and_preference_hardening.sql" in script
    assert "004_validate_audit_and_preference_hardening.sql" in script
    assert "005_application_permissions.sql" in script
    assert "005_validate_application_permissions.sql" in script
    assert "006_user_preference_read.sql" in script
    assert "006_validate_user_preference_read.sql" in script
    assert "007_document_store.sql" in script
    assert "007_validate_document_store.sql" in script
    assert "008_import_provenance.sql" in script
    assert "008_validate_import_provenance.sql" in script
    assert "009_document_permissions.sql" in script
    assert "009_validate_document_permissions.sql" in script
    assert "Applied 9 migration\\(s\\)\\." in script


def test_database_script_enables_quoted_identifier_for_every_sqlcmd_session() -> None:
    """Break caught: a fresh validator session could reject filtered-index DML."""
    script = DATABASE_SCRIPT.read_text(encoding="utf-8")
    arguments = re.search(
        r"\$arguments\s*=\s*@\((.*?)\n\s*\)",
        script,
        flags=re.DOTALL,
    )

    assert arguments is not None
    assert "'-I'" in arguments.group(1)


def validator_section(source: str, marker: str) -> str:
    section = re.search(
        rf"{re.escape(marker)}(?P<section>.*?)(?=\n-- ISOLATED EXPECTED FAILURE:|\n-- SUCCESSFUL VALIDATOR WRITES|\Z)",
        source,
        flags=re.DOTALL,
    )
    assert section is not None, marker
    return section.group("section")


def assert_isolated_expected_failure(source: str, marker: str, expected_error: int) -> None:
    section = validator_section(source, marker)

    assert re.search(r"BEGIN TRANSACTION;\s*BEGIN TRY", section)
    assert re.search(
        rf"IF (?:ERROR_NUMBER\(\)|@\w*ErrorNumber) <> {expected_error}\s*(?:THROW;|BEGIN)",
        section,
    )
    assert "IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;" in section


def test_validator_003_isolates_expected_failures_and_rolls_back_successful_writes() -> None:
    """Break caught: one poisoned trigger transaction could mask later validator assertions."""
    validator = (
        VALIDATION_DIRECTORY / "003_validate_audit_and_preferences.sql"
    ).read_text(encoding="utf-8")

    assert "-- ISOLATED EXPECTED FAILURE:" in validator
    first_failure = validator.index("-- ISOLATED EXPECTED FAILURE:")
    assert "BEGIN TRANSACTION;" not in validator[:first_failure]
    for marker, expected_error in (
        ("-- ISOLATED EXPECTED FAILURE: audit update", 51031),
        ("-- ISOLATED EXPECTED FAILURE: prohibited audit payload", 51032),
        ("-- ISOLATED EXPECTED FAILURE: direct preference DML", 51033),
    ):
        assert_isolated_expected_failure(validator, marker, expected_error)

    successful_writes = validator_section(
        validator, "-- SUCCESSFUL VALIDATOR WRITES (ROLLED BACK)"
    )
    assert re.search(r"BEGIN TRANSACTION;.*?ROLLBACK TRANSACTION;", successful_writes, re.DOTALL)
    assert "COMMIT TRANSACTION" not in validator


def test_validator_004_isolates_expected_failures_and_cleans_up_successful_writes() -> None:
    """Break caught: hardened rejection loops must restore a committable session before later writes."""
    validator = (
        VALIDATION_DIRECTORY / "004_validate_audit_and_preference_hardening.sql"
    ).read_text(encoding="utf-8")

    assert "-- ISOLATED EXPECTED FAILURE:" in validator
    first_failure = validator.index("-- ISOLATED EXPECTED FAILURE:")
    assert "BEGIN TRANSACTION;" not in validator[:first_failure]
    assert_isolated_expected_failure(
        validator,
        "-- ISOLATED EXPECTED FAILURE: prohibited audit payload aliases",
        51032,
    )
    assert_isolated_expected_failure(
        validator,
        "-- ISOLATED EXPECTED FAILURE: direct preference DML",
        51033,
    )

    successful_writes = validator_section(
        validator, "-- SUCCESSFUL VALIDATOR WRITES (ROLLED BACK)"
    )
    assert re.search(r"BEGIN TRANSACTION;.*?ROLLBACK TRANSACTION;", successful_writes, re.DOTALL)
    assert "COMMIT TRANSACTION" not in validator
    assert "DROP USER EHFPreferenceDmlValidator" in validator


def test_validator_cleanup_rolls_back_before_session_context_or_revert() -> None:
    """Break caught: cleanup could execute inside a doomed trigger transaction and raise Msg 3930."""
    validator_003 = (
        VALIDATION_DIRECTORY / "003_validate_audit_and_preferences.sql"
    ).read_text(encoding="utf-8")
    validator_004 = (
        VALIDATION_DIRECTORY / "004_validate_audit_and_preference_hardening.sql"
    ).read_text(encoding="utf-8")

    assert not re.search(
        r"BEGIN CATCH\s+EXEC sys\.sp_set_session_context.*?"
        r"IF XACT_STATE\(\) <> 0 ROLLBACK TRANSACTION;",
        validator_003,
        flags=re.DOTALL,
    )
    direct_section = validator_section(
        validator_004, "-- ISOLATED EXPECTED FAILURE: direct preference DML"
    )
    assert "DECLARE @DirectPreferenceErrorNumber int = ERROR_NUMBER();" in direct_section

    cleanup_catches = re.findall(
        r"BEGIN CATCH(?P<body>.*?)(?=END CATCH;)",
        validator_004,
        flags=re.DOTALL,
    )
    for body in cleanup_catches:
        cleanup_positions = [
            position
            for position in (
                body.find("EXEC sys.sp_set_session_context"),
                body.find("REVERT;"),
            )
            if position >= 0
        ]
        if cleanup_positions:
            rollback_position = body.find("IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;")
            assert rollback_position >= 0
            assert rollback_position < min(cleanup_positions)


def test_database_contract_validator_reports_version_nine() -> None:
    """Break caught: post-upgrade validation could still require the old 005 tip."""
    validator = (
        VALIDATION_DIRECTORY / "001_validate_database_contract.sql"
    ).read_text(encoding="utf-8")

    assert "COUNT_BIG(*) FROM dbo.SchemaMigration) <> 9" in validator
    assert "WHERE MigrationCount = 9 AND CurrentVersion = 9" in validator


def test_database_script_rejects_a_non_test_database_before_connecting() -> None:
    """Break caught: the integration harness could target a production database name."""
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-File",
            str(DATABASE_SCRIPT),
            "-DatabaseName",
            "EHFApplications",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode != 0
    assert "must start exactly with EHFApplications_Test" in (
        completed.stdout + completed.stderr
    )
