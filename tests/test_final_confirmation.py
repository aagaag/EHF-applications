from __future__ import annotations

import base64
import io
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pypdf import PdfWriter

from app.applicant.confirmations import SectionConfirmationService
from app.applicant.documents import ApplicantDocumentService, DocumentSlotRepository
from app.applicant.drafts import DraftLocked, InMemoryDraftRepository
from app.applicant.finalize import FinalizationBlocked, FinalizationService
from app.applicant.review import ApplicantReviewService
from app.auth.applicant import ApplicantSessionContext
from app.documents.keys import load_keyring
from app.documents.malware import ScanResult
from app.documents.store import EncryptedObjectStore


APPLICATION = UUID("90000000-0000-4000-8000-000000000001")


class CleanScanner:
    def scan(self, _source: Path) -> ScanResult:
        return ScanResult("synthetic", "CLEAN", datetime.now(UTC))


def _session() -> ApplicantSessionContext:
    return ApplicantSessionContext(
        APPLICATION,
        bytes(32),
        datetime.now(UTC) + timedelta(minutes=30),
        datetime.now(UTC) + timedelta(hours=24),
    )


def _pdf(path: Path) -> Path:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    stream = io.BytesIO()
    writer.write(stream)
    path.write_bytes(stream.getvalue())
    return path


def _services(tmp_path: Path) -> tuple[
    FinalizationService,
    ApplicantReviewService,
    InMemoryDraftRepository,
    DocumentSlotRepository,
]:
    drafts = InMemoryDraftRepository()
    confirmations = SectionConfirmationService()
    review = ApplicantReviewService(drafts, confirmations)
    slots = DocumentSlotRepository()
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
    documents = ApplicantDocumentService(
        slots,
        EncryptedObjectStore(tmp_path / "objects", load_keyring(credential)),
        CleanScanner(),
    )
    return FinalizationService(review, drafts, confirmations, slots), review, drafts, slots


def _complete_sections(review: ApplicantReviewService) -> None:
    values = {
        "identity": {
            "fullName": "Synthetic Complete Applicant",
            "registeredEmail": "complete@example.test",
            "telephone": "+41 00 000 00 00",
            "birthMonth": 1,
            "birthYear": 1990,
        },
        "employment": {
            "institute": "Synthetic UZH Institute",
            "principalInvestigator": "Synthetic PI",
            "positionTitle": "Postdoctoral researcher",
            "postdoctoralEmploymentStatus": "Employed",
            "employmentStartDate": "2025-01-01",
            "employmentEndDate": "2027-12-31",
            "researchArea": "Molecular life sciences",
            "clinicalWorkPercent": 0,
            "firstAuthorDeclaration": True,
        },
        "qualifications": {"degreeCategory": "MD"},
        "publications": {
            "firstAuthorPaperCount": 2,
            "lastAuthorPaperCount": 0,
            "totalPaperCount": 5,
            "hIndex": 3,
            "applicantReportedCitationTotal": 50,
            "noGoogleScholarProfile": True,
            "googleScholarCitationTotal": 50,
        },
        "contribution": {"contributionStatement": "A synthetic scientific contribution."},
    }
    for section, section_values in values.items():
        snapshot = review.save(_session(), section, section_values, None)
        review.confirm(_session(), section, snapshot.row_version)


def _accepted_required_document(
    tmp_path: Path, slots: DocumentSlotRepository
) -> None:
    credential = tmp_path / "doc-k.json"
    credential.write_text(
        json.dumps(
            {
                "active_key_version": 1,
                "keys": {"1": base64.b64encode(bytes(reversed(range(32)))).decode("ascii")},
            }
        ),
        encoding="utf-8",
    )
    os.chmod(credential, 0o600)
    service = ApplicantDocumentService(
        slots,
        EncryptedObjectStore(tmp_path / "doc-objects", load_keyring(credential)),
        CleanScanner(),
    )
    slot = slots.add_slot(APPLICATION, "CV", "Curriculum vitae", required=True)
    opened = slots.open_slot(APPLICATION, slot.slot_id, "MISSING", "admin", "Missing")
    version = service.upload(
        _session(), slot.slot_id, opened.row_version,
        _pdf(tmp_path / "cv.pdf"), "cv.pdf", "application/pdf",
    )
    slots.accept(version.version_id, "admin")


def test_complete_current_manifest_submits_once_and_locks_all_sections(tmp_path: Path) -> None:
    """Break caught: final submission could omit versions, duplicate, or leave edits open."""
    finalization, review, drafts, slots = _services(tmp_path)
    _complete_sections(review)
    _accepted_required_document(tmp_path, slots)

    first = finalization.submit(_session())
    second = finalization.submit(_session())

    assert second == first
    assert len(first.manifest_sha256) == 64
    manifest = json.dumps(first.manifest, sort_keys=True).casefold()
    assert "contribution" in manifest
    assert "cv" in manifest
    for forbidden in ("recommendation", "storagekey", "internal", "security"):
        assert forbidden not in manifest
    with pytest.raises(DraftLocked):
        review.save(_session(), "identity", {"preferredName": "Too late"}, 1)
    assert [event.action for event in finalization.audit_events] == ["FINAL_SUBMISSION"]


def test_missing_or_stale_section_and_unresolved_required_document_block_submission(
    tmp_path: Path,
) -> None:
    """Break caught: an incomplete or changed application could be finalized."""
    finalization, review, _drafts, slots = _services(tmp_path)
    _complete_sections(review)
    identity = review.load(_session(), "identity")
    assert identity is not None
    review.save(_session(), "identity", {"preferredName": "Changed"}, identity.row_version)
    slots.add_slot(APPLICATION, "CV", "Curriculum vitae", required=True)

    with pytest.raises(FinalizationBlocked) as raised:
        finalization.submit(_session())

    assert set(raised.value.unresolved) == {
        "section:identity",
        "document:CV",
    }


def test_pending_required_document_remains_unresolved(tmp_path: Path) -> None:
    """Break caught: a pending upload could satisfy completeness before staff acceptance."""
    finalization, review, _drafts, slots = _services(tmp_path)
    _complete_sections(review)
    slot = slots.add_slot(APPLICATION, "CV", "Curriculum vitae", required=True)
    slots.open_slot(APPLICATION, slot.slot_id, "MISSING", "admin", "Missing")

    with pytest.raises(FinalizationBlocked) as raised:
        finalization.submit(_session())

    assert raised.value.unresolved == ("document:CV",)


def test_open_optional_document_slot_blocks_finalization(tmp_path: Path) -> None:
    """Break caught: an administrator-requested optional upload could remain mutable after submission."""
    finalization, review, _drafts, slots = _services(tmp_path)
    _complete_sections(review)
    _accepted_required_document(tmp_path, slots)
    optional = slots.add_slot(APPLICATION, "ADDITIONAL", "Additional document", required=False)
    slots.open_slot(APPLICATION, optional.slot_id, "MISSING", "admin", "Requested")

    with pytest.raises(FinalizationBlocked) as raised:
        finalization.submit(_session())

    assert raised.value.unresolved == ("document:ADDITIONAL",)
