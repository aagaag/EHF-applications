from __future__ import annotations

from pathlib import Path
import os
import re
import subprocess
import importlib.util

import pytest


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "database" / "migrations"
VALIDATORS = ROOT / "database" / "tests"
MIGRATION = MIGRATIONS / "005_application_permissions.sql"
SETUP_SCRIPT = ROOT / "infra" / "setup-sql-login.sh"
TEST_SCRIPT = ROOT / "infra" / "test-sql-login.sh"
HELPER = ROOT / "infra" / "sql-principal.py"
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe") if os.name == "nt" else Path("/bin/bash")

PROTECTED_TABLES = (
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
)


def test_permission_boundary_release_artifacts_exist() -> None:
    """Break caught: a permission release could omit a required enforcement artifact."""
    assert (MIGRATIONS / "005_application_permissions.sql").is_file()
    assert (VALIDATORS / "005_validate_application_permissions.sql").is_file()
    assert (ROOT / "infra" / "setup-sql-login.sh").is_file()
    assert (ROOT / "infra" / "test-sql-login.sh").is_file()
    assert (ROOT / "infra" / "sql-principal.py").is_file()
    assert (ROOT / "docs" / "permissions.md").is_file()
    assert (MIGRATIONS / "010_report_export_audit.sql").is_file()
    assert (VALIDATORS / "010_validate_report_export_audit.sql").is_file()


def test_permission_validator_covers_runtime_allow_and_deny_contract() -> None:
    """Break caught: a migration could publish a runtime role without validating its boundary."""
    validator = (VALIDATORS / "005_validate_application_permissions.sql").read_text(
        encoding="utf-8"
    )

    for fragment in (
        "dbo.RuntimeHealth",
        "dbo.SetUserPreference",
        "dbo.GetUserPreference",
        "dbo.SetApplicationStatus",
        "dbo.ValidateApplicationInvitation",
        "dbo.GetInternalApplicationMetrics",
        "dbo.RecordReportExportAudit",
        "EHFApplicationRuntime",
        "sys.database_permissions",
        "The runtime role has a missing or altered permission row.",
    ):
        assert fragment in validator
    assert "SET XACT_ABORT OFF;" in validator


def test_permission_migrations_deny_direct_table_access_and_publish_only_approved_procedures() -> None:
    """Break caught: the runtime role could gain a table grant or unreviewed module access."""
    migration = MIGRATION.read_text(encoding="utf-8")
    permission_migrations = "\n".join(
        (
            migration,
            (MIGRATIONS / "009_document_permissions.sql").read_text(encoding="utf-8"),
            (MIGRATIONS / "010_report_export_audit.sql").read_text(encoding="utf-8"),
        )
    )

    assert "CREATE ROLE EHFApplicationRuntime" in migration
    assert "CREATE USER ehf_app WITHOUT LOGIN" in migration
    for table_name in PROTECTED_TABLES:
        assert (
            f"DENY SELECT, INSERT, UPDATE, DELETE ON dbo.{table_name}"
            " TO EHFApplicationRuntime;"
        ) in permission_migrations
    for procedure_name in (
        "RuntimeHealth",
        "SetUserPreference",
        "SetApplicationStatus",
    ):
        assert (
            f"GRANT EXECUTE ON dbo.{procedure_name} TO EHFApplicationRuntime;"
        ) in migration
    preference_read = (MIGRATIONS / "006_user_preference_read.sql").read_text(encoding="utf-8")
    assert "CREATE PROCEDURE dbo.GetUserPreference" in preference_read
    assert "GRANT EXECUTE ON dbo.GetUserPreference TO EHFApplicationRuntime;" in preference_read
    assert "GRANT SELECT ON SCHEMA::dbo" not in migration
    assert "GRANT EXECUTE ON SCHEMA::dbo" not in migration
    assert "DENY ALTER, CONTROL ON SCHEMA::dbo" not in migration
    assert "REVOKE CONNECT FROM ehf_app;" in migration


def test_report_export_audit_uses_a_procedure_only_execution_principal() -> None:
    migration = (MIGRATIONS / "010_report_export_audit.sql").read_text(encoding="utf-8")
    validator = (VALIDATORS / "010_validate_report_export_audit.sql").read_text(
        encoding="utf-8"
    )

    for fragment in (
        "CREATE USER EHFReportExportAuditExecutor WITHOUT LOGIN",
        "CREATE PROCEDURE dbo.RecordReportExportAudit",
        "WITH EXECUTE AS ''EHFReportExportAuditExecutor''",
        "@ActorGroup NOT IN (N''EHF-Administrators'', N''EHF-Trustees'')",
        "@Outcome NOT IN (N''COMPLETED'', N''FAILED'')",
        "REPORT_EXPORT_COMPLETED",
        "REPORT_EXPORT_FAILED",
        "FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES",
        "GRANT EXECUTE ON dbo.RecordReportExportAudit TO EHFApplicationRuntime",
        "DENY IMPERSONATE ON USER::EHFReportExportAuditExecutor TO public",
    ):
        assert fragment in migration
    for key in ("actorGroup", "rowCount", "format", "outcome", "failureStage"):
        assert key in migration
    assert "GRANT INSERT ON dbo.AuditEvent TO EHFApplicationRuntime" not in migration
    assert "GRANT SELECT ON dbo.AuditEvent TO EHFApplicationRuntime" not in migration
    assert "PASS 010 report export audit" in validator


def test_permission_validator_leaves_real_login_checks_to_the_isolated_verifier() -> None:
    """Break caught: a database-scoped impersonation check could claim server-login coverage."""
    validator = (VALIDATORS / "005_validate_application_permissions.sql").read_text(
        encoding="utf-8"
    )

    for fragment in (
        "sys.database_permissions",
        "EHFApplicationRuntime",
        "The runtime role has a missing or altered permission row.",
        "infra/test-sql-login.sh",
    ):
        assert fragment in validator
    assert "EXECUTE AS USER =" not in validator


def test_permission_validator_rejects_direct_runtime_user_grants_and_unexpected_roles() -> None:
    """Break caught: the mapped user could bypass its one approved runtime role."""
    validator = (VALIDATORS / "005_validate_application_permissions.sql").read_text(
        encoding="utf-8"
    )

    assert "The runtime user has a direct permission." in validator
    assert "The runtime user has an unexpected role." in validator


def test_permission_validator_rejects_unapproved_runtime_grants_and_ownership() -> None:
    """Break caught: the runtime role could inherit object access or own a database object."""
    validator = (VALIDATORS / "005_validate_application_permissions.sql").read_text(encoding="utf-8")
    assert "The runtime role has an unapproved permission row or state." in validator
    assert "The runtime role owns a database object." in validator


def test_permission_validator_requires_the_exact_permission_rows_and_states() -> None:
    """Break caught: GRANT_WITH_GRANT_OPTION or a missing scoped DENY could broaden the runtime role."""
    validator = (VALIDATORS / "005_validate_application_permissions.sql").read_text(encoding="utf-8")

    assert "@ProtectedTables" in validator
    assert "@RequiredDmlDenies" in validator
    assert "@ProtectedViews" in validator
    assert "@ExpectedPermissions" in validator
    for permission_row in (
        "(0, 0, 0, N'CONNECT', N'GRANT')",
        "(0, 0, 0, N'VIEW DEFINITION', N'DENY')",
        "(0, 0, 0, N'CREATE TABLE', N'DENY')",
        "(0, 0, 0, N'CREATE PROCEDURE', N'DENY')",
        "(0, 0, 0, N'CREATE VIEW', N'DENY')",
        "(0, 0, 0, N'ALTER ANY SCHEMA', N'DENY')",
        "(0, 0, 0, N'ALTER ANY USER', N'DENY')",
        "(0, 0, 0, N'ALTER ANY ROLE', N'DENY')",
        "(3, SCHEMA_ID(N'dbo'), 0, N'ALTER', N'DENY')",
        "(4, DATABASE_PRINCIPAL_ID(N'EHFPreferenceProcedureExecutor'), 0, N'IMPERSONATE', N'DENY')",
    ):
        assert permission_row in validator
    assert "permission_row.class = expected_permission.ClassId" in validator
    assert "permission_row.major_id = expected_permission.MajorId" in validator
    assert "permission_row.minor_id = expected_permission.MinorId" in validator
    assert "permission_row.permission_name COLLATE DATABASE_DEFAULT = expected_permission.PermissionName" in validator
    assert "permission_row.state_desc COLLATE DATABASE_DEFAULT = expected_permission.StateDesc" in validator
    assert "The runtime role has a missing or altered permission row." in validator
    assert "The runtime role has an unapproved permission row or state." in validator


def test_permission_validator_normalizes_catalog_collation_in_both_exact_set_comparisons() -> None:
    """Break caught: either side of the exact-set comparison could fail on SQL Server catalog collation."""
    validator = (VALIDATORS / "005_validate_application_permissions.sql").read_text(encoding="utf-8")

    expected_comparison = "permission_row.permission_name COLLATE DATABASE_DEFAULT = expected_permission.PermissionName"
    assert validator.count(expected_comparison) == 2


def test_permission_validator_requires_one_runtime_member_and_dbo_role_owner() -> None:
    """Break caught: an extra role member or non-dbo role owner could inherit the runtime boundary."""
    validator = (VALIDATORS / "005_validate_application_permissions.sql").read_text(encoding="utf-8")

    assert "SELECT COUNT(*) FROM sys.database_role_members" in validator
    assert "role_principal_id = @RuntimeRoleId" in validator
    assert "<> 1" in validator
    assert "member_principal_id = @RuntimeUserId" in validator
    assert "role_row.owning_principal_id = DATABASE_PRINCIPAL_ID(N'dbo')" in validator
    assert "The runtime role must be owned by dbo." in validator
    assert "The runtime role must contain only ehf_app." in validator


def test_production_principal_inspection_uses_valid_outer_sql_and_collation_safe_names() -> None:
    source = HELPER.read_text(encoding="utf-8")

    assert "IF @UserState=N'INVALID' SELECT 'INVALID' AS State;" in source
    assert "IF @UserState=N''INVALID''" not in source
    assert "SET NOCOUNT ON;" in source[source.index("def _cross_database_rows") : source.index("def _inspect_production_state")]
    assert "CONVERT(varbinary(256),DB_NAME())" in source


def test_sql_driver_rows_are_normalized_to_plain_tuples() -> None:
    spec = importlib.util.spec_from_file_location("sql_principal_rows", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class DriverRow:
        def __iter__(self):
            return iter(("Finances2",))

    class Cursor:
        def execute(self, *_args):
            return self

        def fetchall(self):
            return [DriverRow()]

    class Connection:
        def cursor(self):
            return Cursor()

    assert module._rows(Connection(), "SELECT name") == [("Finances2",)]


@pytest.mark.parametrize(
    ("script", "arguments"),
    (
        (
            SETUP_SCRIPT,
            ("--database", "Finances2", "--login", "ehf_app", "--user", "ehf_app"),
        ),
        (
            TEST_SCRIPT,
            ("--database", "EHFApplications", "--login", "ehf_app", "--user", "ehf_app"),
        ),
    ),
)
def test_sql_login_scripts_reject_non_isolated_or_non_ehf_names(
    script: Path, arguments: tuple[str, ...]
) -> None:
    """Break caught: a provisioning command could be redirected to Finances 2 or production."""
    completed = subprocess.run(
        [str(GIT_BASH), str(script), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "unexpected" in output.casefold()


def test_sql_login_scripts_keep_passwords_out_of_command_arguments_and_logs() -> None:
    """Break caught: SQLCMD variable or command-line use could expose a generated credential."""
    for script in (SETUP_SCRIPT, TEST_SCRIPT):
        source = script.read_text(encoding="utf-8")
        assert "SQLCMDPASSWORD=" in source
        assert re.search(r"(?:^|\s)-P(?:\s|$)", source) is None
        assert re.search(r"(?:^|\s)-P(?:\s|$)", source) is None
        assert re.search(r"(?:^|\s)-v(?:\s|$)", source) is None
        assert "set +x" in source


def test_password_validation_has_no_command_line_test_hook() -> None:
    """Break caught: a password value could be injected into a process listing by a test hook."""
    source = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "--validate-password" not in source
    assert "password_is_safe" not in source


@pytest.mark.parametrize(
    ("password", "accepted"),
    (
        ("Aa1._~" + "a" * 42, True),
        ("A" * 48, False),
        ("A" * 47, False),
        ("A" * 47 + "'", False),
        ("A" * 47 + ";", False),
        ("A" * 47 + "\n", False),
    ),
)
def test_helper_password_validation_accepts_only_the_fixed_safe_alphabet(
    password: str, accepted: bool
) -> None:
    """Break caught: a password file could inject SQLCMD syntax without argv exposure."""
    spec = importlib.util.spec_from_file_location("sql_principal_password", HELPER)
    assert spec and spec.loader
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)

    if accepted:
        helper._require_safe_password(password)
    else:
        with pytest.raises(helper.PrincipalError):
            helper._require_safe_password(password)


def test_sql_scripts_use_hardened_sqlcmd_invocations_and_lf_line_endings() -> None:
    """Break caught: inherited SQLCMDINI or a colon endpoint could change live behavior."""
    for script in (SETUP_SCRIPT, TEST_SCRIPT):
        payload = script.read_bytes()
        source = payload.decode("utf-8")

        assert b"\r\n" not in payload
        assert "unset SQLCMDINI" in source
        assert "-X" in source
        assert "-I" in source
        assert "tcp:127.0.0.1,1433" in source
        assert "127.0.0.1:1433" not in source

    assert "*.sh text eol=lf" in (ROOT / ".gitattributes").read_text(
        encoding="utf-8"
    )


def test_permission_migration_records_later_identity_scope_requirement() -> None:
    """Break caught: procedure grants could be mistaken for authenticated app authorization."""
    migration = MIGRATION.read_text(encoding="utf-8")

    assert "application-layer authenticated identity" in migration.casefold()
    assert "ALTER ANY LOGIN" in migration


def test_isolated_verifier_uses_a_second_database_and_fails_when_cleanup_fails() -> None:
    """Break caught: a runtime login could read another database or leak a partial test principal."""
    source = TEST_SCRIPT.read_text(encoding="utf-8")

    assert "EHFApplications_Test_sqlperm_peer_" in source
    assert "create-test-database" in source
    assert "run_token=" in source
    assert "Cleanup failed; isolated EHF SQL verification is unsuccessful." in source
    assert "run_helper verify-peer-database-denial" in source
    assert "run_runtime_sql \"$peer_database\"" not in source
    assert "verify-test-cleanup" in source
    assert "verify-no-test-leftovers" in source
    assert "Cleanup stage: global zero verify." in source


def test_isolated_verifier_cleans_explicitly_before_pass_and_preserves_adverse_peer() -> None:
    """Break caught: PASS could be printed before a failing trap cleanup, or a peer could be deleted."""
    source = TEST_SCRIPT.read_text(encoding="utf-8")

    pass_index = source.index("PASS isolated EHF SQL permission boundary")
    cleanup_index = source.index("cleanup_owned_targets")
    assert cleanup_index < pass_index
    assert "trap - EXIT" in source
    assert "adverse_database" in source
    assert "verify-test-targets-preserved" in source
    assert source.index("verify-no-test-leftovers") < pass_index


@pytest.mark.parametrize(
    ("initial_state", "expected_commands"),
    (
        (
            "ready",
            ("inspect", "authenticate", "inspect-effective", "inspect-effective"),
        ),
        (
            "unmapped",
            ("inspect", "inspect-effective", "map", "authenticate", "inspect-effective"),
        ),
        (
            "absent",
            ("inspect", "create", "inspect-effective", "map", "authenticate", "inspect-effective"),
        ),
    ),
)
def test_setup_lifecycle_executes_mapping_before_expected_database_authentication(
    tmp_path: Path, initial_state: str, expected_commands: tuple[str, ...]
) -> None:
    """Break caught: UNMAPPED could authenticate against EHFApplications before ALTER USER."""
    source = SETUP_SCRIPT.read_text(encoding="utf-8")
    lifecycle = source[
        source.index("verified_state() {") : source.index('app_password="$(<"$password_file")"')
    ]
    command_log = tmp_path / "commands.log"
    state_file = tmp_path / "state"
    password_file = tmp_path / "sql-app-password"
    state_file.write_text(initial_state, encoding="utf-8")
    password_file.write_text("Aa1._~" + "a" * 42, encoding="utf-8")
    harness = tmp_path / "setup-lifecycle.sh"
    harness.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
export EHF_SQL_TEST_MODE=1
database=EHFApplications
login=ehf_app
user=ehf_app
server=tcp:127.0.0.1,1433
admin_password_file=/protected/admin
credential_directory="$(dirname "$4")"
password_file="$4"
command_log="$2"
state_file="$3"
fail() { printf '%s\n' "$1" >&2; exit 2; }
getent() { return 0; }
groupadd() { return 0; }
install() { return 0; }
stat() { printf '%s\n' 'root:ehf:640'; }
chown() { return 0; }
chmod() { return 0; }
openssl() { printf '%s\n' '0123456789abcdef0123456789abcdef0123456789'; }
run_helper() {
  local helper_command="$1" label current_state
  shift
  current_state="$(<"$state_file")"
  label="$helper_command"
  if [[ "$helper_command" == inspect-production ]]; then
    label=inspect
    [[ " $* " != *" --credential-file "* ]] || label=inspect-effective
  elif [[ "$helper_command" == create-production-login ]]; then
    label=create
    printf '%s' unmapped >"$state_file"
  elif [[ "$helper_command" == map-production-user ]]; then
    label=map
    printf '%s' ready >"$state_file"
  elif [[ "$helper_command" == authenticate-login ]]; then
    label=authenticate
    [[ "$current_state" == ready ]] || return 1
  fi
  if [[ "$label" == inspect-effective || "$label" == map || "$label" == authenticate ]]; then
    [[ " $* " == *" --credential-file $password_file "* ]] || return 1
  fi
  printf '%s\n' "$label" >>"$command_log"
  [[ "$helper_command" != inspect-production ]] || printf '%s\n' "$(<"$state_file")"
}
"""
        + lifecycle,
        encoding="utf-8",
        newline="\n",
    )

    completed = subprocess.run(
        [str(GIT_BASH), str(harness), initial_state, str(command_log), str(state_file), str(password_file)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert tuple(command_log.read_text(encoding="utf-8").splitlines()) == expected_commands
    assert password_file.read_text(encoding="utf-8") == "Aa1._~" + "a" * 42
    if initial_state in {"unmapped", "absent"}:
        commands = command_log.read_text(encoding="utf-8").splitlines()
        assert commands.index("inspect-effective") < commands.index("map")
        assert commands.index("map") < commands.index("authenticate")


def test_isolated_sqlcmd_wrapper_forwards_static_migration_and_validator_files() -> None:
    """Break caught: -i migration files could be accepted by the wrapper but never executed."""
    source = TEST_SCRIPT.read_text(encoding="utf-8")

    assert 'local target_database="$1"; shift; SQLCMDPASSWORD=' in source
    assert "EXEC(N'ALTER SERVER ROLE" not in source
    assert "@loginSql" in source and "@roleSql" in source
    assert "IF ERROR_NUMBER()<>15247 THROW" in source


def test_isolated_verifier_exercises_every_protected_table_and_metadata_deny() -> None:
    """Break caught: direct DML or metadata checks could cover only Application and miss another protected table."""
    source = TEST_SCRIPT.read_text(encoding="utf-8")

    for table_name in PROTECTED_TABLES:
        assert f"N'{table_name}'" in source
    for permission_name in (
        "VIEW ANY DATABASE",
        "VIEW ANY DEFINITION",
        "VIEW SERVER STATE",
        "CREATE PROCEDURE",
        "CREATE VIEW",
        "ALTER ANY SCHEMA",
        "ALTER ANY USER",
        "ALTER ANY ROLE",
        "VIEW DEFINITION",
    ):
        assert permission_name in source
    assert "Protected SELECT succeeded." not in source
    assert "DML permission denial was not returned" in source
