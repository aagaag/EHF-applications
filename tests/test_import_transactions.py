"""Synthetic failure-boundary tests for the 2026 import coordinator."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.importer.run import ImportBlockedError, ImportExecutionError, ImportMode, execute_import
from tests.test_import_idempotency import MemoryObjectIngestor, MemoryRepository, request


class FailingRepository(MemoryRepository):
    def record_document(self, document, stored):  # type: ignore[no-untyped-def]
        del document, stored
        raise RuntimeError("synthetic database failure")


class ScanFailingIngestor(MemoryObjectIngestor):
    def ingest(self, source, document, register):  # type: ignore[no-untyped-def]
        del source, document, register
        raise RuntimeError("synthetic scanner failure")


class OnceFailingIngestor(MemoryObjectIngestor):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def ingest(self, source, document, register):  # type: ignore[no-untyped-def]
        if not self.failed:
            self.failed = True
            raise RuntimeError("synthetic interruption")
        return super().ingest(source, document, register)


def test_database_failure_after_object_write_rolls_back_the_applicant_and_object(tmp_path: Path) -> None:
    """Break caught: a metadata failure could leave an imported application or encrypted object behind."""
    repository = FailingRepository()
    objects = MemoryObjectIngestor()

    with pytest.raises(ImportExecutionError, match=r"document-registration \(_DocumentRegistrationError\)"):
        execute_import(request(tmp_path), repository, objects, mode=ImportMode.APPLY)

    assert repository.applications == {}
    assert repository.rows == []
    assert repository.occurrences == []
    assert objects.stored == []


def test_nonempty_scan_failure_blocks_import_and_rolls_back_the_occurrence(tmp_path: Path) -> None:
    """Break caught: a non-empty failed document could be omitted from a completed import."""
    repository = MemoryRepository()

    with pytest.raises(ImportExecutionError):
        execute_import(request(tmp_path), repository, ScanFailingIngestor(), mode=ImportMode.APPLY)

    assert repository.documents == []
    assert repository.occurrences == []


def test_empty_legacy_pdf_is_accounted_as_the_only_nonblocking_rejection(tmp_path: Path) -> None:
    repository = MemoryRepository()

    result = execute_import(
        request(tmp_path, source_bytes=b""),
        repository,
        ScanFailingIngestor(),
        mode=ImportMode.APPLY,
    )

    assert result.exception_counts == {"document-ingestion-failed": 1}
    assert repository.occurrences == [(result.run_id, "Synthetic Alpha/cv.pdf", "REJECTED")]


def test_unmatched_folder_blocks_apply_without_creating_a_run(tmp_path: Path) -> None:
    """Break caught: an unmatched source folder could be guessed into an applicant record."""
    import_request = request(tmp_path)
    unmatched = replace(
        import_request,
        inventory=import_request.inventory.__class__(
            import_request.inventory.source_root,
            ("Unmatched Folder",),
            import_request.inventory.occurrences,
            (),
        ),
    )
    repository = MemoryRepository()

    with pytest.raises(ImportBlockedError):
        execute_import(unmatched, repository, MemoryObjectIngestor(), mode=ImportMode.APPLY)

    assert repository.runs == []


def test_duplicate_register_row_blocks_apply_without_coercing_identity(tmp_path: Path) -> None:
    """Break caught: duplicate register rows could silently create two applications."""
    import_request = request(tmp_path)
    duplicate = replace(
        import_request,
        applicants=import_request.applicants * 2,
        expected_applicants=2,
    )

    with pytest.raises(ImportBlockedError):
        execute_import(duplicate, MemoryRepository(), MemoryObjectIngestor(), mode=ImportMode.APPLY)


def test_partial_import_rolls_back_only_the_failed_applicant_transaction(tmp_path: Path) -> None:
    """Break caught: one applicant failure could leave a partial set of their records committed."""
    repository = FailingRepository()

    with pytest.raises(ImportExecutionError):
        execute_import(request(tmp_path), repository, MemoryObjectIngestor(), mode=ImportMode.APPLY)

    assert repository.rows == []
    assert repository.occurrences == []


def test_interrupted_fingerprint_can_be_retried_to_completion(tmp_path: Path) -> None:
    repository = MemoryRepository()
    objects = OnceFailingIngestor()

    with pytest.raises(ImportExecutionError):
        execute_import(request(tmp_path), repository, objects, mode=ImportMode.APPLY)
    result = execute_import(request(tmp_path), repository, objects, mode=ImportMode.APPLY)

    assert result.run_id is not None
    assert len(repository.runs) == 2
