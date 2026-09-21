from __future__ import annotations

import base64
import io
import json
import os
import pytest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from app.applicant.approval import ApplicantApprovalService
from app.applicant.documents import (
    ApplicantDocumentService,
    DocumentSlotRepository,
    REVIEW_ARTIFACT_SLOT_CODES,
)
from app.auth.applicant import ApplicantSessionContext
from app.config import Settings
from app.documents.keys import load_keyring
from app.documents.malware import ScanResult
from app.documents.store import EncryptedObjectStore
from app.identity import AuthenticatedIdentity
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity


APPLICATION_A = UUID("83000000-0000-4000-8000-000000000001")
APPLICATION_B = UUID("83000000-0000-4000-8000-000000000002")
ROOT = Path(__file__).resolve().parents[1]


class CleanScanner:
    def scan(self, _source: Path) -> ScanResult:
        return ScanResult("synthetic", "CLEAN", datetime.now(UTC))


def _pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def _session(application_id: UUID) -> ApplicantSessionContext:
    return ApplicantSessionContext(
        application_id,
        bytes(32),
        datetime.now(UTC) + timedelta(minutes=30),
        datetime.now(UTC) + timedelta(hours=24),
    )


def _service(tmp_path: Path):  # type: ignore[no-untyped-def]
    credential = tmp_path / "k.json"
    credential.write_text(
        json.dumps(
            {
                "active_key_version": 1,
                "keys": {"1": base64.b64encode(bytes(range(32))).decode("ascii")},
            }
        ),
        encoding="utf-8",
    )
    os.chmod(credential, 0o600)
    repository = DocumentSlotRepository()
    service = ApplicantDocumentService(
        repository,
        EncryptedObjectStore(tmp_path / "objects", load_keyring(credential)),
        CleanScanner(),
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(_pdf())

    def accepted(application_id: UUID, code: str, label: str):  # type: ignore[no-untyped-def]
        slot = repository.add_slot(application_id, code, label, required=True)
        slot = repository.open_slot(application_id, slot.slot_id, "MISSING", "admin", "Missing")
        version = service.upload(
            _session(application_id), slot.slot_id, slot.row_version,
            source, f"{code}.pdf", "application/pdf",
        )
        repository.accept(version.version_id, "admin")
        return slot, version

    slot_a, version_a = accepted(APPLICATION_A, "CV", "Curriculum vitae")
    _slot_b, version_b = accepted(APPLICATION_B, "CV", "Other curriculum vitae")
    repository.add_slot(
        APPLICATION_A,
        "REFERENCE",
        "Confidential referee material",
        required=False,
        applicant_visible=False,
        classification="CONFIDENTIAL_RECOMMENDATION",
        document_type="RECOMMENDATION_LETTER",
        recommendation_linked=True,
    )
    return service, slot_a, version_a, version_b


def test_internal_document_access_is_application_scoped_read_only_and_audited(
    tmp_path: Path,
) -> None:
    """Break caught: a reviewer could guess another dossier or infer confidential material."""
    service, slot, version, other_version = _service(tmp_path)

    listed = service.internal_documents(
        APPLICATION_A, actor="cloudflare:reviewer", actor_group=INTERNAL_GROUPS.trustees
    )
    payload = service.internal_download(
        APPLICATION_A,
        version.version_id,
        actor="cloudflare:reviewer",
        actor_group=INTERNAL_GROUPS.trustees,
        purpose="VIEW",
    )
    guessed = service.internal_download(
        APPLICATION_A,
        other_version.version_id,
        actor="cloudflare:reviewer",
        actor_group=INTERNAL_GROUPS.trustees,
        purpose="VIEW",
    )

    assert [(item.slot_id, item.version_id, item.label) for item in listed] == [
        (slot.slot_id, version.version_id, "Curriculum vitae")
    ]
    assert payload == _pdf()
    assert guessed is None
    assert [(event.purpose, event.outcome) for event in service.access_events] == [
        ("VIEW", "REQUESTED"),
        ("VIEW", "SUCCEEDED"),
        ("VIEW", "REQUESTED"),
        ("VIEW", "FAILED"),
    ]
    package = service.internal_package(
        APPLICATION_A,
        actor="cloudflare:reviewer",
        actor_group=INTERNAL_GROUPS.trustees,
    )
    assert package is not None
    assert len(PdfReader(io.BytesIO(package)).pages) == 1
    assert "Confidential referee material" not in repr(listed)


def _identity(group: str) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        Identity("cloudflare:reviewer", "reviewer@example.test", "Reviewer"),
        frozenset({group}),
    )


def test_internal_document_routes_offer_view_download_and_package_with_neutral_denials(
    tmp_path: Path,
) -> None:
    """Break caught: document buttons could bypass role or application-object authorization."""
    service, slot, version, other_version = _service(tmp_path)
    application = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: _identity(INTERNAL_GROUPS.administrators),
        applicant_approval_service=ApplicantApprovalService(),
        applicant_document_service=service,
    )
    with TestClient(application, base_url="https://localhost") as client:
        listing = client.get(f"/api/internal/applicants/{APPLICATION_A}/documents")
        viewed = client.get(
            f"/api/internal/applicants/{APPLICATION_A}/documents/{version.version_id}/view"
        )
        downloaded = client.get(
            f"/api/internal/applicants/{APPLICATION_A}/documents/{version.version_id}/download"
        )
        package = client.get(f"/api/internal/applicants/{APPLICATION_A}/documents/package/view")
        guessed = client.get(
            f"/api/internal/applicants/{APPLICATION_A}/documents/{other_version.version_id}/view"
        )

    assert listing.status_code == 200
    assert listing.json() == {
        "documents": [
            {
                "slotId": str(slot.slot_id),
                "versionId": str(version.version_id),
                "code": "CV",
                "label": "Curriculum vitae",
                "versionNumber": 1,
                "status": "ACCEPTED",
            }
        ],
        "packageAvailable": True,
    }
    assert viewed.status_code == 200
    assert viewed.headers["content-disposition"] == 'inline; filename="document.pdf"'
    assert downloaded.headers["content-disposition"] == 'attachment; filename="document.pdf"'
    assert package.status_code == 200
    assert guessed.status_code == 404
    assert guessed.json() == {"message": "The document is unavailable."}


def test_internal_review_artifact_is_category_scoped_allowlisted_and_audited(
    tmp_path: Path,
) -> None:
    """Break caught: a category button could expose a full dossier or an arbitrary document."""
    service, _slot, _version, _other_version = _service(tmp_path)
    repository = service._repository
    source = tmp_path / "source.pdf"
    artifact_pdf = _pdf() + b"\n% reviewed artifact\n"
    source.write_bytes(artifact_pdf)
    artifact_slot = repository.add_slot(
        APPLICATION_A,
        REVIEW_ARTIFACT_SLOT_CODES["application"],
        "Reviewed fellowship application",
        required=False,
        document_type="RESEARCH_PLAN",
    )
    artifact_slot = repository.open_slot(
        APPLICATION_A, artifact_slot.slot_id, "MISSING", "admin", "Reviewed extraction"
    )
    artifact_version = service.upload(
        _session(APPLICATION_A), artifact_slot.slot_id, artifact_slot.row_version,
        source, "application.pdf", "application/pdf",
    )
    repository.accept(artifact_version.version_id, "admin")

    listed = service.internal_review_artifacts(
        APPLICATION_A, actor="cloudflare:reviewer", actor_group=INTERNAL_GROUPS.trustees
    )
    payload = service.internal_review_artifact(
        APPLICATION_A, "application",
        actor="cloudflare:reviewer", actor_group=INTERNAL_GROUPS.trustees,
    )

    assert [(item.category, item.version_id) for item in listed] == [
        ("application", artifact_version.version_id)
    ]
    assert payload == artifact_pdf
    assert [(event.purpose, event.outcome) for event in service.access_events[-2:]] == [
        ("VIEW", "REQUESTED"),
        ("VIEW", "SUCCEEDED"),
    ]
    assert service.internal_review_artifact(
        APPLICATION_A, "curriculum",
        actor="cloudflare:reviewer", actor_group=INTERNAL_GROUPS.trustees,
    ) is None
    with pytest.raises(ValueError, match="category"):
        service.internal_review_artifact(
            APPLICATION_A, "recommendations",
            actor="cloudflare:reviewer", actor_group=INTERNAL_GROUPS.trustees,
        )
    assert [(event.version_id, event.outcome) for event in service.access_events[-4:]] == [
        (None, "REQUESTED"), (None, "FAILED"),
        (None, "REQUESTED"), (None, "FAILED"),
    ]


def test_internal_review_artifact_route_lists_availability_and_serves_only_category_pdf(
    tmp_path: Path,
) -> None:
    """Break caught: modal links could embed a package or expose a non-allowlisted category."""
    service, _slot, _version, _other_version = _service(tmp_path)
    application = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: _identity(INTERNAL_GROUPS.administrators),
        applicant_approval_service=ApplicantApprovalService(),
        applicant_document_service=service,
    )
    with TestClient(application, base_url="https://localhost") as client:
        listing = client.get(f"/api/internal/applicants/{APPLICATION_A}/review-artifacts")
        missing = client.get(
            f"/api/internal/applicants/{APPLICATION_A}/review-artifacts/application/view"
        )
        rejected = client.get(
            f"/api/internal/applicants/{APPLICATION_A}/review-artifacts/recommendations/view"
        )

    assert listing.status_code == 200
    assert listing.json() == {"available": []}
    assert missing.status_code == 404
    assert rejected.status_code == 404
    assert missing.json() == rejected.json() == {"message": "The document is unavailable."}


def test_internal_document_sql_release_is_procedure_only_scoped_and_audited() -> None:
    """Break caught: production access could expose recommendations or skip outcome audit."""
    migration = (
        ROOT / "database" / "migrations" / "026_internal_document_access.sql"
    ).read_text(encoding="utf-8")
    validator = (
        ROOT / "database" / "tests" / "026_validate_internal_document_access.sql"
    ).read_text(encoding="utf-8")

    for procedure in (
        "ListInternalApplicantDocuments",
        "GetInternalApplicantDocument",
        "RecordInternalDocumentAccessOutcome",
    ):
        assert f"PROCEDURE dbo.{procedure}" in migration
        assert f"GRANT EXECUTE ON dbo.{procedure} TO EHFApplicationRuntime" in migration
    for exclusion in (
        "slot_row.ApplicantVisible = 1",
        "version_row.Classification = ''APPLICANT_VISIBLE''",
        "document_row.DocumentType <> ''RECOMMENDATION_LETTER''",
        "FROM dbo.Recommendation AS recommendation_row",
    ):
        assert exclusion in migration
    assert "submission_row.SubmissionStatus = ''ACCEPTED''" in migration
    assert "pending_submission.SubmissionStatus = ''PENDING''" in migration
    assert "EXEC dbo.RegisterApplicantDocumentSubmission" in validator
    assert "@DocumentVersionId=@PendingVersionId" in validator
    assert "SubmissionStatus='PENDING'" in validator
    assert "EXEC dbo.ReviewApplicantDocumentSubmission" in validator
    assert "Classification='UNREVIEWED'" in validator
    assert "INTERNAL_DOCUMENT_ACCESS_REQUESTED" in migration
    assert "INTERNAL_DOCUMENT_ACCESS_SUCCEEDED" in migration
    assert "INTERNAL_DOCUMENT_ACCESS_FAILED" in migration
    assert "EXECUTE AS USER = N'ehf_app'" in validator
    assert "PASS 026 internal document access" in validator


def test_document_access_audit_purpose_is_allowlisted_by_a_followup_release() -> None:
    """Break caught: a clean database could reject document-access audit payloads."""
    migration = (
        ROOT / "database" / "migrations" / "027_internal_document_audit_payload.sql"
    ).read_text(encoding="utf-8")
    validator = (
        ROOT / "database" / "tests" / "027_validate_internal_document_audit_payload.sql"
    ).read_text(encoding="utf-8")

    assert "ALTER FUNCTION dbo.IsAuditPayloadKeyProhibited" in migration
    assert "N''purpose''" in migration
    assert "IsAuditPayloadKeyProhibited(N'purpose')" in validator
    assert "IsAuditPayloadKeyProhibited(N'email')" in validator
    assert "PASS 027 internal document audit payload" in validator


def test_internal_review_artifact_sql_release_is_append_only_and_procedure_scoped() -> None:
    """Break caught: derived PDFs could lose provenance or become directly queryable by runtime."""
    migration = (
        ROOT / "database" / "migrations" / "033_internal_review_artifacts.sql"
    ).read_text(encoding="utf-8")
    validator = (
        ROOT / "database" / "tests" / "033_validate_internal_review_artifacts.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE dbo.InternalReviewArtifactProvenance" in migration
    assert "CREATE TRIGGER dbo.TR_InternalReviewArtifactProvenance_AppendOnly" in migration
    assert "INSTEAD OF UPDATE, DELETE" in migration
    for category in ("APPLICATION", "CURRICULUM", "PUBLICATIONS"):
        assert category in migration
    for procedure in (
        "ListInternalReviewArtifacts",
        "GetInternalReviewArtifact",
        "RecordInternalReviewArtifactFailure",
    ):
        assert f"PROCEDURE dbo.{procedure}" in migration
        assert f"GRANT EXECUTE ON dbo.{procedure} TO EHFApplicationRuntime" in migration
    assert (
        "DENY SELECT, INSERT, UPDATE, DELETE ON dbo.InternalReviewArtifactProvenance "
        "TO EHFApplicationRuntime"
    ) in migration
    assert "DocumentType <> ''RECOMMENDATION_LETTER''" in migration
    assert "ALTER FUNCTION dbo.IsAuditPayloadKeyProhibited" in migration
    assert "N''category''" in migration
    assert migration.count("slot_row.SlotCode = CASE provenance_row.Category") == 2
    assert migration.count("document_row.DocumentType = CASE provenance_row.Category") == 2
    assert "SourcePlaintextSha256 binary(32) NOT NULL" in migration
    assert "FirstPage int NOT NULL" in migration and "LastPage int NOT NULL" in migration
    assert "PASS 033 internal review artifacts" in validator
    assert "IsAuditPayloadKeyProhibited(N'category')" in validator
    assert "EXEC dbo.GetInternalReviewArtifact" in validator
    assert "EXEC dbo.RecordInternalReviewArtifactFailure" in validator
