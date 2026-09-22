"""Publication-review audit and resolver matching contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from app.applicant.admin_preview import _publication_record
from app.importer.publication_matching import matches_verified_candidate


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "025_publication_review_workflow.sql"
VALIDATOR = ROOT / "database" / "tests" / "025_validate_publication_review_workflow.sql"
PROMOTION_MIGRATION = ROOT / "database" / "migrations" / "039_publication_promotion_dispositions.sql"
PROMOTION_VALIDATOR = ROOT / "database" / "tests" / "039_validate_publication_promotion_dispositions.sql"
DISPOSITION_MIGRATION = ROOT / "database" / "migrations" / "047_decouple_publication_disposition.sql"
DISPOSITION_VALIDATOR = ROOT / "database" / "tests" / "047_validate_decoupled_publication_disposition.sql"
REVIEW_PERMISSION_MIGRATION = ROOT / "database" / "migrations" / "048_restrict_publication_review_permission.sql"
REVIEW_PERMISSION_VALIDATOR = ROOT / "database" / "tests" / "048_validate_publication_review_permission.sql"


def test_resolver_accepts_vs_abbreviation_and_online_to_issue_year_transition() -> None:
    """Break caught: verified records were rejected only for ``versus``/``vs.`` and year format."""
    assert matches_verified_candidate(
        "Decoupling SAXS versus FRET measurements",
        "Decoupling SAXS vs. FRET measurements",
        reported_year=2017,
        candidate_issue_year=2017,
    )
    assert matches_verified_candidate(
        "Mapping Charge Interactions in Intrinsically Disordered Proteins",
        "Mapping Charge Interactions in Intrinsically Disordered Proteins",
        reported_year=2026,
        candidate_online_year=2025,
        candidate_issue_year=2026,
    )


def test_unresolved_preview_uses_review_status_and_evidence_not_missing_placeholders() -> None:
    record = SimpleNamespace(
        application_publication_id=UUID("25000000-0000-4000-8000-000000000001"),
        authors_text=None,
        title=None,
        journal_text=None,
        volume_text=None,
        pages_text=None,
        publication_year=None,
        citation_count=None,
        citation_status="NOT_APPLICABLE",
        openalex_citation_count=None,
        openalex_citation_status="NOT_APPLICABLE",
        semantic_scholar_citation_count=None,
        semantic_scholar_citation_status="NOT_APPLICABLE",
        publication_url=None,
        resolution_status="UNRESOLVED",
        review_disposition="UNDER_PREPARATION",
        review_reason="Applicant marked this item as under preparation.",
        review_evidence="Dossier page 6, publication list.",
        source_citation="Work under preparation",
        source_page=6,
    )

    rendered = _publication_record(record)

    assert "Resolution and review" in rendered
    assert "UNRESOLVED · UNDER PREPARATION" in rendered
    assert "Applicant marked this item as under preparation." in rendered
    assert "Work under preparation" in rendered
    assert "Missing" not in rendered
    assert 'role="link"' not in rendered


def test_accepted_preprint_disposition_is_presented_as_a_human_readable_category() -> None:
    record = SimpleNamespace(
        application_publication_id=UUID("25000000-0000-4000-8000-000000000002"),
        authors_text=None,
        title=None,
        journal_text=None,
        volume_text=None,
        pages_text=None,
        publication_year=None,
        citation_count=None,
        citation_status="NOT_APPLICABLE",
        openalex_citation_count=None,
        openalex_citation_status="NOT_APPLICABLE",
        semantic_scholar_citation_count=None,
        semantic_scholar_citation_status="NOT_APPLICABLE",
        publication_url=None,
        resolution_status="UNRESOLVED",
        review_disposition="ACCEPTED_PREPRINT",
        review_reason="Accepted manuscript; not yet a published paper.",
        review_evidence="Dossier page 4.",
        source_citation="Accepted manuscript",
        source_page=4,
    )

    rendered = _publication_record(record)

    assert "UNRESOLVED · ACCEPTED / PREPRINT" in rendered
    assert "Missing" not in rendered


def test_publication_review_migration_is_append_only_and_controls_promotions() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    validator = VALIDATOR.read_text(encoding="utf-8")

    assert "CREATE TABLE dbo.ApplicationPublicationReview" in source
    assert "PUBLISHED" in source
    assert "ACCEPTED_PREPRINT" in source
    assert "UNDER_PREPARATION" in source
    assert "NON_PUBLICATION" in source
    assert "CREATE TRIGGER dbo.TR_ApplicationPublicationReview_AppendOnly" in source
    assert "CREATE PROCEDURE dbo.RecordApplicationPublicationReview" in source
    assert "CREATE PROCEDURE dbo.PromoteApplicationPublication" in source
    assert "UNRESOLVED" in source and "RESOLVED" in source
    assert "PW0105" in source and "PW0106" in source
    assert "PW0108" in source and "PW0121" in source
    assert "ValidatedPublishedPaperCount" in source
    assert "@ReviewDisposition AS outcome" in source
    assert "@ResolutionStatus AS status" in source
    assert "@ApplicationPublicationId AS publicationId" not in source
    assert "PASS 025 publication review workflow" in validator


def test_existing_synthetic_metrics_validator_accepts_validated_count_column() -> None:
    """Break caught: an appended metrics column broke the full SQL validator sequence."""
    synthetic_validator = (
        ROOT / "database" / "tests" / "019_validate_synthetic_applicant_workspace.sql"
    ).read_text(encoding="utf-8")
    metrics_validator = (
        ROOT / "database" / "tests" / "020_validate_synthetic_metrics_academic_age.sql"
    ).read_text(encoding="utf-8")

    assert "ValidatedPublishedPaperCount int" in synthetic_validator
    assert "REPLACE(@MetricsDefinition, N' ', N'')" in metrics_validator


def test_promotion_records_the_requested_review_disposition_atomically() -> None:
    migration = PROMOTION_MIGRATION.read_text(encoding="utf-8")
    validator = PROMOTION_VALIDATOR.read_text(encoding="utf-8")

    assert "ALTER PROCEDURE dbo.PromoteApplicationPublication" in migration
    assert "@ReviewDisposition varchar(32) = ''PUBLISHED''" in migration
    assert "@ReviewDisposition=@ReviewDisposition" in migration
    assert "@ReviewDisposition=''PUBLISHED''" not in migration
    assert "@ReviewDisposition='ACCEPTED_PREPRINT'" in validator
    assert "Promotion must record exactly one review decision." in validator
    assert "Promotion did not atomically record the requested disposition." in validator
    assert "PASS 039 publication promotion dispositions" in validator


def test_published_disposition_does_not_require_a_resolved_doi() -> None:
    """Break caught: DOI-less papers were rejected and omitted from published totals."""
    assert DISPOSITION_MIGRATION.is_file()
    assert DISPOSITION_VALIDATOR.is_file()

    migration = DISPOSITION_MIGRATION.read_text(encoding="utf-8")
    validator = DISPOSITION_VALIDATOR.read_text(encoding="utf-8")

    assert "ALTER PROCEDURE dbo.RecordApplicationPublicationReview" in migration
    assert "ALTER PROCEDURE dbo.GetInternalApplicationMetrics" in migration
    assert "ALTER PROCEDURE dbo.GetInternalApplicantMetricDetail" in migration
    assert "ALTER PROCEDURE dbo.RecordPendingPublicationReview" in migration
    assert "DOI resolution is independent of publication disposition" in migration
    assert "@ReviewDisposition='PUBLISHED'" in validator
    assert "ResolutionStatus='UNRESOLVED'" in validator
    assert "DOI-less published paper was omitted from the aggregate metrics" in validator
    assert "DOI-less published paper was omitted from applicant detail" in validator
    assert "PASS 047 decoupled publication disposition" in validator


def test_low_level_publication_review_writer_is_not_runtime_callable() -> None:
    """Break caught: the runtime role briefly received a direct low-level review grant."""
    assert REVIEW_PERMISSION_MIGRATION.is_file()
    assert REVIEW_PERMISSION_VALIDATOR.is_file()

    migration = REVIEW_PERMISSION_MIGRATION.read_text(encoding="utf-8")
    validator = REVIEW_PERMISSION_VALIDATOR.read_text(encoding="utf-8")

    assert "REVOKE EXECUTE ON dbo.RecordApplicationPublicationReview" in migration
    assert "DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')" in validator
    assert "RecordPendingPublicationReview" in validator
    assert "PASS 048 publication review permission" in validator
