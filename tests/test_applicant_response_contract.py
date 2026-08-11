from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.applicant.projection import ApplicantProjectionService, InMemoryApplicantProjectionRepository
from app.auth.applicant import ApplicantSessionContext


def test_projection_serializes_only_the_applicant_allowlist() -> None:
    """Break caught: a newly added internal model field could serialize accidentally."""
    application_id = UUID("50000000-0000-4000-8000-000000000001")
    repository = InMemoryApplicantProjectionRepository()
    repository.add_application(
        application_id,
        applicant={
            "fullName": "Synthetic Allowlist Applicant",
            "preferredName": "Allowed",
            "registeredEmail": "allowed@example.test",
            "telephone": "+41 00 000 00 00",
            "internalRiskScore": "synthetic-secret-risk",
            "verifiedCitationTotal": 999999,
        },
        sections={"identity": {"confirmed": False, "missing": 0, "internalNote": "secret"}},
        documents=(
            {
                "documentId": "visible-doc",
                "versionId": "visible-version",
                "slotCode": "CV",
                "displayName": "CV.pdf",
                "classification": "APPLICANT_VISIBLE",
                "documentType": "CURRICULUM_VITAE",
                "sha256": "dd" * 32,
                "byteSize": 1500,
                "mediaType": "application/pdf",
                "storageKey": "synthetic-secret-storage",
                "sourcePath": "synthetic-secret-source-path",
                "auditEventId": "synthetic-secret-audit",
            },
        ),
        internal={
            "recommendationStatus": "synthetic-secret-recommendation",
            "securityIndicator": "synthetic-secret-security",
        },
    )
    service = ApplicantProjectionService(repository)
    context = ApplicantSessionContext(
        application_id,
        bytes(32),
        datetime.now(UTC) + timedelta(minutes=30),
        datetime.now(UTC) + timedelta(hours=24),
    )

    serialized = json.dumps(service.load(context), sort_keys=True)

    assert "Synthetic Allowlist Applicant" in serialized
    assert "visible-doc" in serialized
    for forbidden in (
        "internalRiskScore",
        "verifiedCitationTotal",
        "internalNote",
        "storageKey",
        "sourcePath",
        "auditEventId",
        "recommendation",
        "securityIndicator",
        "synthetic-secret",
    ):
        assert forbidden.casefold() not in serialized.casefold()
