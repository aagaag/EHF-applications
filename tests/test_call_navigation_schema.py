from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "044_call_navigation_preferences.sql"
VALIDATOR = ROOT / "database" / "tests" / "044_validate_call_navigation_preferences.sql"
FIX_MIGRATION = ROOT / "database" / "migrations" / "045_fix_call_navigation_preference_insert.sql"
FIX_VALIDATOR = ROOT / "database" / "tests" / "045_validate_call_navigation_preference_insert.sql"


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


def test_follow_up_migration_preserves_history_and_supplies_appearance_defaults() -> None:
    migration = FIX_MIGRATION.read_text(encoding="utf-8")
    validator = FIX_VALIDATOR.read_text(encoding="utf-8")

    assert "ALTER PROCEDURE dbo.SetCallNavigationPreference" in migration
    assert "Skin, InvertColors, CompactDensity, ReduceMotion" in migration
    assert "''default'', 0, 0, 0" in migration
    assert "EXEC dbo.SetCallNavigationPreference" in validator
    assert "Skin = 'default'" in validator
    assert "PASS 045 call navigation preference insert" in validator
