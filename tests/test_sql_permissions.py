from __future__ import annotations

from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "database" / "migrations"
VALIDATORS = ROOT / "database" / "tests"
MIGRATION = MIGRATIONS / "005_application_permissions.sql"
SETUP_SCRIPT = ROOT / "infra" / "setup-sql-login.sh"
TEST_SCRIPT = ROOT / "infra" / "test-sql-login.sh"
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")

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
)


def test_permission_boundary_release_artifacts_exist() -> None:
    """Break caught: a permission release could omit a required enforcement artifact."""
    assert (MIGRATIONS / "005_application_permissions.sql").is_file()
    assert (VALIDATORS / "005_validate_application_permissions.sql").is_file()
    assert (ROOT / "infra" / "setup-sql-login.sh").is_file()
    assert (ROOT / "infra" / "test-sql-login.sh").is_file()
    assert (ROOT / "docs" / "permissions.md").is_file()


def test_permission_validator_covers_runtime_allow_and_deny_contract() -> None:
    """Break caught: a migration could publish a runtime role without validating its boundary."""
    validator = (VALIDATORS / "005_validate_application_permissions.sql").read_text(
        encoding="utf-8"
    )

    for fragment in (
        "dbo.RuntimeHealth",
        "dbo.SetUserPreference",
        "dbo.SetApplicationStatus",
        "EHFApplicationRuntime",
        "SchemaMigration",
        "AuditEvent",
        "HAS_PERMS_BY_NAME",
        "VIEW DEFINITION",
        "SCHEMA",
    ):
        assert fragment in validator
    assert "THROW 51504" not in validator


def test_permission_migration_denies_direct_table_access_and_publishes_only_three_procedures() -> None:
    """Break caught: the runtime role could gain a table grant or unreviewed module access."""
    migration = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE ROLE EHFApplicationRuntime" in migration
    assert "CREATE USER ehf_app WITHOUT LOGIN" in migration
    for table_name in PROTECTED_TABLES:
        assert (
            f"DENY SELECT, INSERT, UPDATE, DELETE ON dbo.{table_name}"
            " TO EHFApplicationRuntime;"
        ) in migration
    for procedure_name in (
        "RuntimeHealth",
        "SetUserPreference",
        "SetApplicationStatus",
    ):
        assert (
            f"GRANT EXECUTE ON dbo.{procedure_name} TO EHFApplicationRuntime;"
        ) in migration
    assert "GRANT SELECT ON SCHEMA::dbo" not in migration
    assert "GRANT EXECUTE ON SCHEMA::dbo" not in migration


def test_permission_validator_impersonates_the_runtime_user_for_positive_and_negative_checks() -> None:
    """Break caught: a privileged validator could mask the runtime account's real permissions."""
    validator = (VALIDATORS / "005_validate_application_permissions.sql").read_text(
        encoding="utf-8"
    )

    for fragment in (
        "EXECUTE AS USER = N'ehf_app'",
        "EXEC dbo.RuntimeHealth",
        "EXEC dbo.SetUserPreference",
        "INSERT",
        "UPDATE",
        "DELETE",
        "master.sys.databases",
        "CREATE TABLE dbo.PermissionValidatorDenied",
        "sys.database_principals",
        "ALTER SERVER ROLE",
        "CREATE LOGIN",
        "HAS_PERMS_BY_NAME(NULL, NULL, N'ALTER ANY LOGIN')",
        "HAS_PERMS_BY_NAME(NULL, NULL, N'ALTER ANY SERVER ROLE')",
        "ehf_permission_validator_denied",
        "EXECUTE AS USER = N'EHFPreferenceProcedureExecutor'",
        "REVERT",
    ):
        assert fragment in validator


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
    sentinel = "credential-never-print"
    completed = subprocess.run(
        [str(GIT_BASH), str(script), *arguments],
        cwd=ROOT,
        env={"EHF_SQL_ADMIN_PASSWORD": sentinel},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "unexpected" in output.casefold()
    assert sentinel not in output


def test_sql_login_scripts_keep_passwords_out_of_command_arguments_and_logs() -> None:
    """Break caught: SQLCMD variable or command-line use could expose a generated credential."""
    for script in (SETUP_SCRIPT, TEST_SCRIPT):
        source = script.read_text(encoding="utf-8")
        assert "SQLCMDPASSWORD=" in source
        assert "SQLCMDPASSWORD" not in source.replace("SQLCMDPASSWORD=", "")
        assert re.search(r"(?:^|\s)-P(?:\s|$)", source) is None
        assert re.search(r"(?:^|\s)-v(?:\s|$)", source) is None
        assert "set +x" in source
