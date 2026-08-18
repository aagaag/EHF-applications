from __future__ import annotations

import hashlib
import importlib
import re
import shutil
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


def test_original_003_prefix_upgrades_through_applicant_admin_preview() -> None:
    """Break caught: an original-003 database could skip the current security release."""
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

    assert applied == 16
    assert sorted(connection.records) == list(range(1, 20))
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


def test_fresh_repository_run_applies_all_nineteen_migrations() -> None:
    """Break caught: a new database could omit the synthetic-session boundary."""
    module = migrations_module()
    migrations = module.discover_migrations(MIGRATION_DIRECTORY)
    connection = FakeConnection()

    applied = module.apply_migrations(connection, migrations)

    assert [migration.version for migration in migrations] == list(range(1, 20))
    assert applied == 19
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
        "010_report_export_audit.sql",
        "011_applicant_access.sql",
        "012_applicant_drafts.sql",
        "013_applicant_confirmations.sql",
        "014_applicant_projection.sql",
        "015_applicant_document_slots.sql",
        "016_entra_applicant_workflow.sql",
        "017_applicant_form_simplification.sql",
        "018_applicant_admin_preview.sql",
        "019_synthetic_applicant_workspace.sql",
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
        "010_validate_report_export_audit.sql",
        "011_validate_applicant_access.sql",
        "012_validate_applicant_drafts.sql",
        "013_validate_applicant_confirmations.sql",
        "014_validate_applicant_projection.sql",
        "015_validate_applicant_document_slots.sql",
        "016_validate_entra_applicant_workflow.sql",
        "017_validate_applicant_form_simplification.sql",
        "018_validate_applicant_admin_preview.sql",
        "019_validate_synthetic_applicant_workspace.sql",
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
        "ApplicantInvitation",
        "ApplicantPreAuthContext",
        "ApplicantVerificationChallenge",
        "ApplicantSession",
        "ApplicantRateLimitBucket",
        "ApplicantSectionDraft",
        "ApplicantFieldCorrection",
        "ApplicantSectionConfirmation",
        "ApplicantFinalConfirmation",
        "ApplicantReopenScope",
        "ApplicantDocumentSubmission",
        "ApplicantAccessRequest",
        "ApplicantEntraIdentity",
        "ApplicantPortalBaseline",
        "ApplicantFinalReviewDecision",
        "ApplicantDocumentReviewDecision",
        "ApplicantSyntheticWorkspace",
    }
    for table_name, block in blocks.items():
        assert re.search(r"\bPRIMARY KEY\b", block, flags=re.IGNORECASE), table_name
        assert re.search(
            r"\b(?:Applied|Created|Recorded|Occurred|Started|Observed|Decided|Requested|Linked)AtUtc\s+datetime2\(7\)",
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
        "ApplicantInvitation",
        "ApplicantPreAuthContext",
        "ApplicantVerificationChallenge",
        "ApplicantSession",
        "ApplicantRateLimitBucket",
        "ApplicantSectionDraft",
        "ApplicantReopenScope",
        "ApplicantDocumentSubmission",
        "ApplicantAccessRequest",
        "ApplicantEntraIdentity",
        "ApplicantPortalBaseline",
        "ApplicantSyntheticWorkspace",
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
        "ApplicantFieldCorrection",
        "ApplicantSectionConfirmation",
        "ApplicantFinalConfirmation",
        "ApplicantFinalReviewDecision",
        "ApplicantDocumentReviewDecision",
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


def test_database_script_requires_and_applies_019() -> None:
    """Break caught: the isolated harness could skip the synthetic-session boundary."""
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
    assert "010_report_export_audit.sql" in script
    assert "010_validate_report_export_audit.sql" in script
    assert "011_applicant_access.sql" in script
    assert "011_validate_applicant_access.sql" in script
    assert "012_applicant_drafts.sql" in script
    assert "012_validate_applicant_drafts.sql" in script
    assert "013_applicant_confirmations.sql" in script
    assert "013_validate_applicant_confirmations.sql" in script
    assert "014_applicant_projection.sql" in script
    assert "014_validate_applicant_projection.sql" in script
    assert "015_applicant_document_slots.sql" in script
    assert "015_validate_applicant_document_slots.sql" in script
    assert "016_entra_applicant_workflow.sql" in script
    assert "016_validate_entra_applicant_workflow.sql" in script
    assert "017_applicant_form_simplification.sql" in script
    assert "017_validate_applicant_form_simplification.sql" in script
    assert "018_applicant_admin_preview.sql" in script
    assert "018_validate_applicant_admin_preview.sql" in script
    assert "019_synthetic_applicant_workspace.sql" in script
    assert "019_validate_synthetic_applicant_workspace.sql" in script
    assert "Applied 19 migration\\(s\\)\\." in script


def test_synthetic_applicant_workspace_preserves_the_legacy_session_contract() -> None:
    """Break caught: a synthetic administrator session could be accepted as a real applicant session."""
    migration_path = MIGRATION_DIRECTORY / "019_synthetic_applicant_workspace.sql"
    validator_path = VALIDATION_DIRECTORY / "019_validate_synthetic_applicant_workspace.sql"
    migration = migration_path.read_text(encoding="utf-8")
    validator = validator_path.read_text(encoding="utf-8")

    assert re.search(
        r"CREATE TABLE dbo\.ApplicantSyntheticWorkspace.*?"
        r"ApplicationId uniqueidentifier NOT NULL.*?"
        r"CreatedByIdentity nvarchar\(255\) NOT NULL.*?"
        r"ClosedAtUtc datetime2\(7\) NULL.*?"
        r"PRIMARY KEY.*?"
        r"LEN\(CreatedByIdentity\) > 0",
        migration,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert "UQ_ApplicantSyntheticWorkspace_Application" not in migration
    assert re.search(
        r"ALTER TABLE dbo\.ApplicantSession\s+ADD SyntheticActorIdentity nvarchar\(255\) NULL",
        migration,
        flags=re.IGNORECASE,
    )
    assert re.search(
        r"CK_ApplicantSession_AuthenticationSource.*?"
        r"ApplicantInvitationId IS NOT NULL AND EntraObjectId IS NULL AND SyntheticActorIdentity IS NULL.*?"
        r"ApplicantInvitationId IS NULL AND EntraObjectId IS NOT NULL AND SyntheticActorIdentity IS NULL.*?"
        r"ApplicantInvitationId IS NULL AND EntraObjectId IS NULL AND SyntheticActorIdentity IS NOT NULL",
        migration,
        flags=re.IGNORECASE | re.DOTALL,
    )
    create_procedure = re.search(
        r"CREATE PROCEDURE dbo\.CreateSyntheticApplicantWorkspace.*?END;\s*'\);",
        migration,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert create_procedure is not None
    assert "@ApplicationId" not in create_procedure.group(0)
    assert "@ActorGroup IS NULL" in create_procedure.group(0)
    assert "NULLIF(LTRIM(RTRIM(@ActorIdentity))" in create_procedure.group(0)
    for fragment in (
        "@ActorIdentity nvarchar(255)",
        "@ActorGroup nvarchar(128)",
        "@SessionTokenSha256 binary(32)",
        "@CsrfTokenSha256 binary(32)",
        "@IdleExpiresAtUtc datetime2(7)",
        "@AbsoluteExpiresAtUtc datetime2(7)",
        "EHF-Administrators",
        "NEWID()",
        "SYNTHETIC_APPLICANT_WORKSPACE_CREATED",
    ):
        assert fragment.casefold() in create_procedure.group(0).casefold(), fragment
    assert re.search(
        r"ALTER PROCEDURE dbo\.GetApplicantSession.*?"
        r"SELECT session_row\.ApplicationId, session_row\.CsrfTokenSha256,\s*"
        r"session_row\.IdleExpiresAtUtc, session_row\.AbsoluteExpiresAtUtc,\s*"
        r"session_row\.ApplicantInvitationId, session_row\.EntraObjectId.*?"
        r"NOT EXISTS\s*\(\s*SELECT 1\s*FROM dbo\.ApplicantSyntheticWorkspace",
        migration,
        flags=re.IGNORECASE | re.DOTALL,
    )
    v19_procedure = re.search(
        r"CREATE PROCEDURE dbo\.GetApplicantSessionV19.*?END;\s*'\);",
        migration,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert v19_procedure is not None
    assert "workspace_row.CreatedByIdentity = session_row.SyntheticActorIdentity" in v19_procedure.group(0)
    assert "workspace_row.ClosedAtUtc IS NULL" in v19_procedure.group(0)
    assert v19_procedure.group(0).count("ApplicantSyntheticWorkspace") >= 4
    for fragment in (
        "GRANT EXECUTE ON dbo.CreateSyntheticApplicantWorkspace TO EHFApplicationRuntime",
        "GRANT EXECUTE ON dbo.GetApplicantSessionV19 TO EHFApplicationRuntime",
        "DENY SELECT, INSERT, UPDATE, DELETE ON dbo.ApplicantSyntheticWorkspace TO EHFApplicationRuntime",
        "GetApplicantSessionV19",
        "legacy",
        "synthetic",
        "actor",
        "EHF-Administrators",
    ):
        assert fragment.casefold() in (migration + validator).casefold(), fragment
    for procedure_name in (
        "ListApplicantPreviews",
        "GetApplicantPreview",
        "GetInternalApplicationMetrics",
        "ProvisionApplicantAccessRequest",
        "ApproveApplicantSubmission",
        "SubmitApplicantFinalConfirmation",
        "ListPendingApplicantSubmissions",
        "GetApplicantSubmissionReview",
    ):
        procedure = re.search(
            rf"ALTER PROCEDURE dbo\.{procedure_name}.*?END;\s*'\);",
            migration,
            flags=re.IGNORECASE | re.DOTALL,
        )
        assert procedure is not None, procedure_name
        assert "ApplicantSyntheticWorkspace" in procedure.group(0), procedure_name
    for fragment in (
        "@ActorGroup=NULL",
        "EXECUTE AS USER = N'ehf_app'",
        "GetApplicantPreview",
        "GetInternalApplicationMetrics",
        "ProvisionApplicantAccessRequest",
        "SubmitApplicantFinalConfirmation",
        "ListPendingApplicantSubmissions",
        "ApproveApplicantSubmission",
    ):
        assert fragment.casefold() in validator.casefold(), fragment


def test_sql_login_harness_denies_runtime_direct_synthetic_workspace_dml() -> None:
    """Break caught: the isolated runtime probe could omit the new synthetic marker table."""
    script = (ROOT / "infra" / "test-sql-login.sh").read_text(encoding="utf-8")

    assert "(N'ApplicantSyntheticWorkspace',N'ApplicationId')" in script


def test_sql_login_harness_executes_validator_artifacts_not_migrations_twice() -> None:
    """Break caught: the isolated validator loop could accidentally rerun migration 007 or 009."""
    script = (ROOT / "infra" / "test-sql-login.sh").read_text(encoding="utf-8")
    validation_loop = script.split("for validation_file in ", 1)[1].split("; do", 1)[0]

    assert "007_validate_document_store.sql" in validation_loop
    assert "009_validate_document_permissions.sql" in validation_loop
    assert " 007_document_store.sql" not in validation_loop
    assert " 009_document_permissions.sql" not in validation_loop


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


def test_database_contract_validator_reports_version_nineteen() -> None:
    """Break caught: post-upgrade validation could still require the old schema tip."""
    validator = (
        VALIDATION_DIRECTORY / "001_validate_database_contract.sql"
    ).read_text(encoding="utf-8")

    assert "COUNT_BIG(*) FROM dbo.SchemaMigration) <> 19" in validator
    assert "WHERE MigrationCount = 19 AND CurrentVersion = 19" in validator


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell controller contract")
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
