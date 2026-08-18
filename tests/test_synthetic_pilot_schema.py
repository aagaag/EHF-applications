from __future__ import annotations

from pathlib import Path

from app.migrations import discover_migrations


ROOT = Path(__file__).resolve().parents[1]


def test_release_sixteen_adds_entra_scoping_and_pending_approval_boundaries() -> None:
    """Break caught: the Entra portal could trust record IDs or auto-approve edits."""
    migrations = discover_migrations(ROOT / "database" / "migrations")
    source = next(
        migration for migration in migrations if migration.version == 16
    ).path.read_text(encoding="utf-8")

    for fragment in (
        "CREATE TABLE dbo.ApplicantAccessRequest",
        "CREATE TABLE dbo.ApplicantEntraIdentity",
        "CREATE PROCEDURE dbo.CreateEntraApplicantSession",
        "CREATE PROCEDURE dbo.RequestApplicantAccess",
        "CREATE PROCEDURE dbo.ListPendingApplicantAccessRequests",
        "CREATE PROCEDURE dbo.ReviewApplicantAccessRequest",
        "CREATE PROCEDURE dbo.GetApplicantProjection",
        "CREATE PROCEDURE dbo.GetApplicantSectionDraft",
        "CREATE TABLE dbo.ApplicantFinalReviewDecision",
        "CREATE PROCEDURE dbo.ListPendingApplicantSubmissions",
        "CREATE PROCEDURE dbo.GetApplicantSubmissionReview",
        "CREATE PROCEDURE dbo.PromoteApprovedApplicantDrafts",
        "CREATE PROCEDURE dbo.ApproveApplicantSubmission",
        "CREATE PROCEDURE dbo.RegisterApplicantDocumentSubmission",
        "@SlotAuthorized bit = 0",
        "OR @SlotAuthorized <> 1",
        "CREATE PROCEDURE dbo.GetApplicantDocumentDownload",
        "CREATE PROCEDURE dbo.ListPendingApplicantDocumentSubmissions",
        "CREATE PROCEDURE dbo.ReviewApplicantDocumentSubmission",
        "@SessionTokenSha256 binary(32)",
        "SubmissionStatus = ''PENDING''",
        "ApplicationStatus = ''IN_REVIEW''",
        "ApplicationStatus = ''CONFIRMED''",
        "EHF-Administrators",
        "EHF-Trustees",
    ):
        assert fragment in source
    assert "GRANT SELECT" not in source
    assert "GRANT INSERT" not in source
    assert "GRANT UPDATE" not in source
    assert "GRANT DELETE" not in source


def test_release_sixteen_revalidates_identity_and_promotes_canonical_data() -> None:
    source = (ROOT / "database" / "migrations" / "016_entra_applicant_workflow.sql").read_text(encoding="utf-8")

    assert "identity_row.Enabled = 1" in source
    assert "identity_row.DisabledAtUtc IS NULL" in source
    assert "INSERT dbo.ApplicationSectionVersion" in source
    assert "MERGE dbo.ContributionStatement" in source
    assert "ALTER PROCEDURE dbo.GetInternalApplicationMetrics" in source
    assert "CREATE PROCEDURE dbo.GetApplicantFinalDocumentIssues" in source
    assert "ApplicantAccessRequestId IS NOT NULL" in source
    assert "LEGACY_APPLICANT" in source


def test_release_sixteen_provisions_atomically_and_preserves_verified_citations() -> None:
    source = (ROOT / "database" / "migrations" / "016_entra_applicant_workflow.sql").read_text(encoding="utf-8")
    provision = source.split("CREATE PROCEDURE dbo.ProvisionApplicantAccessRequest", 1)[1].split(
        "CREATE PROCEDURE dbo.CreateEntraApplicantSession", 1
    )[0]
    promotion = source.split("CREATE PROCEDURE dbo.PromoteApprovedApplicantDrafts", 1)[1].split(
        "CREATE PROCEDURE dbo.ApproveApplicantSubmission", 1
    )[0]

    assert "@ApplicationId uniqueidentifier" in provision
    assert "BEGIN TRANSACTION" in provision
    assert "INSERT dbo.ApplicantEntraIdentity" in provision
    assert "IdentityKind, Enabled" in provision
    assert "GoogleScholarCitationCount = TRY_CONVERT" not in promotion
    assert "ClinicalWorkPercent BETWEEN 0.00 AND 100.00" in source


def test_release_sixteen_projects_visible_document_metadata_dynamically() -> None:
    source = (ROOT / "database" / "migrations" / "016_entra_applicant_workflow.sql").read_text(encoding="utf-8")
    projection = source.split("CREATE PROCEDURE dbo.GetApplicantProjection", 1)[1].split(
        "CREATE PROCEDURE dbo.GetApplicantSectionDraft", 1
    )[0]

    assert "vw_ApplicantVisibleDocumentVersion" in projection
    assert "ApplicantDocumentReviewDecision" in projection
    assert "JSON_MODIFY" in projection
