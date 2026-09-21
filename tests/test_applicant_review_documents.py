from __future__ import annotations

import re
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.applicant.approval import (
    ApplicantApprovalService,
    ApplicantPreviewDocument,
    ApplicantPreviewDocumentFile,
    ApplicantPreviewDocuments,
    ApplicantPreviewSummary,
)
from app.config import Settings
from app.identity import AuthenticatedIdentity
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity


APPLICATION_ID = UUID("a7000000-0000-4000-8000-000000000001")
RESEARCH_PLAN_VERSION_ID = UUID("a1000000-0000-4000-8000-000000000001")
CV_VERSION_ID = UUID("a1000000-0000-4000-8000-000000000002")
PDF_BYTES = b"%PDF-1.7 synthetic proposal"


class SyntheticApproval(ApplicantApprovalService):
    """Administrator boundary with one applicant card and two proposal PDFs."""

    def __init__(self) -> None:
        super().__init__()
        self.document_calls: list[tuple[UUID, str, str]] = []

    def previews(self, actor_group: str) -> tuple[ApplicantPreviewSummary, ...]:
        if actor_group != INTERNAL_GROUPS.administrators:
            raise PermissionError("Administrator authorization is required.")
        return (
            ApplicantPreviewSummary(
                APPLICATION_ID,
                "Synthetic Preview Applicant",
                "IMPORTED",
                academic_age_years=4.5,
                h_index=12,
                citation_count=734,
                citation_source="OPENALEX",
                citation_profile_url="https://openalex.org/A123",
                research_area="Synthetic neurodegeneration",
                document_count=2,
            ),
            ApplicantPreviewSummary(
                UUID("a7000000-0000-4000-8000-000000000002"),
                "Synthetic Missing Applicant",
                "IMPORTED",
            ),
        )

    def preview_documents(
        self, application_id: UUID, *, actor: str, actor_group: str
    ) -> ApplicantPreviewDocuments:
        if actor_group != INTERNAL_GROUPS.administrators or not actor.strip():
            raise PermissionError("Administrator authorization is required.")
        if application_id != APPLICATION_ID:
            raise LookupError("The applicant documents are unavailable.")
        return ApplicantPreviewDocuments(
            APPLICATION_ID,
            "Synthetic Preview Applicant",
            "IMPORTED",
            (
                ApplicantPreviewDocument(
                    RESEARCH_PLAN_VERSION_ID,
                    "import-3c5d91b88145",
                    "Research plan",
                    "RESEARCH_PLAN",
                    "UNREVIEWED",
                    19,
                    1_115_189,
                    "application/pdf",
                ),
                ApplicantPreviewDocument(
                    CV_VERSION_ID,
                    "import-fd9ecee62df6",
                    "Curriculum vitae",
                    "CV",
                    "UNREVIEWED",
                    6,
                    206_538,
                    "application/pdf",
                ),
            ),
        )

    def preview_document(
        self, document_version_id: UUID, *, actor: str, actor_group: str
    ) -> ApplicantPreviewDocumentFile:
        if actor_group != INTERNAL_GROUPS.administrators or not actor.strip():
            raise PermissionError("Administrator authorization is required.")
        self.document_calls.append((document_version_id, actor, actor_group))
        if document_version_id != RESEARCH_PLAN_VERSION_ID:
            raise LookupError("The applicant document is unavailable.")
        return ApplicantPreviewDocumentFile(
            display_name="research-plan-3c5d91b88145.pdf",
            media_type="application/pdf",
            content=PDF_BYTES,
        )


def _client(service: ApplicantApprovalService, group: str | None) -> TestClient:
    principal = (
        None
        if group is None
        else AuthenticatedIdentity(
            Identity("cloudflare:reviewer", "reviewer@example.test", "Synthetic reviewer"),
            frozenset({group}),
        )
    )
    app = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request, principal=principal: principal,
        applicant_approval_service=service,
    )
    return TestClient(app, base_url="https://localhost")


def test_review_cards_expose_academic_age_h_index_citations_and_area_of_work() -> None:
    """Break caught: an applicant card could omit the review metrics or invent them."""
    with _client(SyntheticApproval(), INTERNAL_GROUPS.administrators) as client:
        response = client.get("/api/internal/applicant-previews")

    assert response.status_code == 200
    cards = response.json()["applications"]
    card = next(
        item for item in cards if item["applicationId"] == str(APPLICATION_ID)
    )
    assert card["academicAgeYears"] == 4.5
    assert card["hIndex"] == 12
    assert card["citationCount"] == 734
    assert card["citationSource"] == "OPENALEX"
    assert card["researchArea"] == "Synthetic neurodegeneration"
    assert card["documentCount"] == 2
    assert card["documentsHref"] == (
        f"/internal/applicant-previews/{APPLICATION_ID}/documents"
    )
    missing = next(
        item for item in cards if item["applicationId"] != str(APPLICATION_ID)
    )
    assert missing["academicAgeYears"] is None
    assert missing["hIndex"] is None
    assert missing["citationCount"] is None
    assert missing["researchArea"] is None
    assert missing["documentCount"] == 0


def test_documents_page_lists_one_control_per_proposal_pdf() -> None:
    """Break caught: a proposal PDF could be unreachable or wrapped in a nested control."""
    with _client(SyntheticApproval(), INTERNAL_GROUPS.administrators) as client:
        response = client.get(f"/internal/applicant-previews/{APPLICATION_ID}/documents")

    assert response.status_code == 200
    page = response.text
    assert page.count("data-preview-document") == 2
    assert f'href="/api/internal/applicant-preview-documents/{RESEARCH_PLAN_VERSION_ID}"' in page
    assert "Research plan (PDF)" in page
    assert "Curriculum vitae (PDF)" in page
    assert "19 pages" in page
    assert "Synthetic Preview Applicant" in page
    cards = re.findall(
        r'<a class="shell-card preview-document-card"[^>]*>.*?</a>', page, flags=re.DOTALL
    )
    assert len(cards) == 2
    for card in cards:
        assert card.count("<a ") == 1
        assert "<button" not in card
    for fragment in (
        'data-skin-choice="default"',
        'href="/internal/applicant-review#viewpoints"',
        'href="/internal/applicant-previews/a7000000-0000-4000-8000-000000000001"',
    ):
        assert fragment in page


def test_documents_page_reports_an_application_without_documents() -> None:
    """Break caught: an empty dossier could render as an unexplained blank page."""

    class EmptyApproval(SyntheticApproval):
        def preview_documents(
            self, application_id: UUID, *, actor: str, actor_group: str
        ) -> ApplicantPreviewDocuments:
            bundle = super().preview_documents(
                application_id, actor=actor, actor_group=actor_group
            )
            return ApplicantPreviewDocuments(
                bundle.application_id, bundle.applicant_name, bundle.application_status
            )

    with _client(EmptyApproval(), INTERNAL_GROUPS.administrators) as client:
        response = client.get(f"/internal/applicant-previews/{APPLICATION_ID}/documents")

    assert response.status_code == 200
    assert "No proposal documents are available" in response.text


def test_unknown_application_documents_are_a_neutral_not_found() -> None:
    """Break caught: the documents route could disclose that an application exists elsewhere."""
    unknown = UUID("a7000000-0000-4000-8000-000000000099")
    with _client(SyntheticApproval(), INTERNAL_GROUPS.administrators) as client:
        response = client.get(f"/internal/applicant-previews/{unknown}/documents")
        malformed = client.get("/internal/applicant-previews/not-a-uuid/documents")

    assert response.status_code == 404
    assert malformed.status_code == 404


def test_proposal_pdf_route_streams_the_document_inline() -> None:
    """Break caught: a reviewer could not open the proposal PDF, or it could be cached."""
    service = SyntheticApproval()
    with _client(service, INTERNAL_GROUPS.administrators) as client:
        response = client.get(
            f"/api/internal/applicant-preview-documents/{RESEARCH_PLAN_VERSION_ID}"
        )

    assert response.status_code == 200
    assert response.content == PDF_BYTES
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'inline; filename="research-plan-3c5d91b88145.pdf"'
    )
    assert "no-store" in response.headers["cache-control"]
    assert service.document_calls == [
        (RESEARCH_PLAN_VERSION_ID, "cloudflare:reviewer", INTERNAL_GROUPS.administrators)
    ]


def test_proposal_pdfs_deny_trustees_administrator_less_identities_and_guessed_ids() -> None:
    """Break caught: a trustee, applicant, or stale document id could reach a dossier PDF."""
    for group in (INTERNAL_GROUPS.trustees, INTERNAL_GROUPS.applicants, None):
        service = SyntheticApproval()
        with _client(service, group) as client:
            documents = client.get(
                f"/internal/applicant-previews/{APPLICATION_ID}/documents"
            )
            pdf = client.get(
                f"/api/internal/applicant-preview-documents/{RESEARCH_PLAN_VERSION_ID}"
            )
        assert documents.status_code == 404, group
        assert pdf.status_code == 404, group
        assert service.document_calls == [], group

    service = SyntheticApproval()
    with _client(service, INTERNAL_GROUPS.administrators) as client:
        unknown = client.get(
            f"/api/internal/applicant-preview-documents/{CV_VERSION_ID}"
        )
        malformed = client.get("/api/internal/applicant-preview-documents/document-1")
    assert unknown.status_code == 404
    assert malformed.status_code == 404


def test_review_metrics_deny_trustees_and_unauthenticated_readers() -> None:
    """Break caught: non-administrators could read the applicant citation metrics."""
    for group in (INTERNAL_GROUPS.trustees, INTERNAL_GROUPS.applicants, None):
        with _client(SyntheticApproval(), group) as client:
            response = client.get("/api/internal/applicant-previews")
        assert response.status_code == 404, group


def test_in_memory_service_keeps_the_document_boundary_closed() -> None:
    """Break caught: the fallback service could serve documents without an administrator."""
    service = ApplicantApprovalService()

    with pytest.raises(PermissionError):
        service.preview_documents(
            APPLICATION_ID, actor="cloudflare:trustee", actor_group=INTERNAL_GROUPS.trustees
        )
    with pytest.raises(PermissionError):
        service.preview_document(
            RESEARCH_PLAN_VERSION_ID,
            actor="cloudflare:trustee",
            actor_group=INTERNAL_GROUPS.trustees,
        )
    with pytest.raises(LookupError):
        service.preview_document(
            RESEARCH_PLAN_VERSION_ID,
            actor="cloudflare:administrator",
            actor_group=INTERNAL_GROUPS.administrators,
        )
    with pytest.raises(LookupError):
        service.preview_documents(
            APPLICATION_ID,
            actor="cloudflare:administrator",
            actor_group=INTERNAL_GROUPS.administrators,
        )
