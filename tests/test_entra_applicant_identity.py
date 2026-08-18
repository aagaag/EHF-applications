from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.auth.applicant import (
    ApplicantAuthService,
    CapturingVerificationDelivery,
    InMemoryApplicantAuthRepository,
)
from app.auth.rate_limit import InMemoryRateLimiter, RateLimitPolicy
from app.auth.turnstile import TurnstileVerifier
from app.config import Settings
from app.identity import AuthenticatedIdentity, CloudflareAccessIdentityResolver
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity


APPLICATION_A = UUID("a1000000-0000-4000-8000-000000000001")
APPLICATION_B = UUID("a1000000-0000-4000-8000-000000000002")
ENTRA_A = UUID("a2000000-0000-4000-8000-000000000001")


def _service() -> tuple[ApplicantAuthService, InMemoryApplicantAuthRepository]:
    repository = InMemoryApplicantAuthRepository()
    repository.link_entra_identity(ENTRA_A, APPLICATION_A)
    return (
        ApplicantAuthService(
            repository,
            CapturingVerificationDelivery(),
            otp_pepper=b"entra-otp-pepper-that-is-at-least-32-bytes",
            session_pepper=b"entra-session-pepper-that-is-at-least-32-bytes",
        ),
        repository,
    )


def test_entra_identity_maps_to_exactly_one_application_and_unknown_identity_fails_closed() -> None:
    """Break caught: EHF-Applicants membership alone could expose an arbitrary applicant row."""
    service, _repository = _service()

    session = service.establish_entra(ENTRA_A, datetime(2026, 8, 18, 11, 0, tzinfo=UTC))
    unknown = service.establish_entra(
        UUID("a2000000-0000-4000-8000-000000000002"),
        datetime(2026, 8, 18, 11, 0, tzinfo=UTC),
    )

    assert session is not None
    assert session.application_id == APPLICATION_A
    assert session.application_id != APPLICATION_B
    assert unknown is None


def test_entra_sign_in_sets_an_application_session_only_for_ehf_applicants() -> None:
    """Break caught: an unrelated Entra guest could bootstrap an applicant session."""
    service, _repository = _service()
    applicant = AuthenticatedIdentity(
        Identity("cloudflare:subject", "pilot@example.test", "Pilot"),
        frozenset({INTERNAL_GROUPS.applicants}),
        entra_object_id=ENTRA_A,
    )
    app = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: applicant,
        applicant_auth_service=service,
    )
    with TestClient(app, base_url="https://localhost") as client:
        response = client.get("/applicant/sign-in", follow_redirects=False)
        session = client.get("/api/applicant/session")

    assert response.status_code == 303
    assert response.headers["location"] == "/applicant/review"
    assert session.status_code == 200
    assert session.json() == {"authenticated": True}

    unrelated = AuthenticatedIdentity(
        Identity("cloudflare:other", "other@example.test", "Other"),
        frozenset({INTERNAL_GROUPS.trustees}),
        entra_object_id=ENTRA_A,
    )
    denied = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: unrelated,
        applicant_auth_service=service,
    )
    with TestClient(denied, base_url="https://localhost") as client:
        assert client.get("/applicant/sign-in", follow_redirects=False).status_code == 404


def test_entra_sign_in_session_cookie_survives_the_external_identity_redirect() -> None:
    """Break caught: SameSite=Strict could cause an endless sign-in/review redirect loop."""
    service, _repository = _service()
    applicant = AuthenticatedIdentity(
        Identity("cloudflare:subject", "pilot@example.test", "Pilot"),
        frozenset({INTERNAL_GROUPS.applicants}),
        entra_object_id=ENTRA_A,
    )
    app = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: applicant,
        applicant_auth_service=service,
    )

    with TestClient(app, base_url="https://localhost") as client:
        response = client.get("/applicant/sign-in", follow_redirects=False)

    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(
        value for value in cookies if "__Host-ehf_applicant_session=" in value
    )
    csrf_cookie = next(
        value for value in cookies if "__Host-ehf_applicant_csrf=" in value
    )
    assert all(
        flag in session_cookie
        for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/")
    )
    assert all(flag in csrf_cookie for flag in ("Secure", "SameSite=strict", "Path=/"))


@pytest.mark.parametrize(
    ("path", "heading"),
    (
        ("/applicant/review", "Review your application"),
        ("/applicant/documents", "Your application documents"),
        ("/applicant/final-review", "Final review and submission"),
    ),
)
def test_signed_in_entra_applicant_can_open_canonical_workspace_pages(
    path: str, heading: str
) -> None:
    """Break caught: extensionless workspace links could fall through to the JSON 404."""
    service, _repository = _service()
    applicant = AuthenticatedIdentity(
        Identity("cloudflare:subject", "pilot@example.test", "Pilot"),
        frozenset({INTERNAL_GROUPS.applicants}),
        entra_object_id=ENTRA_A,
    )
    app = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: applicant,
        applicant_auth_service=service,
    )

    with TestClient(app, base_url="https://localhost") as client:
        assert client.get("/applicant/sign-in", follow_redirects=False).status_code == 303
        response = client.get(path, follow_redirects=False)

    assert response.status_code == 200
    assert heading in response.text


def test_canonical_workspace_page_bootstraps_a_missing_application_session() -> None:
    """Break caught: a valid Entra applicant opening a direct page link could see a JSON 404."""
    service, _repository = _service()
    applicant = AuthenticatedIdentity(
        Identity("cloudflare:subject", "pilot@example.test", "Pilot"),
        frozenset({INTERNAL_GROUPS.applicants}),
        entra_object_id=ENTRA_A,
    )
    app = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: applicant,
        applicant_auth_service=service,
    )

    with TestClient(app, base_url="https://localhost") as client:
        response = client.get("/applicant/review", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/applicant/sign-in"


def test_cloudflare_resolver_preserves_verified_entra_object_id_for_mapping(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Break caught: applicant mapping could fall back to mutable email addresses."""
    resolver = CloudflareAccessIdentityResolver(
        issuer="https://team.cloudflareaccess.com",
        audience=("internal-audience", "applicant-audience"),
        administrator_group_id="admin-id",
        trustee_group_id="trustee-id",
        applicant_group_id="applicant-id",
    )
    resolver._keys = SimpleNamespace(  # type: ignore[attr-defined]
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key="public-key")
    )
    monkeypatch.setattr(
        "app.identity.jwt.decode",
        lambda *_args, **_kwargs: {
            "type": "app",
            "email": "pilot@example.test",
            "sub": "cloudflare-subject",
            "custom": {"oid": str(ENTRA_A)},
        },
    )
    monkeypatch.setattr(
        "app.identity.httpx.get",
        lambda *_args, **_kwargs: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "email": "pilot@example.test",
                "idp": {"name": "Pilot", "groups": ["applicant-id"]},
            },
        ),
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/applicant/sign-in",
            "headers": [
                (b"cf-access-jwt-assertion", b"signed-token"),
                (b"cookie", b"CF_Authorization=session-token"),
            ],
        }
    )

    principal = resolver(request)

    assert principal is not None
    assert principal.groups == frozenset({INTERNAL_GROUPS.applicants})
    assert principal.entra_object_id == ENTRA_A


def test_every_applicant_api_request_revalidates_live_group_and_object_id() -> None:
    """Break caught: removing EHF-Applicants membership could leave a 24-hour session usable."""
    service, _repository = _service()
    current = {"principal": AuthenticatedIdentity(
        Identity("cloudflare:subject", "pilot@example.test", "Pilot"),
        frozenset({INTERNAL_GROUPS.applicants}),
        entra_object_id=ENTRA_A,
    )}
    app = create_app(
        Settings.from_environment({"EHF_APPLICANT_PORTAL_ENABLED": "true"}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: current["principal"],
        applicant_auth_service=service,
        applicant_turnstile=TurnstileVerifier(
            "synthetic-secret", "localhost",
            lambda *_args: {"success": True, "hostname": "localhost", "action": "test"},
        ),
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=10, window=timedelta(minutes=10))
        ),
    )
    with TestClient(app, base_url="https://localhost") as client:
        assert client.get("/applicant/sign-in", follow_redirects=False).status_code == 303
        assert client.get("/api/applicant/session").status_code == 200
        current["principal"] = AuthenticatedIdentity(
            Identity("cloudflare:subject", "pilot@example.test", "Pilot"),
            frozenset(),
            entra_object_id=ENTRA_A,
        )
        assert client.get("/api/applicant/session").status_code == 404
