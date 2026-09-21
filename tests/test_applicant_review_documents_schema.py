from __future__ import annotations

from pathlib import Path

from app.migrations import discover_migrations


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "025_applicant_review_documents.sql"
VALIDATOR = ROOT / "database" / "tests" / "025_validate_applicant_review_documents.sql"
PERMISSION_VALIDATOR = (
    ROOT / "database" / "tests" / "005_validate_application_permissions.sql"
)
CONTRACT_VALIDATOR = ROOT / "database" / "tests" / "001_validate_database_contract.sql"
TEST_SCRIPT = ROOT / "scripts" / "test-database.ps1"
ISOLATED_VERIFIER = ROOT / "infra" / "test-sql-login.sh"


def test_release_twenty_five_adds_review_card_metrics_and_administrator_only_proposal_pdfs() -> None:
    migrations = discover_migrations(ROOT / "database" / "migrations")
    assert migrations[24].path.name == MIGRATION.name
    source = MIGRATION.read_text(encoding="utf-8")

    for fragment in (
        "ALTER PROCEDURE dbo.ListApplicantPreviews",
        "AcademicAgeYears",
        "$.academic_age_observation",
        "academic_degree.PhdConferralDate",
        "HIndex",
        "CitationCount",
        "CitationSource",
        "ResearchArea",
        "DocumentCount",
        "ApplicantCitationProfileObservation",
        "CREATE PROCEDURE dbo.ListApplicantPreviewDocuments",
        "CREATE PROCEDURE dbo.GetApplicantPreviewDocument",
        "APPLICANT_PREVIEW_DOCUMENTS_OPENED",
        "APPLICANT_PREVIEW_DOCUMENT_OPENED",
        "GRANT EXECUTE ON dbo.ListApplicantPreviews TO EHFApplicationRuntime",
        "GRANT EXECUTE ON dbo.ListApplicantPreviewDocuments TO EHFApplicationRuntime",
        "GRANT EXECUTE ON dbo.GetApplicantPreviewDocument TO EHFApplicationRuntime",
    ):
        assert fragment in source, fragment
    assert source.count("@ActorGroup <> N''EHF-Administrators''") == 3
    assert source.count("THROW 52920") == 2
    assert "ApplicantSyntheticWorkspace" in source


def test_release_twenty_five_keeps_the_card_metrics_behind_administrator_authorization() -> None:
    """Break caught: a trustee or synthetic workspace could reach the review card metrics."""
    source = MIGRATION.read_text(encoding="utf-8")
    card_procedure = source[
        source.index("ALTER PROCEDURE dbo.ListApplicantPreviews") :
        source.index("CREATE PROCEDURE dbo.ListApplicantPreviewDocuments")
    ]

    assert "@ActorGroup <> N''EHF-Administrators''" in card_procedure
    assert "workspace_row.ApplicationId = application_row.ApplicationId" in card_procedure
    assert "application_row.ApplicationId = baseline.ApplicationId" in card_procedure
    for forbidden in ("INSERT dbo.AuditEvent", "DELETE ", "UPDATE dbo."):
        assert forbidden not in card_procedure, forbidden


def test_release_twenty_five_validator_proves_the_card_and_document_boundary() -> None:
    source = VALIDATOR.read_text(encoding="utf-8")

    for fragment in (
        "EXEC dbo.ListApplicantPreviews",
        "EXEC dbo.ListApplicantPreviewDocuments",
        "EXEC dbo.GetApplicantPreviewDocument",
        "AcademicAgeYears = 3.50",
        "DocumentCount = 1",
        "@ActorGroup=N'EHF-Trustees'",
        "APPLICANT_PREVIEW_DOCUMENTS_OPENED",
        "APPLICANT_PREVIEW_DOCUMENT_OPENED",
        "ROLLBACK TRANSACTION",
        "PASS 025 applicant review documents",
    ):
        assert fragment in source, fragment
    assert source.index("@ActorGroup=N'EHF-Trustees'") < source.index("BEGIN TRANSACTION")


def test_contract_permission_and_harness_lists_include_release_twenty_five() -> None:
    permission_validator = PERMISSION_VALIDATOR.read_text(encoding="utf-8")
    contract_validator = CONTRACT_VALIDATOR.read_text(encoding="utf-8")
    script = TEST_SCRIPT.read_text(encoding="utf-8")
    verifier = ISOLATED_VERIFIER.read_text(encoding="utf-8")

    assert "(N'ListApplicantPreviewDocuments')" in permission_validator
    assert "(N'GetApplicantPreviewDocument')" in permission_validator
    assert "COUNT_BIG(*) FROM dbo.SchemaMigration) <> 25" in contract_validator
    assert "WHERE MigrationCount = 25 AND CurrentVersion = 25" in contract_validator
    assert "025_applicant_review_documents.sql" in script
    assert "025_validate_applicant_review_documents.sql" in script
    assert "025_applicant_review_documents.sql" in verifier
    assert "025_validate_applicant_review_documents.sql" in verifier
