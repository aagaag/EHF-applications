from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "044_call_navigation_preferences.sql"
VALIDATOR = ROOT / "database" / "tests" / "044_validate_call_navigation_preferences.sql"


def test_call_navigation_preference_migration_is_durable_and_procedure_only() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "DefaultCallMode varchar(40)" in sql
    assert "LastFellowshipCallId uniqueidentifier" in sql
    assert "CK_UserPreference_DefaultCallMode" in sql
    assert "FK_UserPreference_LastFellowshipCall" in sql
    assert "CREATE PROCEDURE dbo.GetCallNavigationPreference" in sql
    assert "CREATE PROCEDURE dbo.SetCallNavigationPreference" in sql
    assert "WITH EXECUTE AS ''EHFPreferenceProcedureExecutor''" in sql
    assert "GRANT EXECUTE ON dbo.GetCallNavigationPreference TO EHFApplicationRuntime" in sql
    assert "GRANT EXECUTE ON dbo.SetCallNavigationPreference TO EHFApplicationRuntime" in sql


def test_call_navigation_validator_checks_the_runtime_contract() -> None:
    sql = VALIDATOR.read_text(encoding="utf-8")

    assert "dbo.GetCallNavigationPreference" in sql
    assert "dbo.SetCallNavigationPreference" in sql
    assert "resume-last-opened" in sql
    assert "latest-application-deadline" in sql
    assert "PASS 044 call navigation preferences" in sql
