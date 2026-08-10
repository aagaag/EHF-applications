from __future__ import annotations

from pathlib import Path
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
    assert (ROOT / "infra" / "sql-principal.py").is_file()
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
        "sys.database_permissions",
        "A required runtime procedure grant is missing.",
    ):
        assert fragment in validator
    assert "SET XACT_ABORT OFF;" in validator


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
    assert "DENY ALTER, CONTROL ON SCHEMA::dbo" not in migration
    assert "REVOKE CONNECT FROM ehf_app;" in migration


def test_permission_validator_leaves_real_login_checks_to_the_isolated_verifier() -> None:
    """Break caught: a database-scoped impersonation check could claim server-login coverage."""
    validator = (VALIDATORS / "005_validate_application_permissions.sql").read_text(
        encoding="utf-8"
    )

    for fragment in (
        "sys.database_permissions",
        "EHFApplicationRuntime",
        "A required runtime procedure grant is missing.",
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
    assert "run_runtime_sql \"$peer_database\"" in source
    assert "verify-test-cleanup" in source


def test_isolated_verifier_cleans_explicitly_before_pass_and_preserves_adverse_peer() -> None:
    """Break caught: PASS could be printed before a failing trap cleanup, or a peer could be deleted."""
    source = TEST_SCRIPT.read_text(encoding="utf-8")

    pass_index = source.index("PASS isolated EHF SQL permission boundary")
    cleanup_index = source.index("cleanup_owned_targets")
    assert cleanup_index < pass_index
    assert "trap - EXIT" in source
    assert "adverse_database" in source
    assert "verify-test-targets-preserved" in source


def test_setup_converges_an_authenticated_unmapped_login_without_creating_a_password() -> None:
    """Break caught: a safe interrupted setup could not converge on its next root-run."""
    source = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert 'ready|unmapped)' in source
    assert '[[ "$inspect_state" == "ready" ]] || fail' not in source
    assert 'map-production-user' in source
    assert "/opt/ehf/current/venv/bin/python" in source


def test_isolated_sqlcmd_wrapper_forwards_static_migration_and_validator_files() -> None:
    """Break caught: -i migration files could be accepted by the wrapper but never executed."""
    source = TEST_SCRIPT.read_text(encoding="utf-8")

    assert 'local target_database="$1"; shift; SQLCMDPASSWORD=' in source
    assert "EXEC(N'ALTER SERVER ROLE" not in source
    assert "@loginSql" in source and "@roleSql" in source
    assert "IF ERROR_NUMBER()<>15247 THROW" in source
