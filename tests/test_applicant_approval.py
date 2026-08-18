from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.applicant.approval import (
    ApplicantApprovalService,
    ApplicantDocumentReview,
    ApplicantSubmissionBundle,
)
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
        assert queue.json()["capabilities"]["returnForCorrection"] is (
            group == INTERNAL_GROUPS.administrators
        )
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


def test_administrator_can_return_one_section_for_correction_but_trustee_cannot() -> None:
    """Break caught: an unpromotable legacy answer could leave a submission stuck forever."""
    service = ApplicantApprovalService()
    service.queue(_confirmation())

    with pytest.raises(PermissionError):
        service.return_for_correction(
            CONFIRMATION_ID,
            section="employment",
            reason="Please answer the clarified postdoctoral-employment question.",
            actor="cloudflare:trustee",
            actor_group=INTERNAL_GROUPS.trustees,
        )

    returned = service.return_for_correction(
        CONFIRMATION_ID,
        section="employment",
        reason="Please answer the clarified postdoctoral-employment question.",
        actor="cloudflare:administrator",
        actor_group=INTERNAL_GROUPS.administrators,
    )

    assert returned.status == "REJECTED"
    assert service.pending() == ()


def test_return_for_correction_route_is_admin_only_and_binds_scope_to_confirmation() -> None:
    service = ApplicantApprovalService()
    service.queue(_confirmation())
    principal = AuthenticatedIdentity(
        Identity("cloudflare:administrator", "admin@example.test", "Synthetic administrator"),
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
            f"/api/internal/applicant-submissions/{CONFIRMATION_ID}/return-for-correction",
            headers={"Origin": "https://localhost"},
            json={
                "section": "employment",
                "reason": "Please answer the clarified employment question.",
                "applicationId": "ffffffff-ffff-4fff-8fff-ffffffffffff",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"
    assert response.json()["applicationId"] == str(APPLICATION_ID)


def test_internal_detail_presents_legacy_signed_values_in_the_current_schema() -> None:
    raw_baseline = {
        "applicant": {
            "degreeCategory": "MD_PHD",
            "phdDate": "2020-06-30",
            "noGoogleScholarProfile": True,
            "googleScholarCitationTotal": 321,
        }
    }
    raw_drafts = {
        "qualifications": {
            "degreeCategory": "PHD",
            "phdDate": "2021-07-01",
        },
        "publications": {
            "noGoogleScholarProfile": True,
            "googleScholarCitationTotal": 321,
        },
    }

    class LegacyApproval(ApplicantApprovalService):
        def detail(self, confirmation_id: UUID) -> ApplicantSubmissionBundle:
            return ApplicantSubmissionBundle(
                confirmation_id,
                APPLICATION_ID,
                raw_baseline,
                {"schemaVersion": 1},
                raw_drafts,
            )

    principal = AuthenticatedIdentity(
        Identity("cloudflare:reviewer", "reviewer@example.test", "Synthetic reviewer"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    app = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: principal,
        applicant_approval_service=LegacyApproval(),
    )
    with TestClient(app, base_url="https://localhost") as client:
        response = client.get(
            f"/api/internal/applicant-submissions/{CONFIRMATION_ID}"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["baseline"]["applicant"]["degrees"] == [
        {"degreeType": "MD", "conferralDate": None},
        {"degreeType": "PhD", "conferralDate": "2020-06-30"},
    ]
    assert body["drafts"]["qualifications"]["degrees"] == [
        {"degreeType": "PhD", "conferralDate": "2021-07-01"}
    ]
    assert body["drafts"]["publications"] == {
        "hasGoogleScholarProfile": False,
        "publications": [],
    }
    assert raw_drafts["qualifications"]["degreeCategory"] == "PHD"


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
