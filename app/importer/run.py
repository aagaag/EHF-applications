"""Fail-closed planning and idempotent execution for the 2026 call import."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from pypdf import PdfReader

from app.documents.keys import load_keyring
from app.documents.malware import ClamDScanner, ScanResult
from app.documents.store import EncryptedObjectStore, ObjectBinding, StoredObjectRecord
from app.documents.validation import ValidatedPdf, validate_pdf
from app.config import Settings
from app.importer.classify import DocumentType, suggest_classification
from app.importer.inventory import inventory_source_tree
from app.importer.match import match_applicants_to_folders
from app.importer.model import SourceInventory, SourceOccurrence
from app.importer.register import RegisterApplicant, parse_register


IMPORTER_VERSION = "2026.3"
CALL_2026_CODE = "EHF-2026"
CALL_2026_DISPLAY_NAME = "Ernst Hadorn Transitional Fellowships 2026"
CALL_2026_DEADLINE_UTC = "2026-07-31T21:59:59"


class ImportMode(StrEnum):
    """The importer never writes unless the caller explicitly selects Apply."""

    PLAN_ONLY = "PLAN_ONLY"
    APPLY = "APPLY"


class ImportBlockedError(RuntimeError):
    """The input cannot be imported without an explicit reviewed correction."""


class ImportExecutionError(RuntimeError):
    """An Apply run failed; diagnostic detail remains in the internal report only."""


class _DocumentRegistrationError(RuntimeError):
    """A database write failed after a document object was prepared."""


def _record_legacy_recommendation(connection: Any, document_id: str, document_type: str) -> None:
    """Make recommendation confidentiality authoritative at import time."""
    if document_type == DocumentType.RECOMMENDATION_LETTER.value:
        connection.execute(
            "INSERT dbo.Recommendation (DocumentId, ArrivalChannel, CreatedByIdentity) "
            "VALUES (?, 'UNKNOWN_LEGACY', 'ISAB01_IMPORT')",
            document_id,
        )


def _legacy_register_snapshot(applicant: RegisterApplicant) -> str:
    """Preserve every register observation without treating it as applicant-confirmed data."""
    return json.dumps(
        {
            field: getattr(applicant, field)
            for field in applicant.__dataclass_fields__
            if field != "applicant_name"
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True, slots=True)
class ImportRequest:
    call_id: str
    importer_version: str
    register_bytes: bytes
    applicants: tuple[RegisterApplicant, ...]
    inventory: SourceInventory
    identity_parts: Mapping[str, tuple[str, str]]
    reviewed_folder_aliases: Mapping[str, str] = field(default_factory=dict)
    expected_applicants: int = 36


@dataclass(frozen=True, slots=True)
class ImportedDocument:
    application_id: str
    document_id: UUID
    version_id: UUID
    object_id: UUID
    slot_code: str
    document_type: str
    classification: str
    source_locator_hash: str
    source_content_hash: str


@dataclass(frozen=True, slots=True)
class PlannedApplicant:
    row_number: int
    applicant: RegisterApplicant
    folder_name: str
    source_row_hash: str
    occurrences: tuple[SourceOccurrence, ...]


@dataclass(frozen=True, slots=True)
class ImportPlan:
    fingerprint: str
    source_manifest_hash: str
    applicants: tuple[PlannedApplicant, ...]
    call_occurrences: tuple[SourceOccurrence, ...]
    exception_counts: Mapping[str, int]

    @property
    def blocked(self) -> bool:
        blocking_codes = {
            "duplicate-register-row",
            "unexpected-applicant-count",
            "source-inventory-issue",
            "unmatched-applicant",
            "ambiguous-folder-match",
            "duplicate-folder-match",
            "unmatched-folder",
            "match-failed",
            "unmatched-source-occurrence",
            "identity-parts-required",
        }
        return any(self.exception_counts.get(code, 0) for code in blocking_codes)


@dataclass(frozen=True, slots=True)
class ImportResult:
    mode: ImportMode
    fingerprint: str
    source_manifest_hash: str
    application_count: int
    run_id: str | None
    reused_completed_run: bool
    exception_counts: Mapping[str, int]


class ImportRepository(Protocol):
    def completed_run(self, fingerprint: str) -> str | None: ...

    def start_run(self, fingerprint: str) -> str: ...

    def applicant_transaction(self) -> AbstractContextManager[None]: ...

    def application_for(self, applicant: RegisterApplicant, source_row_hash: str) -> str: ...

    def record_row(self, run_id: str, row_number: int, application_id: str, source_row_hash: str) -> str: ...

    def prepare_document(
        self, application_id: str, occurrence: SourceOccurrence, document_type: str
    ) -> ImportedDocument: ...

    def existing_version_for_content(self, application_id: str, source_content_hash: str) -> str | None: ...

    def record_document(self, document: ImportedDocument, stored: object) -> str: ...

    def record_occurrence(
        self,
        run_id: str,
        row_id: str,
        application_id: str,
        occurrence: SourceOccurrence,
        document_version_id: str | None,
        disposition: str,
    ) -> None: ...

    def record_exception(self, run_id: str, row_id: str | None, code: str) -> None: ...

    def record_call_occurrence(self, run_id: str, occurrence: SourceOccurrence) -> None: ...

    def complete_run(self, run_id: str, fingerprint: str) -> None: ...

    def fail_run(self, run_id: str) -> None: ...


class ObjectIngestor(Protocol):
    def ingest(
        self,
        source: Path,
        document: ImportedDocument,
        register: Callable[[object], str],
    ) -> object: ...

    def discard(self, stored: object) -> None: ...


@dataclass(frozen=True, slots=True)
class StoredAdmission:
    """The non-plaintext object metadata that can be recorded with a document version."""

    record: StoredObjectRecord
    validation: ValidatedPdf
    scan: ScanResult


class DocumentStoreIngestor:
    """Adapt the approved encrypted object store without exposing filenames in diagnostics."""

    def __init__(self, store: EncryptedObjectStore, scanner: ClamDScanner) -> None:
        self._store = store
        self._scanner = scanner

    def ingest(
        self,
        source: Path,
        document: ImportedDocument,
        register: Callable[[object], str],
    ) -> StoredAdmission:
        validation: ValidatedPdf | None = None
        scan: ScanResult | None = None
        registration_failed = False

        def validator(path: Path) -> ValidatedPdf:
            nonlocal validation
            validation = validate_pdf(
                path,
                declared_filename=source.name,
                declared_media_type="application/pdf",
            )
            return validation

        class ScanCapture:
            def scan(self, path: Path) -> ScanResult:
                nonlocal scan
                scan = self_outer._scanner.scan(path)
                return scan

        self_outer = self

        def register_record(record: StoredObjectRecord) -> str:
            nonlocal registration_failed
            if validation is None or scan is None:
                raise _DocumentRegistrationError("Document admission was incomplete.")
            try:
                return register(StoredAdmission(record, validation, scan))
            except Exception:
                registration_failed = True
                raise

        try:
            record = self._store.ingest_file(
                source,
                ObjectBinding(
                    application_id=UUID(document.application_id),
                    document_id=document.document_id,
                    version_id=document.version_id,
                    object_id=document.object_id,
                ),
                validator=validator,
                scanner=ScanCapture(),
                register=register_record,
            )
        except Exception:
            if registration_failed:
                raise _DocumentRegistrationError("Document metadata registration failed.") from None
            raise
        if validation is None or scan is None:
            raise _DocumentRegistrationError("Document admission was incomplete.")
        return StoredAdmission(record, validation, scan)

    def discard(self, stored: object) -> None:
        if isinstance(stored, StoredAdmission):
            self._store.path_for(stored.record.object_key).unlink(missing_ok=True)


class SqlImportRepository:
    """Root-only SQL writer for an import run; the web runtime remains denied direct table access."""

    def __init__(self, connection: Any, identity_parts: Mapping[str, tuple[str, str]]) -> None:
        self._connection = connection
        self._identity_parts = identity_parts
        self._call_id: str | None = None

    def completed_run(self, fingerprint: str) -> str | None:
        row = self._connection.execute(
            "SELECT CONVERT(varchar(36), ImportRunId) FROM dbo.ImportRun "
            "WHERE FellowshipCallId = ? AND ImportFingerprintSha256 = CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)) "
            "AND RunStatus = 'COMPLETED'",
            self._call_id,
            fingerprint,
        ).fetchone()
        return None if row is None else str(row[0])

    def start_run(self, fingerprint: str) -> str:
        row = self._connection.execute(
            "INSERT dbo.ImportRun (FellowshipCallId, ImportFingerprintSha256, ImporterVersion, RunStatus, StartedByIdentity) "
            "OUTPUT CONVERT(varchar(36), inserted.ImportRunId) "
            "VALUES (?, CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), ?, 'RUNNING', 'ISAB01_IMPORT')",
            self._call_id,
            fingerprint,
            IMPORTER_VERSION,
        ).fetchone()
        if row is None:
            raise RuntimeError("Import run creation failed.")
        return str(row[0])

    def applicant_transaction(self) -> AbstractContextManager[None]:
        return _SqlTransaction(self._connection)

    def application_for(self, applicant: RegisterApplicant, source_row_hash: str) -> str:
        row = self._connection.execute(
            "SELECT TOP (1) CONVERT(varchar(36), application_row.ApplicationId) "
            "FROM dbo.ImportRow AS import_row "
            "JOIN dbo.Application AS application_row ON application_row.ApplicationId = import_row.ApplicationId "
            "JOIN dbo.ImportRun AS import_run ON import_run.ImportRunId = import_row.ImportRunId "
            "WHERE import_run.FellowshipCallId = ? "
            "AND import_row.SourceRowSha256 = CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)) "
            "AND import_row.MatchStatus = 'MATCHED' ORDER BY import_run.StartedAtUtc DESC",
            self._call_id,
            source_row_hash,
        ).fetchone()
        if row is not None:
            return str(row[0])
        given_names, family_name = self._identity_parts[applicant.applicant_name]
        identity_row = self._connection.execute(
            "SELECT TOP (1) CONVERT(varchar(36), application_row.ApplicationId) "
            "FROM dbo.Application AS application_row "
            "JOIN dbo.Applicant AS applicant_row ON applicant_row.ApplicantId = application_row.ApplicantId "
            "WHERE application_row.FellowshipCallId = ? "
            "AND applicant_row.LegalGivenNames = ? AND applicant_row.LegalFamilyName = ?",
            self._call_id,
            given_names,
            family_name,
        ).fetchone()
        if identity_row is not None:
            return str(identity_row[0])
        applicant_id = str(uuid4())
        application_id = str(uuid4())
        self._connection.execute(
            "INSERT dbo.Applicant (ApplicantId, LegalGivenNames, LegalFamilyName, SelfReportedGender) VALUES (?, ?, ?, ?)",
            applicant_id,
            given_names,
            family_name,
            applicant.gender,
        )
        self._connection.execute(
            "INSERT dbo.Application (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus) VALUES (?, ?, ?, 'IMPORTED')",
            application_id,
            self._call_id,
            applicant_id,
        )
        self._connection.execute(
            "INSERT dbo.Bibliometrics (ApplicationId, FirstAuthorPaperCount, LastAuthorPaperCount, TotalPaperCount, GoogleScholarCitationCount) "
            "VALUES (?, ?, ?, ?, ?)",
            application_id,
            applicant.first_author_papers,
            applicant.last_author_papers,
            applicant.total_papers,
            applicant.google_scholar_citations,
        )
        self._connection.execute(
            "INSERT dbo.ApplicationSectionVersion "
            "(ApplicationId, SectionCode, VersionNumber, SnapshotJson, ChangedByIdentity) "
            "VALUES (?, 'LEGACY_REGISTER_OBSERVATIONS', 1, ?, 'ISAB01_IMPORT')",
            application_id,
            _legacy_register_snapshot(applicant),
        )
        return application_id

    def record_row(self, run_id: str, row_number: int, application_id: str, source_row_hash: str) -> str:
        row = self._connection.execute(
            "INSERT dbo.ImportRow (ImportRunId, SourceRowNumber, ApplicationId, SourceRowSha256, MatchStatus) "
            "OUTPUT CONVERT(varchar(36), inserted.ImportRowId) "
            "VALUES (?, ?, ?, CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), 'MATCHED')",
            run_id,
            row_number,
            application_id,
            source_row_hash,
        ).fetchone()
        if row is None:
            raise RuntimeError("Import row creation failed.")
        return str(row[0])

    def prepare_document(
        self, application_id: str, occurrence: SourceOccurrence, document_type: str
    ) -> ImportedDocument:
        locator_hash = hashlib.sha256(occurrence.relative_path.encode("utf-8")).hexdigest()
        slot_code = f"import-{locator_hash[:32]}"
        row = self._connection.execute(
            "SELECT CONVERT(varchar(36), document_row.DocumentId), document_row.DocumentType "
            "FROM dbo.DocumentSlot AS slot_row JOIN dbo.Document AS document_row ON document_row.DocumentSlotId = slot_row.DocumentSlotId "
            "WHERE slot_row.ApplicationId = ? AND slot_row.SlotCode = ?",
            application_id,
            slot_code,
        ).fetchone()
        if row is not None and str(row[1]) != document_type:
            raise RuntimeError("A changed source conflicts with the immutable document type.")
        document_id = UUID(str(row[0])) if row is not None else uuid4()
        return ImportedDocument(
            application_id=application_id,
            document_id=document_id,
            version_id=uuid4(),
            object_id=uuid4(),
            slot_code=slot_code,
            document_type=document_type,
            classification="UNREVIEWED",
            source_locator_hash=locator_hash,
            source_content_hash=occurrence.sha256,
        )

    def existing_version_for_content(
        self, application_id: str, source_content_hash: str
    ) -> str | None:
        row = self._connection.execute(
            "SELECT TOP (1) CONVERT(varchar(36), DocumentVersionId) "
            "FROM dbo.SourceOccurrence WHERE ApplicationId = ? "
            "AND SourceContentSha256 = CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)) "
            "AND DocumentVersionId IS NOT NULL ORDER BY ObservedAtUtc",
            application_id,
            source_content_hash,
        ).fetchone()
        return None if row is None else str(row[0])

    def record_document(self, document: ImportedDocument, stored: object) -> str:
        if not isinstance(stored, StoredAdmission):
            raise RuntimeError("Document admission is invalid.")
        row = self._connection.execute(
            "SELECT CONVERT(varchar(36), DocumentSlotId) FROM dbo.DocumentSlot WHERE ApplicationId = ? AND SlotCode = ?",
            document.application_id,
            document.slot_code,
        ).fetchone()
        if row is None:
            slot_id = str(uuid4())
            self._connection.execute(
                "INSERT dbo.DocumentSlot (DocumentSlotId, ApplicationId, SlotCode, CreatedByIdentity) VALUES (?, ?, ?, 'ISAB01_IMPORT')",
                slot_id,
                document.application_id,
                document.slot_code,
            )
            self._connection.execute(
                "INSERT dbo.Document (DocumentId, DocumentSlotId, DocumentType, CreatedByIdentity) VALUES (?, ?, ?, 'ISAB01_IMPORT')",
                str(document.document_id),
                slot_id,
                document.document_type,
            )
            _record_legacy_recommendation(
                self._connection, str(document.document_id), document.document_type
            )
        else:
            slot_id = str(row[0])
        record = stored.record
        self._connection.execute(
            "INSERT dbo.StoredObject (StoredObjectId, ObjectKey, KeyVersion, EnvelopeVersion, AesGcmNonce, PlaintextSha256, CiphertextSha256, ByteSize, MediaType, PageCount, ScanEngine, ScanSignature, ScannedAtUtc, ScanResult, CreatedByIdentity) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ISAB01_IMPORT')",
            str(document.object_id), record.object_key, record.key_version, record.envelope_version,
            record.nonce, record.plaintext_sha256, record.ciphertext_sha256, record.byte_size,
            stored.validation.media_type, stored.validation.page_count, stored.scan.engine,
            stored.scan.signature, stored.scan.scanned_at_utc, stored.scan.result,
        )
        self._connection.execute(
            "INSERT dbo.DocumentVersion (DocumentVersionId, DocumentId, StoredObjectId, VersionNumber, Classification, CreatedByIdentity) "
            "SELECT ?, ?, ?, ISNULL(MAX(VersionNumber), 0) + 1, 'UNREVIEWED', 'ISAB01_IMPORT' "
            "FROM dbo.DocumentVersion WHERE DocumentId = ?",
            str(document.version_id), str(document.document_id), str(document.object_id), str(document.document_id),
        )
        self._connection.execute(
            "UPDATE dbo.DocumentSlot SET ActiveDocumentVersionId = ? WHERE DocumentSlotId = ?",
            str(document.version_id),
            slot_id,
        )
        return str(document.version_id)

    def record_occurrence(self, run_id: str, row_id: str, application_id: str, occurrence: SourceOccurrence, document_version_id: str | None, disposition: str) -> None:
        self._connection.execute(
            "INSERT dbo.SourceOccurrence (ImportRunId, ImportRowId, ApplicationId, DocumentVersionId, SourceLocatorSha256, SourceContentSha256, SourceByteSize, SourceMediaType, ImportDisposition) "
            "VALUES (?, ?, ?, ?, CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), ?, ?, ?)",
            run_id, row_id, application_id, document_version_id,
            hashlib.sha256(occurrence.relative_path.encode("utf-8")).hexdigest(), occurrence.sha256,
            occurrence.byte_size, "application/pdf" if occurrence.is_pdf else None, disposition,
        )

    def record_exception(self, run_id: str, row_id: str | None, code: str) -> None:
        self._connection.execute(
            "INSERT dbo.ImportException (ImportRunId, ImportRowId, ExceptionCode) VALUES (?, ?, ?)",
            run_id, row_id, code,
        )

    def record_call_occurrence(self, run_id: str, occurrence: SourceOccurrence) -> None:
        media_type = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".html": "text/html",
            ".png": "image/png",
            ".svg": "image/svg+xml",
        }.get(Path(occurrence.relative_path).suffix.casefold())
        self._connection.execute(
            "INSERT dbo.CallSourceOccurrence "
            "(ImportRunId, SourceLocatorSha256, SourceContentSha256, SourceByteSize, SourceMediaType, ImportDisposition) "
            "VALUES (?, CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), "
            "CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), ?, ?, 'REVIEWED_INTERNAL_EXCLUSION')",
            run_id,
            hashlib.sha256(occurrence.relative_path.encode("utf-8")).hexdigest(),
            occurrence.sha256,
            occurrence.byte_size,
            media_type,
        )

    def complete_run(self, run_id: str, fingerprint: str) -> None:
        self._connection.execute(
            "UPDATE dbo.ImportRun SET RunStatus = 'COMPLETED', CompletedAtUtc = SYSUTCDATETIME() "
            "WHERE ImportRunId = ? AND ImportFingerprintSha256 = CONVERT(binary(32), CONVERT(varbinary(32), ?, 2))",
            run_id, fingerprint,
        )
        self._connection.commit()

    def fail_run(self, run_id: str) -> None:
        self._connection.rollback()
        self._connection.execute("UPDATE dbo.ImportRun SET RunStatus = 'FAILED' WHERE ImportRunId = ?", run_id)
        self._connection.commit()

    def set_call_id(self, call_id: str) -> None:
        self._call_id = call_id

    def ensure_2026_call(self) -> None:
        """Create the closed 2026 call once, or fail if the identifier conflicts."""
        row = self._connection.execute(
            "SELECT CallCode, DisplayName, CallStatus, CONVERT(varchar(19), ApplicationDeadlineUtc, 126) "
            "FROM dbo.FellowshipCall WHERE FellowshipCallId = ?",
            self._call_id,
        ).fetchone()
        expected = (
            CALL_2026_CODE,
            CALL_2026_DISPLAY_NAME,
            "CLOSED",
            CALL_2026_DEADLINE_UTC,
        )
        if row is not None:
            if tuple(str(value) for value in row) != expected:
                raise RuntimeError("The fellowship call identifier conflicts with an existing call.")
            return
        conflicting = self._connection.execute(
            "SELECT CONVERT(varchar(36), FellowshipCallId) FROM dbo.FellowshipCall WHERE CallCode = ?",
            CALL_2026_CODE,
        ).fetchone()
        if conflicting is not None:
            raise RuntimeError("The 2026 fellowship call already has a different identifier.")
        self._connection.execute(
            "INSERT dbo.FellowshipCall "
            "(FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc, SettingsJson) "
            "VALUES (?, ?, ?, 'CLOSED', CONVERT(datetime2(7), ?, 126), N'{\"source\":\"legacy-2026-import\"}')",
            self._call_id,
            CALL_2026_CODE,
            CALL_2026_DISPLAY_NAME,
            CALL_2026_DEADLINE_UTC,
        )
        self._connection.commit()


class _SqlTransaction(AbstractContextManager[None]):
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is None:
            self._connection.commit()
        else:
            self._connection.rollback()
        return False


def plan_import(request: ImportRequest) -> ImportPlan:
    """Build a deterministic, PII-free operational plan without writing any records."""
    _validate_request(request)
    exceptions: Counter[str] = Counter()
    normalized_names = [_identity_key(applicant.applicant_name) for applicant in request.applicants]
    duplicate_count = len(normalized_names) - len(set(normalized_names))
    if duplicate_count:
        exceptions["duplicate-register-row"] += duplicate_count
    if len(request.applicants) != request.expected_applicants:
        exceptions["unexpected-applicant-count"] += 1
    if request.inventory.issues:
        exceptions["source-inventory-issue"] += len(request.inventory.issues)

    matching = match_applicants_to_folders(
        request.applicants,
        request.inventory.applicant_directories,
        reviewed_aliases=request.reviewed_folder_aliases,
    )
    for match_exception in matching.exceptions:
        exceptions[_match_exception_code(match_exception.code)] += 1
    folders_by_applicant = {match.applicant_name: match.folder_name for match in matching.matches}
    matched_folders = set(folders_by_applicant.values())
    for applicant in request.applicants:
        parts = request.identity_parts.get(applicant.applicant_name)
        if not _valid_identity_parts(parts):
            exceptions["identity-parts-required"] += 1

    occurrences_by_folder: dict[str, list[SourceOccurrence]] = {}
    for occurrence in request.inventory.occurrences:
        root = occurrence.relative_path.split("/", 1)[0]
        occurrences_by_folder.setdefault(root, []).append(occurrence)
        if occurrence.is_internal or "/" not in occurrence.relative_path:
            exceptions["unassigned-internal-occurrence"] += 1
        elif root not in matched_folders:
            exceptions["unmatched-source-occurrence"] += 1

    planned = tuple(
        PlannedApplicant(
            row_number=row_number,
            applicant=applicant,
            folder_name=folders_by_applicant.get(applicant.applicant_name, ""),
            source_row_hash=_source_row_hash(applicant),
            occurrences=tuple(occurrences_by_folder.get(folders_by_applicant.get(applicant.applicant_name, ""), ())),
        )
        for row_number, applicant in enumerate(request.applicants, start=1)
    )
    manifest_hash = _manifest_hash(request.inventory)
    fingerprint = _fingerprint(request, manifest_hash)
    call_occurrences = tuple(
        occurrence
        for occurrence in request.inventory.occurrences
        if occurrence.is_internal or "/" not in occurrence.relative_path
    )
    return ImportPlan(
        fingerprint,
        manifest_hash,
        planned,
        call_occurrences,
        dict(sorted(exceptions.items())),
    )


def execute_import(
    request: ImportRequest,
    repository: ImportRepository,
    objects: ObjectIngestor,
    *,
    mode: ImportMode = ImportMode.PLAN_ONLY,
) -> ImportResult:
    """Plan by default, or atomically import each applicant when Apply is explicit."""
    plan = plan_import(request)
    if mode is ImportMode.PLAN_ONLY:
        return _result(plan, mode=mode)
    if mode is not ImportMode.APPLY:
        raise ValueError("Import mode is invalid.")
    if plan.blocked:
        raise ImportBlockedError("The import plan requires reviewed corrections.")
    completed_run = repository.completed_run(plan.fingerprint)
    if completed_run is not None:
        return _result(plan, mode=mode, run_id=completed_run, reused=True)

    run_id = repository.start_run(plan.fingerprint)
    exceptions: Counter[str] = Counter(plan.exception_counts)
    try:
        with repository.applicant_transaction():
            for occurrence in plan.call_occurrences:
                repository.record_call_occurrence(run_id, occurrence)
        for planned in plan.applicants:
            _import_applicant(request, repository, objects, run_id, planned, exceptions)
        repository.complete_run(run_id, plan.fingerprint)
    except Exception as error:
        repository.fail_run(run_id)
        if isinstance(error, ImportExecutionError):
            raise
        raise ImportExecutionError("The import run failed.") from None
    return _result(plan, mode=mode, run_id=run_id, exception_counts=exceptions)


def _import_applicant(
    request: ImportRequest,
    repository: ImportRepository,
    objects: ObjectIngestor,
    run_id: str,
    planned: PlannedApplicant,
    exceptions: Counter[str],
) -> None:
    stored: list[object] = []
    stage = "application-record"
    try:
        with repository.applicant_transaction():
            application_id = repository.application_for(planned.applicant, planned.source_row_hash)
            stage = "import-row-record"
            row_id = repository.record_row(run_id, planned.row_number, application_id, planned.source_row_hash)
            for occurrence in planned.occurrences:
                if not occurrence.is_pdf:
                    stage = "non-pdf-occurrence-record"
                    repository.record_occurrence(
                        run_id, row_id, application_id, occurrence, None, "NON_PDF"
                    )
                    repository.record_exception(run_id, row_id, "non-pdf-source")
                    exceptions["non-pdf-source"] += 1
                    continue
                try:
                    stage = "source-file-resolution"
                    source = _source_path(request.inventory.source_root, occurrence.relative_path)
                    stage = "existing-document-lookup"
                    existing_version = repository.existing_version_for_content(
                        application_id, occurrence.sha256
                    )
                    if existing_version is not None:
                        stage = "existing-occurrence-record"
                        repository.record_occurrence(
                            run_id,
                            row_id,
                            application_id,
                            occurrence,
                            existing_version,
                            "INGESTED",
                        )
                        continue
                    stage = "document-classification"
                    document_type = _document_type(source)
                    stage = "document-preparation"
                    document = repository.prepare_document(application_id, occurrence, document_type)
                    def register(stored_record: object) -> str:
                        nonlocal stage
                        stage = "document-registration"
                        try:
                            return repository.record_document(document, stored_record)
                        except Exception as error:
                            raise _DocumentRegistrationError from error
                    stage = "document-admission"
                    stored_object = objects.ingest(
                        source,
                        document,
                        register,
                    )
                    stored.append(stored_object)
                    stage = "source-occurrence-record"
                    repository.record_occurrence(
                        run_id, row_id, application_id, occurrence, str(document.version_id), "INGESTED"
                    )
                except _DocumentRegistrationError:
                    raise
                except Exception:
                    repository.record_occurrence(
                        run_id, row_id, application_id, occurrence, None, "REJECTED"
                    )
                    repository.record_exception(run_id, row_id, "document-ingestion-failed")
                    exceptions["document-ingestion-failed"] += 1
                    if occurrence.byte_size > 0:
                        raise _DocumentRegistrationError(
                            "A non-empty source document failed admission."
                        )
    except Exception as error:
        for stored_object in reversed(stored):
            try:
                objects.discard(stored_object)
            except Exception:
                pass
        raise ImportExecutionError(
            f"An applicant transaction failed during {stage} ({type(error).__name__})."
        ) from None


def _result(
    plan: ImportPlan,
    *,
    mode: ImportMode,
    run_id: str | None = None,
    reused: bool = False,
    exception_counts: Mapping[str, int] | None = None,
) -> ImportResult:
    return ImportResult(
        mode=mode,
        fingerprint=plan.fingerprint,
        source_manifest_hash=plan.source_manifest_hash,
        application_count=len(plan.applicants),
        run_id=run_id,
        reused_completed_run=reused,
        exception_counts=dict(sorted((exception_counts or plan.exception_counts).items())),
    )


def _source_path(root: Path, relative_path: str) -> Path:
    try:
        path = (root / relative_path).resolve(strict=True)
        path.relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        raise ValueError("The source occurrence is unavailable.") from None
    if not path.is_file():
        raise ValueError("The source occurrence is unavailable.")
    return path


def _document_type(source: Path) -> str:
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            first_page_text = PdfReader(source, strict=False).pages[0].extract_text() or ""
    except Exception:
        first_page_text = ""
    suggestion = suggest_classification(source.name, first_page_text[:20000])
    return "OTHER" if suggestion.document_type is DocumentType.UNKNOWN else suggestion.document_type.value


def _validate_request(request: ImportRequest) -> None:
    try:
        UUID(request.call_id)
    except ValueError:
        raise ValueError("The fellowship call identifier is invalid.") from None
    if not request.importer_version.strip() or request.expected_applicants < 1:
        raise ValueError("The import request is invalid.")


def _identity_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _valid_identity_parts(parts: tuple[str, str] | None) -> bool:
    return parts is not None and all(part.strip() for part in parts)


def _source_row_hash(applicant: RegisterApplicant) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                field: getattr(applicant, field)
                for field in applicant.__dataclass_fields__
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _manifest_hash(inventory: SourceInventory) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "applicant_directories": inventory.applicant_directories,
                "issues": [(issue.relative_path, issue.message) for issue in inventory.issues],
                "occurrences": [
                    (
                        occurrence.relative_path,
                        occurrence.sha256,
                        occurrence.byte_size,
                        occurrence.is_pdf,
                        occurrence.is_internal,
                    )
                    for occurrence in inventory.occurrences
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _fingerprint(request: ImportRequest, manifest_hash: str) -> str:
    payload = b"\x00".join(
        (
            request.call_id.encode("ascii"),
            request.importer_version.encode("utf-8"),
            hashlib.sha256(request.register_bytes).digest(),
            bytes.fromhex(manifest_hash),
            hashlib.sha256(
                json.dumps(
                    {
                        "identity_parts": request.identity_parts,
                        "reviewed_folder_aliases": request.reviewed_folder_aliases,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).digest(),
        )
    )
    return hashlib.sha256(payload).hexdigest()


def _match_exception_code(code: str) -> str:
    return {
        "no-folder-match": "unmatched-applicant",
        "ambiguous-folder-match": "ambiguous-folder-match",
        "cross-row-folder-match": "duplicate-folder-match",
        "unmatched-source-folder": "unmatched-folder",
    }.get(code, "match-failed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan a 2026 EHF source import without exposing source data.")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--register", required=True, type=Path)
    parser.add_argument("--call-id", required=True)
    parser.add_argument("--identity-parts", required=True, type=Path)
    parser.add_argument("--folder-aliases", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--sql-admin-credential-file", type=Path)
    parser.add_argument("--report-root", type=Path, default=Path("/var/lib/ehf/import-reports/2026"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Produce a non-sensitive plan; operational Apply is supplied by the root ISAB01 wrapper."""
    arguments = _parser().parse_args(argv)
    try:
        identity_parts = _load_identity_parts(arguments.identity_parts)
        reviewed_folder_aliases = _load_folder_aliases(arguments.folder_aliases)
        request = ImportRequest(
            call_id=arguments.call_id,
            importer_version=IMPORTER_VERSION,
            register_bytes=arguments.register.read_bytes(),
            applicants=parse_register(arguments.register),
            inventory=inventory_source_tree(arguments.source_root),
            identity_parts=identity_parts,
            reviewed_folder_aliases=reviewed_folder_aliases,
        )
        plan = plan_import(request)
    except (OSError, ValueError) as error:
        print(f"EHF_IMPORT_ERROR: {error}")
        return 2
    try:
        if arguments.apply:
            if arguments.sql_admin_credential_file is None:
                raise ValueError("Apply requires the protected SQL administrator credential path.")
            result = _apply_on_isab01(request, arguments.sql_admin_credential_file)
        else:
            result = _result(plan, mode=ImportMode.PLAN_ONLY)
        from app.importer.report import write_exception_report

        write_exception_report(result, arguments.report_root)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"EHF_IMPORT_ERROR: {error}")
        return 2
    print(f"Mode: {result.mode.value}")
    print(f"Applications planned: {result.application_count}")
    print(f"Source manifest: {result.source_manifest_hash}")
    print(f"Import fingerprint: {result.fingerprint}")
    print(f"Exceptions: {sum(result.exception_counts.values())}")
    print("Exception report: written without applicant names, paths, or document text.")
    return 0


def _apply_on_isab01(request: ImportRequest, admin_credential_path: Path) -> ImportResult:
    if os.name != "posix" or os.geteuid() != 0:
        raise ValueError("Apply must run through the root-mediated ISAB01 path.")
    if admin_credential_path.is_symlink() or not admin_credential_path.is_file():
        raise ValueError("The SQL administrator credential path is unsafe.")
    if admin_credential_path.stat().st_mode & 0o077:
        raise ValueError("The SQL administrator credential file is insufficiently protected.")
    settings = Settings.from_environment()
    if not settings.document_root or not settings.document_encryption_keyring_path:
        raise ValueError("Document storage is not configured.")
    repository_connection = _open_import_connection(admin_credential_path)
    try:
        repository = SqlImportRepository(repository_connection, request.identity_parts)
        repository.set_call_id(request.call_id)
        repository.ensure_2026_call()
        import pwd

        account = pwd.getpwnam("ehf")
        store = EncryptedObjectStore(
            Path(settings.document_root),
            load_keyring(Path(settings.document_encryption_keyring_path)),
            owner=(account.pw_uid, account.pw_gid),
        )
        scanner = ClamDScanner(Path(os.environ.get("EHF_CLAMD_CONFIG", "/etc/clamav/clamd.conf")))
        return execute_import(request, repository, DocumentStoreIngestor(store, scanner), mode=ImportMode.APPLY)
    finally:
        repository_connection.close()


def _open_import_connection(admin_credential_path: Path) -> Any:
    try:
        import pyodbc
        password = admin_credential_path.read_text(encoding="utf-8").strip()
        if not password:
            raise ValueError
        server = os.environ.get("EHF_SQL_SERVER", "tcp:127.0.0.1,1433").strip()
        database = os.environ.get("EHF_SQL_DATABASE", "EHFApplications").strip()
        if not server or not database or any(value in server + database for value in ";{}\r\n\0"):
            raise ValueError
        connection = pyodbc.connect(
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={server};DATABASE={database};UID=sa;PWD={{{password.replace('}', '}}')}}};"
            "Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=15;",
            autocommit=False,
        )
        connection.timeout = 15
        return connection
    except Exception:
        raise ValueError("The root-only import database connection is unavailable.") from None


def _load_identity_parts(path: Path) -> Mapping[str, tuple[str, str]]:
    """Read the reviewed name map without printing names or retaining it in reports."""
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        parsed = {
            str(name): (str(parts["given_names"]), str(parts["family_name"]))
            for name, parts in payload.items()
            if isinstance(parts, dict)
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("The reviewed identity-parts map is invalid.") from None
    if not parsed or not all(_valid_identity_parts(parts) for parts in parsed.values()):
        raise ValueError("The reviewed identity-parts map is invalid.")
    return parsed


def _load_folder_aliases(path: Path) -> Mapping[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        aliases = payload.get("aliases", payload)
        if not isinstance(aliases, dict) or not aliases:
            raise ValueError
        normalized = {
            str(applicant).strip(): str(folder).strip()
            for applicant, folder in aliases.items()
        }
        if not all(normalized) or not all(normalized.values()):
            raise ValueError
    except (OSError, ValueError, TypeError, json.JSONDecodeError, AttributeError):
        raise ValueError("The reviewed folder-alias map is invalid.") from None
    return normalized


if __name__ == "__main__":
    raise SystemExit(main())
