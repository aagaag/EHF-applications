from __future__ import annotations

from pathlib import Path

from app.migrations import discover_migrations


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "018_applicant_admin_preview.sql"
VALIDATOR = ROOT / "database" / "tests" / "018_validate_applicant_admin_preview.sql"
PERMISSION_VALIDATOR = ROOT / "database" / "tests" / "005_validate_application_permissions.sql"


def test_release_eighteen_adds_an_admin_only_audited_applicant_preview_boundary() -> None:
    migrations = discover_migrations(ROOT / "database" / "migrations")
    assert migrations[17].path.name == MIGRATION.name
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE PROCEDURE dbo.ListApplicantPreviews" in source
    assert "CREATE PROCEDURE dbo.GetApplicantPreview" in source
    assert "@ActorGroup <> N''EHF-Administrators''" in source
    assert "@ActorIdentity" in source
    assert "@EmitDrafts bit = 1" in source
    assert "APPLICANT_PREVIEW_OPENED" in source
    assert "INSERT dbo.AuditEvent" in source
    assert "GRANT EXECUTE ON dbo.ListApplicantPreviews TO EHFApplicationRuntime" in source
    assert "GRANT EXECUTE ON dbo.GetApplicantPreview TO EHFApplicationRuntime" in source
    assert "ApplicantDocument" not in source


def test_release_eighteen_validator_checks_authorization_audit_and_exact_record_scope() -> None:
    source = VALIDATOR.read_text(encoding="utf-8")

    for fragment in (
        "EXEC dbo.ListApplicantPreviews",
        "EXEC dbo.GetApplicantPreview",
        "EHF-Trustees",
        "APPLICANT_PREVIEW_OPENED",
        "@PreviewHeader",
        "@EmitDrafts=0",
        "Synthetic Other Preview",
        "ROLLBACK TRANSACTION",
        "PASS 018 applicant administrator preview",
    ):
        assert fragment in source
    assert source.index("@ActorGroup=N'EHF-Trustees'") < source.index("BEGIN TRANSACTION")


def test_runtime_permission_validator_approves_only_the_new_preview_procedures() -> None:
    source = PERMISSION_VALIDATOR.read_text(encoding="utf-8")

    assert "(N'ListApplicantPreviews')" in source
    assert "(N'GetApplicantPreview')" in source
