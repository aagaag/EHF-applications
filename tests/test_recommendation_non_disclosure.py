from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.applicant.projection import ApplicantProjectionService, InMemoryApplicantProjectionRepository
from app.auth.applicant import ApplicantSessionContext


def test_every_recommendation_arrival_path_is_absent_from_all_applicant_results() -> None:
    """Break caught: a forwarded or oddly classified recommendation could enter applicant output."""
    application_id = UUID("40000000-0000-4000-8000-000000000001")
    repository = InMemoryApplicantProjectionRepository()
    repository.add_application(
        application_id,
        applicant={"fullName": "Synthetic Confidentiality Applicant"},
        sections={},
        documents=(
            {
                "documentId": "direct-referee",
                "versionId": "direct-version",
                "slotCode": "REFERENCE",
                "displayName": "synthetic-direct-secret.pdf",
                "classification": "CONFIDENTIAL_RECOMMENDATION",
                "documentType": "RECOMMENDATION_LETTER",
                "arrivalChannel": "DIRECT_REFEREE",
            },
            {
                "documentId": "forwarded-by-applicant",
                "versionId": "forwarded-version",
                "slotCode": "OTHER",
                "displayName": "synthetic-forwarded-secret.pdf",
                "classification": "APPLICANT_VISIBLE",
                "documentType": "RECOMMENDATION_LETTER",
                "arrivalChannel": "APPLICANT_FORWARDED",
            },
            {
                "documentId": "linked-recommendation",
                "versionId": "linked-version",
                "slotCode": "OTHER_TWO",
                "displayName": "synthetic-linked-secret.pdf",
                "classification": "APPLICANT_VISIBLE",
                "documentType": "OTHER",
                "recommendationLinked": True,
            },
        ),
        internal={"recommendationCount": 3},
    )
    service = ApplicantProjectionService(repository)
    context = ApplicantSessionContext(
        application_id,
        bytes(32),
        datetime(2026, 8, 11, 14, 30, tzinfo=UTC),
        datetime(2026, 8, 12, 14, 0, tzinfo=UTC),
    )

    payload = service.load(context)

    assert payload is not None
    assert payload["documents"] == []
    serialized = repr(payload).casefold()
    for forbidden in (
        "recommendation",
        "direct-referee",
        "forwarded-by-applicant",
        "linked-recommendation",
        "synthetic-direct-secret",
        "synthetic-forwarded-secret",
        "synthetic-linked-secret",
    ):
        assert forbidden not in serialized


def test_recommendation_identifiers_always_resolve_as_neutral_not_found() -> None:
    """Break caught: document lookup could reveal recommendation existence by identifier."""
    application_id = UUID("40000000-0000-4000-8000-000000000002")
    repository = InMemoryApplicantProjectionRepository()
    repository.add_application(
        application_id,
        applicant={"fullName": "Synthetic Applicant"},
        sections={},
        documents=(
            {
                "documentId": "known-recommendation-id",
                "versionId": "known-recommendation-version",
                "slotCode": "REFERENCE",
                "displayName": "confidential.pdf",
                "classification": "CONFIDENTIAL_RECOMMENDATION",
                "documentType": "RECOMMENDATION_LETTER",
            },
        ),
    )
    context = ApplicantSessionContext(
        application_id,
        bytes(32),
        datetime.now(UTC) + timedelta(minutes=30),
        datetime.now(UTC) + timedelta(hours=24),
    )
    service = ApplicantProjectionService(repository)

    assert service.visible_document(context, "known-recommendation-id") is None
    assert service.visible_document(context, "unknown-id") is None
