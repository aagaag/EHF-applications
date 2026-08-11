from __future__ import annotations

import base64
import io
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pypdf import PdfWriter

from app.applicant.documents import (
    ApplicantDocumentService,
    DocumentSlotRepository,
    DocumentUnavailable,
    DocumentUploadRejected,
    REQUIRED_SLOT_CODES,
)
from app.auth.applicant import ApplicantSessionContext
from app.documents.keys import load_keyring
from app.documents.malware import MalwareDetectedError, MalwareUnavailableError, ScanResult
from app.documents.store import EncryptedObjectStore


APPLICATION_A = UUID("80000000-0000-4000-8000-000000000001")
APPLICATION_B = UUID("80000000-0000-4000-8000-000000000002")


def _pdf(path: Path, *, active: bool = False, encrypted: bool = False) -> Path:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": path.stem})
    if active:
        writer.add_js("app.alert('synthetic')")
    if encrypted:
        writer.encrypt("synthetic")
    stream = io.BytesIO()
    writer.write(stream)
    path.write_bytes(stream.getvalue())
    return path


class CleanScanner:
    def scan(self, _source: Path) -> ScanResult:
        return ScanResult("synthetic", "CLEAN", datetime.now(UTC))


class BrokenScanner:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def scan(self, _source: Path) -> ScanResult:
        raise self.error


def _store(tmp_path: Path) -> EncryptedObjectStore:
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
    return EncryptedObjectStore(tmp_path / "objects", load_keyring(credential))


def _context(application: UUID) -> ApplicantSessionContext:
    return ApplicantSessionContext(
        application,
        bytes(32),
        datetime.now(UTC) + timedelta(minutes=30),
        datetime.now(UTC) + timedelta(hours=24),
    )


def test_required_slots_are_exact_and_recommendations_are_not_applicant_slots() -> None:
    """Break caught: a required document could vanish or a recommendation slot could appear."""
    assert REQUIRED_SLOT_CODES == (
        "CV",
        "PUBLICATION_LIST",
        "RESEARCH_PLAN",
        "COVER_LETTER_CAREER_PLAN",
        "FUTURE_UZH_EMPLOYMENT_PROOF",
    )
    assert all("RECOMMEND" not in code for code in REQUIRED_SLOT_CODES)


def test_only_exact_open_session_slot_accepts_a_clean_pdf(tmp_path: Path) -> None:
    """Break caught: a closed, stale, or other-applicant slot could accept an upload."""
    repository = DocumentSlotRepository()
    slot = repository.add_slot(APPLICATION_A, "CV", "Curriculum vitae", required=True)
    service = ApplicantDocumentService(repository, _store(tmp_path), CleanScanner())
    source = _pdf(tmp_path / "cv.pdf")

    with pytest.raises(DocumentUnavailable):
        service.upload(_context(APPLICATION_A), slot.slot_id, 1, source, "cv.pdf", "application/pdf")
    opened = repository.open_slot(APPLICATION_A, slot.slot_id, "MISSING", "admin", "Missing CV")
    with pytest.raises(DocumentUnavailable):
        service.upload(_context(APPLICATION_B), slot.slot_id, opened.row_version, source, "cv.pdf", "application/pdf")
    with pytest.raises(DocumentUnavailable):
        service.upload(_context(APPLICATION_A), slot.slot_id, opened.row_version - 1, source, "cv.pdf", "application/pdf")

    version = service.upload(
        _context(APPLICATION_A),
        slot.slot_id,
        opened.row_version,
        source,
        "cv.pdf",
        "application/pdf",
    )

    assert version.status == "PENDING"
    assert version.version_number == 1
    assert version.object_record.byte_size == source.stat().st_size


@pytest.mark.parametrize(
    ("filename", "media_type", "active", "encrypted"),
    [
        ("cv.txt", "application/pdf", False, False),
        ("cv.pdf", "text/plain", False, False),
        ("cv.pdf", "application/pdf", True, False),
        ("cv.pdf", "application/pdf", False, True),
    ],
)
def test_invalid_pdf_is_rejected_without_registering_a_version(
    tmp_path: Path, filename: str, media_type: str, active: bool, encrypted: bool
) -> None:
    """Break caught: unsafe PDF content could become a document version."""
    repository = DocumentSlotRepository()
    slot = repository.add_slot(APPLICATION_A, "CV", "Curriculum vitae", required=True)
    opened = repository.open_slot(APPLICATION_A, slot.slot_id, "MISSING", "admin", "Missing")
    service = ApplicantDocumentService(repository, _store(tmp_path), CleanScanner())
    source = _pdf(tmp_path / "source.pdf", active=active, encrypted=encrypted)

    with pytest.raises(DocumentUploadRejected):
        service.upload(_context(APPLICATION_A), slot.slot_id, opened.row_version, source, filename, media_type)

    assert repository.versions(slot.slot_id) == ()


@pytest.mark.parametrize(
    "error",
    [
        MalwareDetectedError("synthetic detection"),
        MalwareUnavailableError("synthetic outage"),
    ],
)
def test_malware_detection_or_outage_fails_closed(tmp_path: Path, error: Exception) -> None:
    """Break caught: scanner failure could promote an unscanned applicant document."""
    repository = DocumentSlotRepository()
    slot = repository.add_slot(APPLICATION_A, "CV", "Curriculum vitae", required=True)
    opened = repository.open_slot(APPLICATION_A, slot.slot_id, "MISSING", "admin", "Missing")
    service = ApplicantDocumentService(repository, _store(tmp_path), BrokenScanner(error))

    with pytest.raises(DocumentUploadRejected):
        service.upload(
            _context(APPLICATION_A),
            slot.slot_id,
            opened.row_version,
            _pdf(tmp_path / "clean.pdf"),
            "clean.pdf",
            "application/pdf",
        )

    assert repository.versions(slot.slot_id) == ()


def test_replacement_preserves_original_and_supports_reject_accept_restore(tmp_path: Path) -> None:
    """Break caught: replacing a file could overwrite history or activate before review."""
    repository = DocumentSlotRepository()
    slot = repository.add_slot(APPLICATION_A, "CV", "Curriculum vitae", required=True)
    service = ApplicantDocumentService(repository, _store(tmp_path), CleanScanner())
    opened = repository.open_slot(APPLICATION_A, slot.slot_id, "MISSING", "admin", "Missing")
    first = service.upload(
        _context(APPLICATION_A), slot.slot_id, opened.row_version,
        _pdf(tmp_path / "first.pdf"), "first.pdf", "application/pdf",
    )
    repository.accept(first.version_id, "admin")
    active_first = repository.slot(slot.slot_id).active_version_id
    replacement_slot = repository.open_slot(
        APPLICATION_A, slot.slot_id, "REPLACEMENT", "admin", "Updated CV requested"
    )
    second = service.upload(
        _context(APPLICATION_A), slot.slot_id, replacement_slot.row_version,
        _pdf(tmp_path / "second.pdf"), "second.pdf", "application/pdf",
    )

    assert repository.slot(slot.slot_id).active_version_id == active_first
    repository.reject(second.version_id, "admin", "Wrong document")
    assert repository.slot(slot.slot_id).active_version_id == active_first
    third_slot = repository.open_slot(
        APPLICATION_A, slot.slot_id, "REPLACEMENT", "admin", "Try again"
    )
    third = service.upload(
        _context(APPLICATION_A), slot.slot_id, third_slot.row_version,
        _pdf(tmp_path / "third.pdf"), "third.pdf", "application/pdf",
    )
    repository.accept(third.version_id, "admin")
    assert repository.slot(slot.slot_id).active_version_id == third.version_id
    repository.restore(slot.slot_id, first.version_id, "admin")
    assert repository.slot(slot.slot_id).active_version_id == first.version_id
    assert [item.version_number for item in repository.versions(slot.slot_id)] == [1, 2, 3]
