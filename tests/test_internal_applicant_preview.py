from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.applicant.approval import ApplicantApprovalService
from app.config import Settings
from app.identity import AuthenticatedIdentity
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity


APPLICATION_ID = UUID("a7000000-0000-4000-8000-000000000001")


class PreviewApprovalService(ApplicantApprovalService):
    def previews(self, actor_group: str):  # type: ignore[no-untyped-def]
        if actor_group != INTERNAL_GROUPS.administrators:
            raise PermissionError
        return (
            SimpleNamespace(
                application_id=APPLICATION_ID,
                applicant_name="Synthetic Preview Applicant",
                application_status="IMPORTED",
            ),
        )

    def preview(self, application_id: UUID, *, actor: str, actor_group: str):  # type: ignore[no-untyped-def]
        if actor_group != INTERNAL_GROUPS.administrators:
            raise PermissionError
        if application_id != APPLICATION_ID:
            raise LookupError
        return SimpleNamespace(
            application_id=APPLICATION_ID,
            applicant_name="Synthetic Preview Applicant",
            application_status="IMPORTED",
            baseline={
                "applicant": {
                    "fullName": "Synthetic Preview Applicant",
                    "registeredEmail": "preview@example.test",
                    "telephone": "+41 71 000 00 00",
                    "institute": "Synthetic Institute",
                    "postdoctoralEmploymentStatus": True,
                    "degrees": [
                        {"degreeType": "PhD", "conferralDate": "2020-06-30"}
                    ],
                    "hasGoogleScholarProfile": False,
                    "publications": [
                        {"doi": "10.1000/example", "confirmed": True}
                    ],
                }
            },
            drafts={
                "identity": {
                    "fullName": "Synthetic Preview Applicant",
                    "registeredEmail": "preview@example.test",
                    "telephone": "+41 71 111 11 11",
                }
            },
        )


def _identity(group: str) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        Identity("cloudflare:previewer", "previewer@example.test", "Previewer"),
        frozenset({group}),
    )


def _app(group: str):  # type: ignore[no-untyped-def]
    return create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: _identity(group),
        applicant_approval_service=PreviewApprovalService(),
    )


def test_administrator_can_open_every_existing_application_in_the_read_only_applicant_form() -> None:
    """Break caught: reviewers could see queues but not inspect the form applicants see."""
    with TestClient(_app(INTERNAL_GROUPS.administrators), base_url="https://localhost") as client:
        listing = client.get("/api/internal/applicant-previews")
        page = client.get(f"/internal/applicant-previews/{APPLICATION_ID}")

    assert listing.status_code == 200
    assert listing.json() == {
        "applications": [
            {
                "applicationId": str(APPLICATION_ID),
                "applicantName": "Synthetic Preview Applicant",
                "applicationStatus": "IMPORTED",
                "href": f"/internal/applicant-previews/{APPLICATION_ID}",
            }
        ]
    }
    assert page.status_code == 200
    assert "Read-only administrator preview" in page.text
    assert "Synthetic Preview Applicant" in page.text
    assert "Registered email address" in page.text
    assert "preview@example.test" in page.text
    assert "+41 71 111 11 11" in page.text
    assert "PhD" in page.text and "2020-06-30" in page.text
    assert "10.1000/example" in page.text
    assert "Save changes" not in page.text
    assert "Confirm this information" not in page.text
    assert "readonly" in page.text


def test_trustee_cannot_list_or_open_administrator_applicant_previews() -> None:
    """Break caught: the new sensitive preview could inherit broader reviewer access."""
    with TestClient(_app(INTERNAL_GROUPS.trustees), base_url="https://localhost") as client:
        listing = client.get("/api/internal/applicant-previews")
        page = client.get(f"/internal/applicant-previews/{APPLICATION_ID}")
        malformed = client.get("/internal/applicant-previews/not-a-uuid")

    assert listing.status_code == 404
    assert page.status_code == 404
    assert malformed.status_code == 404


def test_unknown_applicant_preview_uses_a_neutral_not_found_response() -> None:
    """Break caught: preview lookup could disclose which application identifiers exist."""
    with TestClient(_app(INTERNAL_GROUPS.administrators), base_url="https://localhost") as client:
        response = client.get(
            "/internal/applicant-previews/a7000000-0000-4000-8000-000000000099"
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_malformed_administrator_preview_identifier_is_also_neutral_not_found() -> None:
    with TestClient(_app(INTERNAL_GROUPS.administrators), base_url="https://localhost") as client:
        response = client.get("/internal/applicant-previews/not-a-uuid")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
