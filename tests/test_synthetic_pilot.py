from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.auth.applicant import (
    ApplicantAuthService,
    CapturingVerificationDelivery,
    InMemoryApplicantAuthRepository,
)
from app.auth.rate_limit import InMemoryRateLimiter, RateLimitPolicy
from app.auth.turnstile import TurnstileVerifier
from app.config import Settings
from app.main import ReadinessChecks, create_app


def _pilot_service() -> ApplicantAuthService:
    repository = InMemoryApplicantAuthRepository()
    delivery = CapturingVerificationDelivery()
    return ApplicantAuthService(
        repository,
        delivery,
        otp_pepper=b"pilot-otp-pepper-that-is-at-least-32-bytes",
        session_pepper=b"pilot-session-pepper-that-is-at-least-32-bytes",
    )


def test_production_registers_applicant_routes_for_entra_portal_only() -> None:
    """Break caught: Entra applicant routes could remain hidden behind the invitation gate."""
    service = _pilot_service()
    settings = Settings.from_environment(
        {
            "EHF_ENVIRONMENT": "development",
            "EHF_APPLICANT_PORTAL_ENABLED": "true",
        }
    )
    settings = __import__("dataclasses").replace(
        settings,
        environment="production",
        allowed_host="ehf.isab.science",
        invitations_enabled=False,
    )
    application = create_app(
        settings,
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        applicant_auth_service=service,
        applicant_turnstile=TurnstileVerifier(
            "synthetic-secret",
            "ehf.isab.science",
            lambda *_args: {
                "success": True,
                "hostname": "ehf.isab.science",
                "action": "applicant-code-request",
            },
        ),
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=20, window=timedelta(minutes=10))
        ),
    )

    with TestClient(application, base_url="https://ehf.isab.science") as client:
        response = client.get("/applicant/sign-in", follow_redirects=False)

    assert response.status_code == 404


def test_pilot_projection_fixture_contains_no_source_values_and_preserves_missingness() -> None:
    """Break caught: provisioning could copy real applicant values instead of only absence flags."""
    from app.applicant.pilot import synthetic_projection

    projection = synthetic_projection("pilot@example.test")
    applicant = projection["applicant"]

    assert applicant["fullName"] == "Synthetic EHF test applicant"
    assert applicant["registeredEmail"] is None
    assert applicant["phdDate"] is None
    assert applicant["hIndex"] is None
    assert applicant["contributionStatement"] is None
    assert applicant["firstAuthorPaperCount"] == 3
    assert applicant["lastAuthorPaperCount"] == 1
    assert applicant["totalPaperCount"] == 8
    assert "Sevasti" not in repr(projection)
    assert "Gaspari" not in repr(projection)
