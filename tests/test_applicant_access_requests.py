from __future__ import annotations

from uuid import UUID

from app.applicant.access import ApplicantAccessService, InMemoryApplicantAccessRepository
from app.auth.rate_limit import InMemoryRateLimiter, RateLimitPolicy
from app.auth.turnstile import TurnstileVerifier
from app.config import Settings
from app.identity import AuthenticatedIdentity
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity
from datetime import timedelta
from fastapi.testclient import TestClient


def test_access_request_is_normalized_and_duplicate_open_requests_are_neutral() -> None:
    """Break caught: Entra intake could create duplicate identities or disclose an open request."""
    service = ApplicantAccessService(InMemoryApplicantAccessRepository())

    first = service.request("  Applicant@Example.org ", "  Example Applicant  ")
    second = service.request("applicant@example.org", "Example Applicant")

    assert first.requested_email == "applicant@example.org"
    assert first.requested_display_name == "Example Applicant"
    assert second.request_id == first.request_id
    assert len(service.pending()) == 1


def test_access_request_needs_reviewer_approval_before_provisioning() -> None:
    """Break caught: a prospective applicant could self-provision an Entra identity."""
    service = ApplicantAccessService(InMemoryApplicantAccessRepository())
    request = service.request("applicant@example.org", "Example Applicant")

    approved = service.review(
        request.request_id,
        decision="APPROVED",
        actor="cloudflare:administrator",
        actor_group="EHF-Administrators",
    )

    assert approved.status == "APPROVED"
    assert service.pending() == ()


def test_approved_access_request_is_atomically_bound_to_one_application() -> None:
    """Break caught: provisioning could mark a request complete without creating its mapping."""
    repository = InMemoryApplicantAccessRepository()
    service = ApplicantAccessService(repository)
    request = service.request("applicant@example.org", "Example Applicant")
    service.review(
        request.request_id,
        decision="APPROVED",
        actor="cloudflare:administrator",
        actor_group="EHF-Administrators",
    )
    application_id = UUID("f1000000-0000-4000-8000-000000000001")
    entra_object_id = UUID("f2000000-0000-4000-8000-000000000001")

    provisioned = service.provision(
        request.request_id,
        application_id=application_id,
        entra_object_id=entra_object_id,
        actor="cloudflare:administrator",
        actor_group="EHF-Administrators",
    )

    assert provisioned.status == "PROVISIONED"
    assert repository.application_for_entra(entra_object_id) == application_id
    assert service.actionable() == ()


def test_public_access_request_route_is_turnstile_protected_and_neutral() -> None:
    service = ApplicantAccessService(InMemoryApplicantAccessRepository())
    app = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        applicant_access_service=service,
        applicant_turnstile=TurnstileVerifier(
            "synthetic-secret", "localhost",
            lambda *_args: {
                "success": True, "hostname": "localhost",
                "action": "applicant-access-request",
            },
        ),
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=10, window=timedelta(minutes=10))
        ),
        applicant_turnstile_site_key="synthetic-site-key",
    )
    with TestClient(app, base_url="https://localhost") as client:
        page = client.get("/request-access")
        response = client.post("/api/applicant-access-requests", json={
            "displayName": "Example Applicant",
            "email": "applicant@example.org",
            "turnstileToken": "valid-once",
        })

    assert page.status_code == 200
    assert "synthetic-site-key" in page.text
    assert response.status_code == 202
    assert "received" in response.json()["message"]
    assert len(service.pending()) == 1


def test_reviewer_route_calls_the_atomic_provisioning_boundary() -> None:
    repository = InMemoryApplicantAccessRepository()
    service = ApplicantAccessService(repository)
    access_request = service.request("applicant@example.org", "Example Applicant")
    service.review(
        access_request.request_id,
        decision="APPROVED",
        actor="cloudflare:administrator",
        actor_group=INTERNAL_GROUPS.administrators,
    )
    administrator = AuthenticatedIdentity(
        Identity("cloudflare:administrator", "admin@example.test", "Administrator"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    app = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: administrator,
        applicant_access_service=service,
        applicant_turnstile=TurnstileVerifier(
            "synthetic-secret", "localhost", lambda *_args: {"success": False}
        ),
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=10, window=timedelta(minutes=10))
        ),
        applicant_turnstile_site_key="synthetic-site-key",
    )
    application_id = UUID("f1000000-0000-4000-8000-000000000002")
    entra_object_id = UUID("f2000000-0000-4000-8000-000000000002")
    with TestClient(app, base_url="https://localhost") as client:
        response = client.post(
            f"/api/internal/applicant-access-requests/{access_request.request_id}/provision",
            headers={"origin": "https://localhost"},
            json={
                "applicationId": str(application_id),
                "entraObjectId": str(entra_object_id),
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "PROVISIONED"
    assert repository.application_for_entra(entra_object_id) == application_id
