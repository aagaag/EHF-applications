from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID
import re

import pytest
from fastapi.testclient import TestClient

from app.applicant.approval import ApplicantApprovalService, ApplicantPreviewBundle
from app.applicant.admin_preview import _citation_counts, render_applicant_preview
from app.config import Settings
from app.identity import AuthenticatedIdentity
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity


APPLICATION_ID = UUID("a7000000-0000-4000-8000-000000000001")


def test_preview_uses_only_openalex_when_no_observation_exists() -> None:
    value = _citation_counts(
        SimpleNamespace(
            citation_count=None,
            citation_status=None,
            openalex_citation_count=None,
            openalex_citation_status=None,
            semantic_scholar_citation_count=35,
            semantic_scholar_citation_status="OBSERVED",
        )
    )

    assert value == "OpenAlex: Not available"


def test_preview_shows_a_recovered_phd_conferral_year_without_inventing_a_date() -> None:
    """Break caught: legacy academic-age evidence was rendered as a missing PhD date."""
    page = render_applicant_preview(
        ApplicantPreviewBundle(
            APPLICATION_ID,
            "Synthetic Preview Applicant",
            "IMPORTED",
            {
                "applicant": {
                    "fullName": "Synthetic Preview Applicant",
                    "degreeCategory": "PHD",
                    "phdDate": None,
                    "phdConferralYear": 2019,
                }
            },
            {},
        )
    )

    assert 'value="2019 (year recorded; full date unavailable)"' in page


@pytest.mark.parametrize("recovered_year", (2019.0, 2019.9, "2019.9"))
def test_preview_rejects_a_non_year_phd_conferral_value(recovered_year: object) -> None:
    """Break caught: malformed source values were silently truncated into a year."""
    page = render_applicant_preview(
        ApplicantPreviewBundle(
            APPLICATION_ID,
            "Synthetic Preview Applicant",
            "IMPORTED",
            {
                "applicant": {
                    "fullName": "Synthetic Preview Applicant",
                    "degreeCategory": "PHD",
                    "phdDate": None,
                    "phdConferralYear": recovered_year,
                }
            },
            {},
        )
    )

    assert 'value="Missing"' in page
    assert "year recorded; full date unavailable" not in page


def test_preview_preserves_an_exact_phd_conferral_date() -> None:
    """Break caught: a year-only fallback could replace a stored exact conferral date."""
    page = render_applicant_preview(
        ApplicantPreviewBundle(
            APPLICATION_ID,
            "Synthetic Preview Applicant",
            "IMPORTED",
            {
                "applicant": {
                    "fullName": "Synthetic Preview Applicant",
                    "degrees": [{"degreeType": "PhD", "conferralDate": "2020-06-30"}],
                    "phdConferralYear": 2019,
                }
            },
            {},
        )
    )

    assert 'value="2020-06-30"' in page
    assert "year recorded; full date unavailable" not in page


def test_preview_uses_a_validated_return_link_for_filtered_applicant_lists() -> None:
    bundle = ApplicantPreviewBundle(
        APPLICATION_ID,
        "Synthetic Preview Applicant",
        "IMPORTED",
        {"applicant": {"fullName": "Synthetic Preview Applicant"}},
        {},
    )

    preserved = render_applicant_preview(
        bundle, back_href="/internal/applicants?q=Synthetic&status=IMPORTED"
    )
    unsafe = render_applicant_preview(
        bundle, back_href="https://attacker.example/collect"
    )

    assert 'href="/internal/applicants?q=Synthetic&amp;status=IMPORTED"' in preserved
    assert 'href="/internal/applicants">Back to applicants</a>' in unsafe


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
            publication_records=(
                SimpleNamespace(
                    application_publication_id=UUID(
                        "a1000000-0000-4000-8000-000000000001"
                    ),
                    authors_text="Ada Author; Ben Biologist; Cara Chemist",
                    title="A <Synthetic> Publication",
                    journal_text="Journal of Synthetic Results",
                    volume_text="12",
                    pages_text="101-109",
                    publication_year=2025,
                    citation_count=37,
                    citation_status="OBSERVED",
                    openalex_citation_count=39,
                    openalex_citation_status="OBSERVED",
                    semantic_scholar_citation_count=35,
                    semantic_scholar_citation_status="OBSERVED",
                    publication_url="https://doi.org/10.1000/example",
                ),
                SimpleNamespace(
                    application_publication_id=UUID(
                        "a1000000-0000-4000-8000-000000000002"
                    ),
                    authors_text="Dora Discoverer",
                    title="Awaiting review",
                    journal_text=None,
                    volume_text=None,
                    pages_text=None,
                    publication_year=None,
                    citation_count=None,
                    citation_status="MANUAL_REQUIRED",
                    openalex_citation_count=None,
                    openalex_citation_status="NOT_FOUND",
                    semantic_scholar_citation_count=None,
                    semantic_scholar_citation_status="NOT_FOUND",
                    publication_url=None,
                ),
            ),
        )


class UnsortedPreviewApprovalService(PreviewApprovalService):
    def previews(self, actor_group: str):  # type: ignore[no-untyped-def]
        if actor_group != INTERNAL_GROUPS.administrators:
            raise PermissionError
        return (
            SimpleNamespace(
                application_id=UUID("a7000000-0000-4000-8000-000000000003"),
                applicant_name="Zeta Applicant",
                application_status="IMPORTED",
            ),
            SimpleNamespace(
                application_id=UUID("a7000000-0000-4000-8000-000000000002"),
                applicant_name="Alpha Applicant",
                application_status="IMPORTED",
            ),
            SimpleNamespace(
                application_id=UUID("a7000000-0000-4000-8000-000000000001"),
                applicant_name="Alpha Applicant",
                application_status="IMPORTED",
            ),
        )


def _identity(group: str) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        Identity("cloudflare:previewer", "previewer@example.test", "Previewer"),
        frozenset({group}),
    )


def _app(group: str, approval: ApplicantApprovalService | None = None):  # type: ignore[no-untyped-def]
    return create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: _identity(group),
        applicant_approval_service=approval or PreviewApprovalService(),
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
                "href": f"/internal/applicants/{APPLICATION_ID}",
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
    assert "Publication records" in page.text
    assert "First author" in page.text
    assert "Ada Author; Ben Biologist; Cara Chemist" in page.text
    assert "A &lt;Synthetic&gt; Publication" in page.text
    assert "Journal of Synthetic Results. 2025;12:101-109." in page.text
    assert "Citations by source" in page.text
    assert "OpenAlex: 39" in page.text
    assert "Google Scholar:" not in page.text
    assert "Semantic Scholar:" not in page.text
    assert "OpenAlex: Not found" in page.text
    assert 'data-publication-url="https://doi.org/10.1000/example"' in page.text
    assert 'data-publication-record' in page.text
    assert 'role="link"' in page.text
    assert 'tabindex="0"' in page.text
    assert "Save changes" not in page.text
    assert "Confirm this information" not in page.text
    assert "readonly" in page.text


def test_internal_surfaces_keep_the_same_primary_navigation_while_details_use_local_tabs() -> None:
    """Break caught: opening an applicant could replace global navigation with form sections."""
    with TestClient(_app(INTERNAL_GROUPS.administrators), base_url="https://localhost") as client:
        overview = client.get("/internal/")
        applicants = client.get("/internal/applicants")
        detail = client.get(f"/internal/applicants/{APPLICATION_ID}")

    def labels(source: str) -> list[str]:
        match = re.search(
            r'<nav class="app-nav-list" aria-label="Primary navigation">(.*?)</nav>',
            source,
            flags=re.DOTALL,
        )
        assert match is not None
        return re.findall(r'<a[^>]*>([^<]+)</a>', match.group(1))

    expected = ["Overview", "Applicants", "Review queue", "Reports", "Operations"]
    assert labels(overview.text) == expected
    assert labels(applicants.text) == expected
    assert labels(detail.text) == expected
    assert 'aria-label="Applicant details"' in detail.text
    assert "Summary" in detail.text
    assert "Applicant information" in detail.text
    assert "Documents" in detail.text
    assert "Access &amp; identity" in detail.text
    assert "Internal audit" in detail.text
    assert 'aria-label="Application sections"' not in detail.text


def test_administrator_applicant_previews_are_sorted_by_name_with_deterministic_ties() -> None:
    with TestClient(
        _app(
            INTERNAL_GROUPS.administrators,
            approval=UnsortedPreviewApprovalService(),
        ),
        base_url="https://localhost",
    ) as client:
        response = client.get("/api/internal/applicant-previews")

    assert response.status_code == 200
    assert [
        (item["applicantName"], item["applicationId"])
        for item in response.json()["applications"]
    ] == [
        ("Alpha Applicant", "a7000000-0000-4000-8000-000000000001"),
        ("Alpha Applicant", "a7000000-0000-4000-8000-000000000002"),
        ("Zeta Applicant", "a7000000-0000-4000-8000-000000000003"),
    ]


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
