from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from app.applicant.projection import (
    ApplicantProjectionService,
    InMemoryApplicantProjectionRepository,
)
from app.auth.applicant import ApplicantSessionContext
from app.auth.applicant import (
    ApplicantAuthService,
    CapturingVerificationDelivery,
    InMemoryApplicantAuthRepository,
    invitation_token_hash,
    new_opaque_token,
)
from app.auth.rate_limit import InMemoryRateLimiter, RateLimitPolicy
from app.auth.turnstile import TurnstileVerifier
from app.config import Settings
from app.main import ReadinessChecks, create_app


NOW = datetime(2026, 8, 11, 13, 0, tzinfo=UTC)
APPLICATION_A = UUID("30000000-0000-4000-8000-000000000001")
APPLICATION_B = UUID("30000000-0000-4000-8000-000000000002")


def _context(application_id: UUID) -> ApplicantSessionContext:
    return ApplicantSessionContext(
        application_id,
        bytes.fromhex("11" * 32),
        NOW + timedelta(minutes=30),
        NOW + timedelta(hours=24),
    )


def _repository() -> InMemoryApplicantProjectionRepository:
    repository = InMemoryApplicantProjectionRepository()
    repository.add_application(
        APPLICATION_A,
        applicant={"fullName": "Synthetic Applicant A", "preferredName": "Alpha"},
        sections={"identity": {"confirmed": False, "missing": 1}},
        documents=(
            {
                "documentId": "doc-a-visible",
                "versionId": "version-a-visible",
                "slotCode": "CV",
                "displayName": "Curriculum vitae.pdf",
                "classification": "APPLICANT_VISIBLE",
                "documentType": "CURRICULUM_VITAE",
                "sha256": "aa" * 32,
                "byteSize": 1200,
                "mediaType": "application/pdf",
                "storageKey": "synthetic-secret-storage-a",
            },
            {
                "documentId": "doc-a-internal",
                "versionId": "version-a-internal",
                "slotCode": "ADMIN",
                "displayName": "internal-secret.pdf",
                "classification": "INTERNAL_ADMINISTRATIVE",
                "documentType": "INTERNAL_NOTE",
                "sha256": "bb" * 32,
                "byteSize": 1300,
                "mediaType": "application/pdf",
                "storageKey": "synthetic-secret-storage-internal",
            },
        ),
        internal={"note": "synthetic-secret-note-a"},
    )
    repository.add_application(
        APPLICATION_B,
        applicant={"fullName": "Synthetic Applicant B", "preferredName": "Beta"},
        sections={"identity": {"confirmed": True, "missing": 0}},
        documents=(
            {
                "documentId": "doc-b-visible",
                "versionId": "version-b-visible",
                "slotCode": "CV",
                "displayName": "Other curriculum vitae.pdf",
                "classification": "APPLICANT_VISIBLE",
                "documentType": "CURRICULUM_VITAE",
                "sha256": "cc" * 32,
                "byteSize": 1400,
                "mediaType": "application/pdf",
                "storageKey": "synthetic-secret-storage-b",
            },
        ),
        internal={"note": "synthetic-secret-note-b"},
    )
    return repository


def test_session_application_is_the_only_scope_for_projection_and_documents() -> None:
    """Break caught: a guessed application or document ID could cross the session boundary."""
    service = ApplicantProjectionService(_repository())

    payload = service.load(_context(APPLICATION_A))

    assert payload["applicant"]["fullName"] == "Synthetic Applicant A"
    assert [document["documentId"] for document in payload["documents"]] == ["doc-a-visible"]
    assert service.visible_document(_context(APPLICATION_A), "doc-a-visible") is not None
    assert service.visible_document(_context(APPLICATION_A), "doc-b-visible") is None
    assert service.visible_document(_context(APPLICATION_A), "doc-a-internal") is None
    assert "Synthetic Applicant B" not in repr(payload)


def test_missing_application_returns_the_same_empty_result_without_lookup_fallback() -> None:
    """Break caught: an unknown session scope could fall back to another or first record."""
    service = ApplicantProjectionService(_repository())
    unknown = _context(UUID("30000000-0000-4000-8000-000000000099"))

    assert service.load(unknown) is None
    assert service.visible_document(unknown, "doc-a-visible") is None


def test_http_projection_ignores_guessed_application_and_exposes_no_identifier_route() -> None:
    """Break caught: an applicant-controlled query or path could choose a different record."""
    auth_repository = InMemoryApplicantAuthRepository()
    delivery = CapturingVerificationDelivery()
    auth = ApplicantAuthService(
        auth_repository,
        delivery,
        otp_pepper=b"synthetic-otp-pepper-with-at-least-32-bytes",
        session_pepper=b"synthetic-session-pepper-at-least-32-bytes",
        code_factory=lambda: "654321",
    )
    invitation = new_opaque_token()
    auth_repository.add_invitation(
        APPLICATION_A,
        invitation_token_hash(invitation),
        "scope@example.test",
        datetime.now(UTC) + timedelta(days=1),
    )
    turnstile = TurnstileVerifier(
        "synthetic-secret",
        "localhost",
        lambda _secret, _token, _ip: {
            "success": True,
            "hostname": "localhost",
            "action": "applicant-code-request",
        },
    )
    application = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        applicant_auth_service=auth,
        applicant_turnstile=turnstile,
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=20, window=timedelta(minutes=10))
        ),
        applicant_projection_service=ApplicantProjectionService(_repository()),
    )

    with TestClient(application, base_url="https://localhost") as client:
        client.get(f"/a/{invitation}")
        client.post(
            "/api/applicant/auth/code", json={"turnstileToken": "scope-turnstile"}
        )
        client.post("/api/applicant/auth/verify", json={"code": delivery.messages[-1].code})

        response = client.get(f"/api/applicant/application?applicationId={APPLICATION_B}")

        assert response.status_code == 200
        assert response.json()["applicant"]["fullName"] == "Synthetic Applicant A"
        assert str(APPLICATION_A) not in response.text
        assert str(APPLICATION_B) not in response.text
        assert client.get(f"/api/applicant/applications/{APPLICATION_B}").status_code == 404
