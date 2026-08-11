from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from app.applicant.confirmations import SectionConfirmationService
from app.applicant.drafts import InMemoryDraftRepository
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
from app.preferences import InMemoryPreferenceRepository


def _client() -> tuple[TestClient, CapturingVerificationDelivery]:
    application_id = UUID("71000000-0000-4000-8000-000000000001")
    repository = InMemoryApplicantAuthRepository()
    delivery = CapturingVerificationDelivery()
    auth = ApplicantAuthService(
        repository,
        delivery,
        otp_pepper=b"synthetic-otp-pepper-with-at-least-32-bytes",
        session_pepper=b"synthetic-session-pepper-at-least-32-bytes",
        code_factory=lambda: "654321",
    )
    token = new_opaque_token()
    repository.add_invitation(
        application_id,
        invitation_token_hash(token),
        "review@example.test",
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
    review = ApplicantReviewService(InMemoryDraftRepository(), SectionConfirmationService())
    app = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        applicant_auth_service=auth,
        applicant_turnstile=turnstile,
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=20, window=timedelta(minutes=10))
        ),
        applicant_review_service=review,
        preference_repository=InMemoryPreferenceRepository(),
    )
    client = TestClient(app, base_url="https://localhost")
    client.get(f"/a/{token}")
    client.post("/api/applicant/auth/code", json={"turnstileToken": "review-turnstile"})
    client.post("/api/applicant/auth/verify", json={"code": "654321"})
    return client, delivery


def test_review_routes_require_csrf_then_save_and_explicitly_confirm() -> None:
    """Break caught: cross-site writes or navigation could save/confirm applicant data."""
    client, _delivery = _client()
    try:
        rejected = client.put(
            "/api/applicant/review/contribution",
            json={"values": {"contributionStatement": "A synthetic contribution."}, "expectedRowVersion": None},
        )
        assert rejected.status_code == 403

        csrf = client.cookies.get("__Host-ehf_applicant_csrf")
        saved = client.put(
            "/api/applicant/review/contribution",
            json={"values": {"contributionStatement": "A synthetic contribution."}, "expectedRowVersion": None},
            headers={"x-csrf-token": csrf},
        )
        assert saved.status_code == 200
        assert saved.json() == {
            "saved": True,
            "rowVersion": 1,
            "values": {"contributionStatement": "A synthetic contribution."},
            "confirmed": False,
        }

        confirmed = client.post(
            "/api/applicant/review/contribution/confirm",
            json={"rowVersion": 1},
            headers={"x-csrf-token": csrf},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["confirmed"] is True
        assert len(confirmed.json()["canonicalSha256"]) == 64
    finally:
        client.close()


def test_review_route_returns_current_version_on_stale_autosave() -> None:
    """Break caught: stale writes could overwrite data or return no reconciliation state."""
    client, _delivery = _client()
    try:
        csrf = client.cookies.get("__Host-ehf_applicant_csrf")
        client.put(
            "/api/applicant/review/contribution",
            json={"values": {"contributionStatement": "Current contribution."}, "expectedRowVersion": None},
            headers={"x-csrf-token": csrf},
        )
        stale = client.put(
            "/api/applicant/review/contribution",
            json={"values": {"contributionStatement": "Stale contribution."}, "expectedRowVersion": 0},
            headers={"x-csrf-token": csrf},
        )

        assert stale.status_code == 409
        assert stale.json()["current"]["values"] == {
            "contributionStatement": "Current contribution."
        }
        assert stale.json()["current"]["rowVersion"] == 1
    finally:
        client.close()


def test_applicant_appearance_preferences_are_session_scoped_and_csrf_protected() -> None:
    """Break caught: applicant appearance could be unsaved or writable cross-site."""
    client, _delivery = _client()
    try:
        current = client.get("/api/preferences")
        assert current.status_code == 200
        assert current.json()["skin"] == "default"

        payload = {"skin": "blue", "invert": False, "compact": True, "reduceMotion": True}
        assert client.post("/api/preferences", json=payload).status_code == 403
        saved = client.post(
            "/api/preferences",
            json=payload,
            headers={"x-csrf-token": client.cookies.get("__Host-ehf_applicant_csrf")},
        )
        assert saved.status_code == 200
        assert saved.json() == payload
        assert client.get("/api/preferences").json() == payload
    finally:
        client.close()
