from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_trustee_shortlist_migration_is_identity_bound_audited_and_least_privilege() -> None:
    migration = (ROOT / "database/migrations/037_trustee_shortlist.sql").read_text(encoding="utf-8")
    validator = (ROOT / "database/tests/037_validate_trustee_shortlist.sql").read_text(encoding="utf-8")
    combined = migration + validator

    for value in (
        "7747ffa7-5193-4cc8-9221-08a1dd24b026",
        "09d14671-38e1-4763-8d67-512c9787d379",
        "d5c5fb6a-f9c3-456c-97b1-20b450647f8c",
        "CREATE TABLE dbo.ShortlistTrustee",
        "CREATE TABLE dbo.TrusteeShortlistSelection",
        "CREATE PROCEDURE dbo.GetInternalShortlistSelections",
        "CREATE PROCEDURE dbo.SetInternalShortlistSelection",
        "@ActorEntraObjectId uniqueidentifier",
        "BEGIN TRANSACTION",
        "SHORTLIST_SELECTION_SET",
        "INSERT dbo.AuditEvent",
        "GRANT EXECUTE ON dbo.GetInternalShortlistSelections TO EHFApplicationRuntime",
        "GRANT EXECUTE ON dbo.SetInternalShortlistSelection TO EHFApplicationRuntime",
        "DENY SELECT, INSERT, UPDATE, DELETE ON dbo.TrusteeShortlistSelection TO EHFApplicationRuntime",
    ):
        assert value in combined

    assert "ActorEntraObjectId = @ActorEntraObjectId" in migration
    assert "TrusteeCode = @TrusteeCode" in migration
    assert "@TrusteeCode NOT IN" in migration
    assert "trusteecode" in migration.casefold()
    assert "selected" in migration.casefold()


def test_runtime_permission_validator_knows_the_shortlist_objects() -> None:
    validator = (ROOT / "database/tests/005_validate_application_permissions.sql").read_text(encoding="utf-8")

    assert "GetInternalShortlistSelections" in validator
    assert "SetInternalShortlistSelection" in validator
    assert "ShortlistTrustee" in validator
    assert "TrusteeShortlistSelection" in validator
