from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.applicant.approval import ApplicantApprovalService, ApplicantDocumentReview
from app.applicant.finalize import FinalConfirmation
from app.config import Settings
from app.identity import AuthenticatedIdentity
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity


CONFIRMATION_ID = UUID("81000000-0000-4000-8000-000000000001")
APPLICATION_ID = UUID("82000000-0000-4000-8000-000000000001")


def _confirmation() -> FinalConfirmation:
    return FinalConfirmation(
        CONFIRMATION_ID,
        APPLICATION_ID,
        {"schemaVersion": 1, "sections": [], "documents": []},
        "a" * 64,
        datetime(2026, 8, 18, 10, 0, tzinfo=UTC),
    )


def test_submitted_applicant_changes_remain_pending_until_an_authorized_review() -> None:
    """Break caught: applicant submission could become authoritative without reviewer approval."""
    service = ApplicantApprovalService()
    service.queue(_confirmation())

    assert service.pending()[0].status == "PENDING"
    with pytest.raises(PermissionError):
        service.approve(
            CONFIRMATION_ID,
            actor="applicant:test",
            actor_group="APPLICANT",
        )
    assert service.pending()[0].status == "PENDING"

    approved = service.approve(
        CONFIRMATION_ID,
        actor="cloudflare:reviewer",
        actor_group=INTERNAL_GROUPS.trustees,
    )

    assert approved.status == "APPROVED"
    assert approved.reviewed_by == "cloudflare:reviewer"
    assert service.pending() == ()


def test_internal_approval_route_accepts_trustees_and_administrators_only() -> None:
    """Break caught: an applicant or unrelated identity could approve proposed changes."""
    for group in (INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees):
        service = ApplicantApprovalService()
        service.queue(_confirmation())
        principal = AuthenticatedIdentity(
            Identity("cloudflare:reviewer", "reviewer@example.test", "Synthetic reviewer"),
            frozenset({group}),
        )
        app = create_app(
            Settings.from_environment({}),
            readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
            identity_resolver=lambda _request, principal=principal: principal,
            applicant_approval_service=service,
        )
        with TestClient(app, base_url="https://localhost") as client:
            queue = client.get("/api/internal/applicant-submissions")
            approved = client.post(
                f"/api/internal/applicant-submissions/{CONFIRMATION_ID}/approve",
                headers={"Origin": "https://localhost"},
            )
        assert queue.status_code == 200
        assert queue.json()["submissions"][0]["applicationId"] == str(APPLICATION_ID)
        assert approved.status_code == 200
        assert approved.json()["status"] == "APPROVED"

    denied = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: None,
        applicant_approval_service=ApplicantApprovalService(),
    )
    with TestClient(denied, base_url="https://localhost") as client:
        assert client.get("/api/internal/applicant-submissions").status_code == 404
        assert client.post(
            f"/api/internal/applicant-submissions/{CONFIRMATION_ID}/approve"
        ).status_code == 404


def test_approval_route_never_accepts_a_browser_supplied_application_id() -> None:
    """Break caught: a reviewer request could redirect approval to a different applicant record."""
    service = ApplicantApprovalService()
    service.queue(_confirmation())
    principal = AuthenticatedIdentity(
        Identity("cloudflare:reviewer", "reviewer@example.test", "Synthetic reviewer"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    app = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: principal,
        applicant_approval_service=service,
    )
    with TestClient(app, base_url="https://localhost") as client:
        response = client.post(
            f"/api/internal/applicant-submissions/{CONFIRMATION_ID}/approve",
            headers={"Origin": "https://localhost"},
            json={"applicationId": "ffffffff-ffff-4fff-8fff-ffffffffffff"},
        )

    assert response.status_code == 400
    assert service.pending()[0].application_id == APPLICATION_ID


def test_internal_approval_route_rejects_cross_site_writes() -> None:
    service = ApplicantApprovalService()
    service.queue(_confirmation())
    principal = AuthenticatedIdentity(
        Identity("cloudflare:reviewer", "reviewer@example.test", "Synthetic reviewer"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    app = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: principal,
        applicant_approval_service=service,
    )
    with TestClient(app, base_url="https://localhost") as client:
        response = client.post(
            f"/api/internal/applicant-submissions/{CONFIRMATION_ID}/approve",
            headers={"Origin": "https://attacker.example"},
        )

    assert response.status_code == 403
    assert service.pending()[0].status == "PENDING"


def test_document_submission_requires_an_authorized_acceptance() -> None:
    """Break caught: an applicant PDF could become active without administrator/trustee review."""
    service = ApplicantApprovalService()
    submission_id = UUID("83000000-0000-4000-8000-000000000001")
    service.queue_document(
        ApplicantDocumentReview(
            submission_id,
            APPLICATION_ID,
            UUID("84000000-0000-4000-8000-000000000001"),
            UUID("85000000-0000-4000-8000-000000000001"),
            "additional.pdf",
            datetime(2026, 8, 18, 10, 5, tzinfo=UTC),
        )
    )
    with pytest.raises(PermissionError):
        service.accept_document(submission_id, actor="applicant", actor_group="APPLICANT")

    accepted = service.accept_document(
        submission_id,
        actor="cloudflare:reviewer",
        actor_group=INTERNAL_GROUPS.administrators,
    )

    assert accepted.status == "ACCEPTED"
    assert service.pending_documents() == ()
