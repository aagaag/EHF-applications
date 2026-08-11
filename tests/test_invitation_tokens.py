from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

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


NOW = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)


def _service() -> tuple[
    ApplicantAuthService,
    InMemoryApplicantAuthRepository,
    CapturingVerificationDelivery,
]:
    repository = InMemoryApplicantAuthRepository()
    delivery = CapturingVerificationDelivery()
    service = ApplicantAuthService(
        repository,
        delivery,
        otp_pepper=b"synthetic-otp-pepper-with-at-least-32-bytes",
        session_pepper=b"synthetic-session-pepper-at-least-32-bytes",
        code_factory=lambda: "654321",
    )
    return service, repository, delivery


def test_known_invitation_requests_code_without_storing_raw_token() -> None:
    """Break caught: a valid personalized link could fail or persist its bearer token."""
    service, repository, delivery = _service()
    application_id = UUID("10000000-0000-4000-8000-000000000001")
    raw_token = new_opaque_token()
    repository.add_invitation(
        application_id,
        invitation_token_hash(raw_token),
        "applicant@example.test",
        NOW + timedelta(days=14),
    )

    context = service.establish(raw_token, NOW)
    response = service.request_code(context, NOW)

    assert response == "If the invitation is valid, a code was sent to the registered address."
    assert len(delivery.messages) == 1
    assert delivery.messages[0].recipient == "applicant@example.test"
    assert raw_token not in repr(repository)
    assert raw_token not in repr(delivery.messages)


def test_unknown_expired_and_revoked_links_have_the_same_neutral_result() -> None:
    """Break caught: code requests could reveal whether an invitation exists or is active."""
    service, repository, delivery = _service()
    expired_token = new_opaque_token()
    revoked_token = new_opaque_token()
    repository.add_invitation(
        UUID("10000000-0000-4000-8000-000000000002"),
        invitation_token_hash(expired_token),
        "expired@example.test",
        NOW - timedelta(seconds=1),
    )
    repository.add_invitation(
        UUID("10000000-0000-4000-8000-000000000003"),
        invitation_token_hash(revoked_token),
        "revoked@example.test",
        NOW + timedelta(days=1),
        revoked_at=NOW - timedelta(seconds=1),
    )

    responses = [
        service.request_code(service.establish(token, NOW), NOW)
        for token in (new_opaque_token(), expired_token, revoked_token, "malformed")
    ]

    assert responses == [responses[0]] * 4
    assert delivery.messages == []


def test_preauth_context_is_single_use_after_successful_verification() -> None:
    """Break caught: forwarding or replaying a completed pre-auth context could create sessions."""
    service, repository, delivery = _service()
    raw_token = new_opaque_token()
    repository.add_invitation(
        UUID("10000000-0000-4000-8000-000000000004"),
        invitation_token_hash(raw_token),
        "single-use@example.test",
        NOW + timedelta(days=1),
    )
    context = service.establish(raw_token, NOW)
    service.request_code(context, NOW)
    code = delivery.messages[-1].code

    session = service.verify_code(context, code, NOW + timedelta(seconds=1))

    assert session.application_id == UUID("10000000-0000-4000-8000-000000000004")
    assert service.verify_code(context, code, NOW + timedelta(seconds=2)) is None


def test_http_entry_replaces_bearer_url_and_sets_hardened_session_cookies() -> None:
    """Break caught: the invitation bearer could remain in history or cookies could be weak."""
    service, repository, delivery = _service()
    token = new_opaque_token()
    repository.add_invitation(
        UUID("10000000-0000-4000-8000-000000000005"),
        invitation_token_hash(token),
        "route@example.test",
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
        applicant_auth_service=service,
        applicant_turnstile=turnstile,
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=20, window=timedelta(minutes=10))
        ),
    )

    with TestClient(application, base_url="https://localhost") as client:
        entry = client.get(f"/a/{token}", follow_redirects=False)
        assert entry.status_code == 303
        assert entry.headers["location"] == "/applicant/verify"
        preauth_cookie = entry.headers["set-cookie"]
        assert "ehf_applicant_preauth=" in preauth_cookie
        assert all(flag in preauth_cookie for flag in ("HttpOnly", "Secure", "SameSite=strict"))
        assert token not in preauth_cookie

        requested = client.post(
            "/api/applicant/auth/code", json={"turnstileToken": "turnstile-one"}
        )
        assert requested.status_code == 202
        assert requested.json() == {
            "message": "If the invitation is valid, a code was sent to the registered address."
        }
        verified = client.post(
            "/api/applicant/auth/verify", json={"code": delivery.messages[-1].code}
        )
        assert verified.status_code == 200
        assert verified.json() == {"next": "/applicant/review"}
        cookies = verified.headers.get_list("set-cookie")
        session_cookie = next(value for value in cookies if "__Host-ehf_applicant_session=" in value)
        csrf_cookie = next(value for value in cookies if "__Host-ehf_applicant_csrf=" in value)
        assert all(flag in session_cookie for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"))
        assert "HttpOnly" not in csrf_cookie
        assert all(flag in csrf_cookie for flag in ("Secure", "SameSite=strict", "Path=/"))
        authenticated = client.get("/api/applicant/session")
        assert authenticated.status_code == 200
        assert authenticated.json() == {"authenticated": True}
        assert authenticated.headers["cache-control"] == "private, no-store"


def test_http_unknown_and_valid_preauth_responses_share_one_identity_neutral_shape() -> None:
    """Break caught: response structure could let an attacker enumerate valid invitations."""
    service, repository, _delivery = _service()
    token = new_opaque_token()
    repository.add_invitation(
        UUID("10000000-0000-4000-8000-000000000006"),
        invitation_token_hash(token),
        "neutral@example.test",
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
        applicant_auth_service=service,
        applicant_turnstile=turnstile,
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=20, window=timedelta(minutes=10))
        ),
    )

    bodies: list[dict[str, str]] = []
    for index, candidate in enumerate((token, new_opaque_token())):
        with TestClient(application, base_url="https://localhost") as client:
            entry = client.get(f"/a/{candidate}", follow_redirects=False)
            assert entry.status_code == 303
            assert entry.headers["location"] == "/applicant/verify"
            page = client.get("/applicant/verify")
            assert "neutral@example.test" not in page.text
            response = client.post(
                "/api/applicant/auth/code",
                json={"turnstileToken": f"turnstile-{index}"},
            )
            assert response.status_code == 202
            bodies.append(response.json())

    assert bodies == [bodies[0], bodies[0]]


def test_http_verification_attempts_are_rate_limited_by_context_and_ip() -> None:
    """Break caught: attackers could bypass request throttles by guessing OTPs directly."""
    service, repository, _delivery = _service()
    token = new_opaque_token()
    repository.add_invitation(
        UUID("10000000-0000-4000-8000-000000000007"),
        invitation_token_hash(token),
        "limited@example.test",
        datetime.now(UTC) + timedelta(days=1),
    )
    application = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        applicant_auth_service=service,
        applicant_turnstile=TurnstileVerifier(
            "synthetic-secret",
            "localhost",
            lambda *_args: {"success": True, "hostname": "localhost", "action": "applicant-code-request"},
        ),
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=2, window=timedelta(minutes=10))
        ),
    )

    with TestClient(application, base_url="https://localhost") as client:
        client.get(f"/a/{token}")
        assert client.post("/api/applicant/auth/verify", json={"code": "000000"}).status_code == 401
        assert client.post(
            "/api/applicant/auth/verify",
            json={"code": "000000", "turnstileToken": "verification-turnstile"},
        ).status_code == 401
        blocked = client.post("/api/applicant/auth/verify", json={"code": "000000"})
        assert blocked.status_code == 429
        assert blocked.json() == {"message": "Please wait before trying again."}


def test_production_invitation_routes_remain_absent_while_gate_is_false() -> None:
    """Break caught: dependency wiring could bypass the explicit production invitation gate."""
    service, _repository, _delivery = _service()
    settings = replace(
        Settings.from_environment({}),
        environment="production",
        allowed_host="ehf.isab.science",
        invitations_enabled=False,
    )
    application = create_app(
        settings,
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: None,
        applicant_auth_service=service,
        applicant_turnstile=TurnstileVerifier(
            "synthetic-secret",
            "ehf.isab.science",
            lambda *_args: {"success": True, "hostname": "ehf.isab.science", "action": "applicant-code-request"},
        ),
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=20, window=timedelta(minutes=10))
        ),
    )

    response = TestClient(application, base_url="https://ehf.isab.science").get(
        f"/a/{new_opaque_token()}", follow_redirects=False
    )

    assert response.status_code == 404
