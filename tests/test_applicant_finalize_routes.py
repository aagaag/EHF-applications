from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from app.applicant.confirmations import SectionConfirmationService
from app.applicant.documents import DocumentSlotRepository
from app.applicant.drafts import InMemoryDraftRepository
from app.applicant.finalize import FinalizationService
from app.applicant.review import ApplicantReviewService
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


def _client() -> TestClient:
    application_id = UUID("75000000-0000-4000-8000-000000000001")
    repository = InMemoryApplicantAuthRepository()
    auth = ApplicantAuthService(
        repository,
        CapturingVerificationDelivery(),
        otp_pepper=b"synthetic-otp-pepper-with-at-least-32-bytes",
        session_pepper=b"synthetic-session-pepper-at-least-32-bytes",
        code_factory=lambda: "654321",
    )
    token = new_opaque_token()
    repository.add_invitation(
        application_id,
        invitation_token_hash(token),
        "final@example.test",
        datetime.now(UTC) + timedelta(days=1),
    )
    turnstile = TurnstileVerifier(
        "synthetic-secret",
        "localhost",
        lambda *_args: {
            "success": True,
            "hostname": "localhost",
            "action": "applicant-code-request",
        },
    )
    drafts = InMemoryDraftRepository()
    confirmations = SectionConfirmationService()
    review = ApplicantReviewService(drafts, confirmations)
    finalization = FinalizationService(
        review, drafts, confirmations, DocumentSlotRepository()
    )
    app = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        applicant_auth_service=auth,
        applicant_turnstile=turnstile,
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=20, window=timedelta(minutes=10))
        ),
        applicant_review_service=review,
        applicant_finalization_service=finalization,
    )
    client = TestClient(app, base_url="https://localhost")
    client.get(f"/a/{token}")
    client.post("/api/applicant/auth/code", json={"turnstileToken": "final-turnstile"})
    client.post("/api/applicant/auth/verify", json={"code": "654321"})
    return client


def test_finalization_preview_is_scoped_and_submission_requires_csrf() -> None:
    """Break caught: submission could leak state or accept a cross-site write."""
    client = _client()
    try:
        preview = client.get("/api/applicant/finalization")
        assert preview.status_code == 200
        assert preview.json()["ready"] is False
        assert "applicationId" not in preview.text

        rejected = client.post("/api/applicant/finalization")
        assert rejected.status_code == 403

        csrf = client.cookies.get("__Host-ehf_applicant_csrf")
        blocked = client.post(
            "/api/applicant/finalization", headers={"x-csrf-token": csrf}
        )
        assert blocked.status_code == 422
        assert "section:contribution" in blocked.json()["unresolved"]
    finally:
        client.close()
