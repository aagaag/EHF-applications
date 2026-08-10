"""Synthetic, behavior-first tests for the 2026 import coordinator."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from app.importer.model import SourceInventory, SourceOccurrence
from app.importer.register import RegisterApplicant
from app.importer.run import (
    ImportMode,
    ImportRequest,
    ImportedDocument,
    execute_import,
)
from app.importer.report import write_exception_report


class MemoryRepository:
    def __init__(self) -> None:
        self.completed: dict[str, str] = {}
        self.applications: dict[str, str] = {}
        self.rows: list[tuple[str, int]] = []
        self.occurrences: list[tuple[str, str, str]] = []
        self.documents: list[ImportedDocument] = []
        self.content_versions: dict[tuple[str, str], str] = {}
        self.runs: list[tuple[str, str]] = []
        self.call_occurrences: list[tuple[str, str]] = []

    def completed_run(self, fingerprint: str) -> str | None:
        return self.completed.get(fingerprint)

    def start_run(self, fingerprint: str) -> str:
        run_id = f"run-{len(self.runs) + 1}"
        self.runs.append((run_id, fingerprint))
        return run_id

    @contextmanager
    def applicant_transaction(self):
        before = (
            len(self.rows),
            len(self.occurrences),
            len(self.documents),
            dict(self.applications),
            dict(self.content_versions),
            len(self.call_occurrences),
        )
        try:
            yield
        except Exception:
            del self.rows[before[0] :]
            del self.occurrences[before[1] :]
            del self.documents[before[2] :]
            self.applications = before[3]
            self.content_versions = before[4]
            del self.call_occurrences[before[5] :]
            raise

    def application_for(self, applicant: RegisterApplicant, source_row_hash: str) -> str:
        return self.applications.setdefault(source_row_hash, str(uuid4()))

    def record_row(self, run_id: str, row_number: int, application_id: str, source_row_hash: str) -> str:
        self.rows.append((run_id, row_number))
        return f"row-{run_id}-{row_number}"

    def prepare_document(self, application_id: str, occurrence: SourceOccurrence, document_type: str) -> ImportedDocument:
        return ImportedDocument(
            application_id=application_id,
            document_id=uuid4(),
            version_id=uuid4(),
            object_id=uuid4(),
            slot_code=occurrence.relative_path,
            document_type=document_type,
            classification="UNREVIEWED",
            source_locator_hash=occurrence.relative_path,
            source_content_hash=occurrence.sha256,
        )

    def existing_version_for_content(self, application_id: str, source_content_hash: str) -> str | None:
        return self.content_versions.get((application_id, source_content_hash))

    def record_document(self, document: ImportedDocument, stored: object) -> str:
        del stored
        self.documents.append(document)
        version = f"version-{len(self.documents)}"
        self.content_versions[(document.application_id, document.source_content_hash)] = version
        return version

    def record_occurrence(
        self,
        run_id: str,
        row_id: str,
        application_id: str,
        occurrence: SourceOccurrence,
        document_version_id: str | None,
        disposition: str,
    ) -> None:
        self.occurrences.append((run_id, occurrence.relative_path, disposition))

    def record_exception(self, run_id: str, row_id: str | None, code: str) -> None:
        del run_id, row_id, code

    def record_call_occurrence(self, run_id: str, occurrence: SourceOccurrence) -> None:
        self.call_occurrences.append((run_id, occurrence.relative_path))

    def complete_run(self, run_id: str, fingerprint: str) -> None:
        self.completed[fingerprint] = run_id

    def fail_run(self, run_id: str) -> None:
        del run_id


class MemoryObjectIngestor:
    def __init__(self) -> None:
        self.stored: list[ImportedDocument] = []

    def ingest(self, source: Path, document: ImportedDocument, register):  # type: ignore[no-untyped-def]
        del source
        register(document)
        self.stored.append(document)
        return document

    def discard(self, document: ImportedDocument) -> None:
        self.stored.remove(document)


def applicant(name: str) -> RegisterApplicant:
    return RegisterApplicant(
        applicant_name=name,
        degree="MD",
        age_observation=30,
        academic_age_observation=5.0,
        gender="X",
        first_author_papers=1,
        last_author_papers=2,
        total_papers=3,
        h_index=4,
        total_citations=5,
        orcid=None,
        google_scholar_citations=6,
        identity_certainty="verified",
    )


def request(tmp_path: Path, *, source_bytes: bytes = b"first synthetic source") -> ImportRequest:
    source_root = tmp_path / "source"
    folder = source_root / "Synthetic Alpha"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cv.pdf").write_bytes(source_bytes)
    occurrence = SourceOccurrence(
        relative_path="Synthetic Alpha/cv.pdf",
        sha256=__import__("hashlib").sha256(source_bytes).hexdigest(),
        byte_size=len(source_bytes),
        is_pdf=True,
        is_internal=False,
    )
    return ImportRequest(
        call_id="00000000-0000-0000-0000-000000000101",
        importer_version="2026.1",
        register_bytes=b"synthetic register bytes",
        applicants=(applicant("Synthetic Alpha"),),
        inventory=SourceInventory(source_root, ("Synthetic Alpha",), (occurrence,), ()),
        identity_parts={"Synthetic Alpha": ("Synthetic", "Alpha")},
        expected_applicants=1,
    )


def test_plan_only_is_the_default_and_never_writes(tmp_path: Path) -> None:
    """Break caught: an operator preview could create records before explicit Apply."""
    repository = MemoryRepository()

    result = execute_import(request(tmp_path), repository, MemoryObjectIngestor())

    assert result.mode is ImportMode.PLAN_ONLY
    assert result.application_count == 1
    assert repository.runs == []
    assert repository.applications == {}


def test_identical_completed_import_reuses_the_same_run_without_duplicates(tmp_path: Path) -> None:
    """Break caught: repeating the same source could create duplicate applications or versions."""
    repository = MemoryRepository()
    objects = MemoryObjectIngestor()
    first = execute_import(request(tmp_path), repository, objects, mode=ImportMode.APPLY)
    second = execute_import(request(tmp_path), repository, objects, mode=ImportMode.APPLY)

    assert first.run_id == second.run_id
    assert second.reused_completed_run is True
    assert len(repository.runs) == 1
    assert len(repository.applications) == 1
    assert len(repository.documents) == 1
    assert repository.documents[0].classification == "UNREVIEWED"


def test_changed_bytes_at_the_same_locator_create_a_new_run_not_a_duplicate_application(
    tmp_path: Path,
) -> None:
    """Break caught: source replacement could duplicate the applicant instead of recording a new version."""
    repository = MemoryRepository()
    objects = MemoryObjectIngestor()
    first = execute_import(request(tmp_path / "one"), repository, objects, mode=ImportMode.APPLY)
    second = execute_import(
        request(tmp_path / "two", source_bytes=b"changed synthetic source"),
        repository,
        objects,
        mode=ImportMode.APPLY,
    )

    assert first.run_id != second.run_id
    assert len(repository.applications) == 1
    assert len(repository.documents) == 2


def test_added_source_occurrence_is_accounted_for_in_a_new_manifest(tmp_path: Path) -> None:
    """Break caught: a newly added file could be invisible to the audit trail."""
    repository = MemoryRepository()
    objects = MemoryObjectIngestor()
    first_request = request(tmp_path / "one")
    execute_import(first_request, repository, objects, mode=ImportMode.APPLY)
    source_root = tmp_path / "two" / "source"
    folder = source_root / "Synthetic Alpha"
    folder.mkdir(parents=True)
    first = SourceOccurrence("Synthetic Alpha/cv.pdf", "a" * 64, 10, True, False)
    second = SourceOccurrence("Synthetic Alpha/plan.pdf", "b" * 64, 11, True, False)
    (folder / "cv.pdf").write_bytes(b"first file")
    (folder / "plan.pdf").write_bytes(b"second file")
    second_request = replace(
        first_request,
        inventory=SourceInventory(source_root, ("Synthetic Alpha",), (first, second), ()),
    )

    result = execute_import(second_request, repository, objects, mode=ImportMode.APPLY)

    assert result.reused_completed_run is False
    assert len(repository.occurrences) == 3
    assert len(repository.documents) == 3


def test_duplicate_content_within_one_application_reuses_the_version(tmp_path: Path) -> None:
    import_request = request(tmp_path)
    first = import_request.inventory.occurrences[0]
    duplicate_path = import_request.inventory.source_root / "Synthetic Alpha" / "copy.pdf"
    duplicate_path.write_bytes((import_request.inventory.source_root / first.relative_path).read_bytes())
    duplicate = SourceOccurrence(
        "Synthetic Alpha/copy.pdf", first.sha256, first.byte_size, True, False
    )
    import_request = replace(
        import_request,
        inventory=replace(
            import_request.inventory,
            occurrences=(first, duplicate),
        ),
    )
    repository = MemoryRepository()

    execute_import(import_request, repository, MemoryObjectIngestor(), mode=ImportMode.APPLY)

    assert len(repository.documents) == 1
    assert len(repository.occurrences) == 2


def test_call_level_internal_occurrence_is_persisted_as_reviewed_exclusion(tmp_path: Path) -> None:
    import_request = request(tmp_path)
    internal_path = import_request.inventory.source_root / "register.docx"
    internal_path.write_bytes(b"internal register")
    internal = SourceOccurrence(
        "register.docx",
        __import__("hashlib").sha256(b"internal register").hexdigest(),
        len(b"internal register"),
        False,
        True,
    )
    import_request = replace(
        import_request,
        inventory=replace(
            import_request.inventory,
            occurrences=(*import_request.inventory.occurrences, internal),
        ),
    )
    repository = MemoryRepository()

    execute_import(import_request, repository, MemoryObjectIngestor(), mode=ImportMode.APPLY)

    assert len(repository.call_occurrences) == 1


def test_exception_report_uses_short_internal_ids_without_source_names_or_document_text(
    tmp_path: Path,
) -> None:
    """Break caught: a review report could expose applicant names, paths, or document contents."""
    import_request = request(tmp_path)
    source_file = import_request.inventory.source_root / "Synthetic Alpha" / "notes.txt"
    source_file.write_text("synthetic confidential text", encoding="utf-8")
    non_pdf = SourceOccurrence(
        "Synthetic Alpha/notes.txt",
        __import__("hashlib").sha256(source_file.read_bytes()).hexdigest(),
        source_file.stat().st_size,
        False,
        False,
    )
    result = execute_import(
        replace(import_request, inventory=replace(import_request.inventory, occurrences=(*import_request.inventory.occurrences, non_pdf))),
        MemoryRepository(),
        MemoryObjectIngestor(),
        mode=ImportMode.APPLY,
    )

    html_path, csv_path = write_exception_report(result, tmp_path / "report")

    html = html_path.read_text(encoding="utf-8")
    csv = csv_path.read_text(encoding="utf-8")
    assert "EHF-IMP-0001" in html
    assert "Synthetic Alpha" not in html + csv
    assert "cv.pdf" not in html + csv
    assert "exception_count" in csv
