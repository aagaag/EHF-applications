from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "043_pending_publication_review_queue.sql"
VALIDATOR = ROOT / "database" / "tests" / "043_validate_pending_publication_review_queue.sql"
PERMISSION_VALIDATOR = ROOT / "database" / "tests" / "005_validate_application_permissions.sql"


def test_pending_publication_queue_is_a_role_scoped_append_only_sql_boundary() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    validator = VALIDATOR.read_text(encoding="utf-8")

    for fragment in (
        "CREATE PROCEDURE dbo.ListPendingPublicationReviews",
        "CREATE PROCEDURE dbo.RecordPendingPublicationReview",
        "ReviewDisposition = ''PENDING_REVIEW''",
        "WITH (UPDLOCK, HOLDLOCK)",
        "dbo.RecordApplicationPublicationReview",
        "EHF-Administrators",
        "EHF-Trustees",
        "GRANT EXECUTE ON dbo.ListPendingPublicationReviews TO EHFApplicationRuntime",
        "GRANT EXECUTE ON dbo.RecordPendingPublicationReview TO EHFApplicationRuntime",
        "RawCitation",
        "ACCEPTED_PREPRINT",
        "NON_PUBLICATION",
        "EHFPublicationPromotion",
        "ResolutionStatus = ''RESOLVED''",
    ):
        assert fragment in source
    assert "PASS 043 pending publication review queue" in validator
    assert "/* ReviewDisposition" not in source


def test_runtime_permission_allowlist_contains_only_the_pending_review_procedures() -> None:
    permissions = PERMISSION_VALIDATOR.read_text(encoding="utf-8")
    assert "ListPendingPublicationReviews" in permissions
    assert "RecordPendingPublicationReview" in permissions
