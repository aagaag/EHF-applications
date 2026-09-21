"""Validated, reviewed extraction manifests for internal applicant PDFs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Protocol
from uuid import UUID, uuid4

from pypdf import PdfReader

from app.documents.extract import PdfExtractError, PdfSegment, build_pdf_extract
from app.documents.malware import ScanResult
from app.documents.store import EncryptedObjectStore, ObjectBinding, StoredObjectRecord


class ReviewArtifactImportError(RuntimeError):
    """A private review-artifact manifest or source failed closed."""


@dataclass(frozen=True, slots=True)
class ReviewArtifactSegment:
    source_version_id: UUID
    source_sha256: bytes
    relative_path: str
    first_page: int
    last_page: int


@dataclass(frozen=True, slots=True)
class ReviewArtifactDefinition:
    application_id: UUID
    category: str
    segments: tuple[ReviewArtifactSegment, ...]


@dataclass(frozen=True, slots=True)
class ReviewArtifactManifest:
    reviewed_by: str
    artifacts: tuple[ReviewArtifactDefinition, ...]


@dataclass(frozen=True, slots=True)
class PreparedReviewArtifact:
    application_id: UUID
    category: str
    reviewed_by: str
    segments: tuple[ReviewArtifactSegment, ...]
    payload: bytes


@dataclass(frozen=True, slots=True)
class ReviewArtifactImportResult:
    mode: str
    application_count: int
    artifact_count: int
    applied_count: int
    prepared: tuple[PreparedReviewArtifact, ...]


class ReviewArtifactRepository(Protocol):
    def source_pdf(
        self, application_id: UUID, version_id: UUID, expected_sha256: bytes
    ) -> bytes: ...

    def apply(self, prepared: tuple[PreparedReviewArtifact, ...]) -> int: ...


_CATEGORIES = frozenset({"APPLICATION", "CURRICULUM", "PUBLICATIONS"})
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_RECOMMENDATION_SIGNALS = (
    "letter of recommendation",
    "recommendation for",
    "i strongly recommend",
    "i highly recommend",
    "referee report",
    "referee letter",
    "reference letter",
    "letter of support",
    "support the application",
    "strongest support",
)
_TITLES = {
    "APPLICATION": ("EHF fellowship application", "Reviewed fellowship-project extract"),
    "CURRICULUM": ("EHF applicant curriculum", "Reviewed curriculum extract"),
    "PUBLICATIONS": ("EHF applicant publication list", "Reviewed publication-list extract"),
}


def load_review_artifact_manifest(raw: bytes) -> ReviewArtifactManifest:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ReviewArtifactImportError("The review-artifact manifest is invalid.") from None
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ReviewArtifactImportError("The review-artifact manifest version is invalid.")
    reviewed_by = value.get("reviewedBy")
    artifacts_value = value.get("artifacts")
    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        raise ReviewArtifactImportError("The review identity is required.")
    if not isinstance(artifacts_value, list) or not artifacts_value:
        raise ReviewArtifactImportError("At least one reviewed artifact is required.")
    artifacts: list[ReviewArtifactDefinition] = []
    keys: set[tuple[UUID, str]] = set()
    for item in artifacts_value:
        if not isinstance(item, dict):
            raise ReviewArtifactImportError("A reviewed artifact is invalid.")
        try:
            application_id = UUID(str(item.get("applicationId")))
        except (ValueError, TypeError, AttributeError):
            raise ReviewArtifactImportError("An application identifier is invalid.") from None
        category = str(item.get("category", "")).strip().upper()
        if category not in _CATEGORIES:
            raise ReviewArtifactImportError("A review-artifact category is invalid.")
        key = (application_id, category)
        if key in keys:
            raise ReviewArtifactImportError("A review-artifact category is duplicated.")
        keys.add(key)
        segments_value = item.get("segments")
        if not isinstance(segments_value, list) or not segments_value:
            raise ReviewArtifactImportError("A review artifact needs source page ranges.")
        segments: list[ReviewArtifactSegment] = []
        for segment in segments_value:
            if not isinstance(segment, dict):
                raise ReviewArtifactImportError("A source page range is invalid.")
            try:
                version_id = UUID(str(segment.get("sourceVersionId")))
            except (ValueError, TypeError, AttributeError):
                raise ReviewArtifactImportError("A source version identifier is invalid.") from None
            digest_text = str(segment.get("sourceSha256", "")).lower()
            if _HEX_64.fullmatch(digest_text) is None:
                raise ReviewArtifactImportError("A source hash is invalid.")
            relative_path = str(segment.get("relativePath", ""))
            pure_path = PurePosixPath(relative_path.replace("\\", "/"))
            if pure_path.is_absolute() or not relative_path or ".." in pure_path.parts:
                raise ReviewArtifactImportError("A source path must remain inside the source root.")
            first_page = segment.get("firstPage")
            last_page = segment.get("lastPage")
            if (
                not isinstance(first_page, int)
                or isinstance(first_page, bool)
                or not isinstance(last_page, int)
                or isinstance(last_page, bool)
                or first_page < 1
                or last_page < first_page
            ):
                raise ReviewArtifactImportError("A source page range is invalid.")
            segments.append(
                ReviewArtifactSegment(
                    version_id,
                    bytes.fromhex(digest_text),
                    pure_path.as_posix(),
                    first_page,
                    last_page,
                )
            )
        artifacts.append(ReviewArtifactDefinition(application_id, category, tuple(segments)))
    return ReviewArtifactManifest(reviewed_by.strip(), tuple(artifacts))


def run_review_artifact_import(
    raw: bytes,
    *,
    source_root: Path,
    apply: bool,
    repository: ReviewArtifactRepository | None = None,
) -> ReviewArtifactImportResult:
    manifest = load_review_artifact_manifest(raw)
    root = source_root.resolve()
    if apply and repository is None:
        raise ReviewArtifactImportError("Apply requires the review-artifact repository.")
    prepared: list[PreparedReviewArtifact] = []
    for artifact in manifest.artifacts:
        pdf_segments: list[PdfSegment] = []
        for segment in artifact.segments:
            if apply:
                assert repository is not None
                payload = repository.source_pdf(
                    artifact.application_id,
                    segment.source_version_id,
                    segment.source_sha256,
                )
            else:
                path = (root / Path(segment.relative_path)).resolve()
                try:
                    path.relative_to(root)
                except ValueError:
                    raise ReviewArtifactImportError(
                        "A source path must remain inside the source root."
                    ) from None
                try:
                    payload = path.read_bytes()
                except OSError:
                    raise ReviewArtifactImportError("A source PDF is unavailable.") from None
            if hashlib.sha256(payload).digest() != segment.source_sha256:
                raise ReviewArtifactImportError("A source PDF hash does not match the manifest.")
            _reject_recommendation_pages(payload, segment.first_page, segment.last_page)
            pdf_segments.append(PdfSegment(payload, segment.first_page, segment.last_page))
        title, subject = _TITLES[artifact.category]
        try:
            extracted = build_pdf_extract(tuple(pdf_segments), title=title, subject=subject)
        except PdfExtractError as error:
            raise ReviewArtifactImportError(str(error)) from None
        prepared.append(
            PreparedReviewArtifact(
                artifact.application_id,
                artifact.category,
                manifest.reviewed_by,
                artifact.segments,
                extracted,
            )
        )
    applied_count = repository.apply(tuple(prepared)) if apply and repository else 0
    return ReviewArtifactImportResult(
        "APPLY" if apply else "PLAN_ONLY",
        len({item.application_id for item in prepared}),
        len(prepared),
        applied_count,
        tuple(prepared),
    )


def _reject_recommendation_pages(payload: bytes, first_page: int, last_page: int) -> None:
    try:
        reader = PdfReader(io.BytesIO(payload), strict=True)
        if reader.is_encrypted or last_page > len(reader.pages):
            raise ReviewArtifactImportError("A source PDF is unavailable.")
        metadata = " ".join(str(value) for value in (reader.metadata or {}).values())
        text = " ".join(
            (reader.pages[index].extract_text() or "")
            for index in range(first_page - 1, last_page)
        )
    except ReviewArtifactImportError:
        raise
    except Exception:
        raise ReviewArtifactImportError("A source PDF is unavailable.") from None
    normalized = re.sub(r"\s+", " ", f"{metadata} {text}".casefold())
    if any(signal in normalized for signal in _RECOMMENDATION_SIGNALS):
        raise ReviewArtifactImportError("A selected page contains recommendation material.")


class SqlReviewArtifactRepository:
    """Root-mediated registration of generated artifacts and immutable provenance."""

    def __init__(self, connection: Any, store: EncryptedObjectStore, scanner: Any, quarantine: Path):
        self._connection = connection
        self._store = store
        self._scanner = scanner
        self._quarantine = quarantine

    def source_pdf(
        self, application_id: UUID, version_id: UUID, expected_sha256: bytes
    ) -> bytes:
        row = self._connection.execute(
            "SELECT slot_row.ApplicationId, document_row.DocumentId, "
            "version_row.DocumentVersionId, object_row.StoredObjectId, "
            "object_row.ObjectKey, object_row.KeyVersion, object_row.EnvelopeVersion, "
            "object_row.AesGcmNonce, object_row.PlaintextSha256, "
            "object_row.CiphertextSha256, object_row.ByteSize "
            "FROM dbo.DocumentVersion AS version_row "
            "JOIN dbo.Document AS document_row ON document_row.DocumentId=version_row.DocumentId "
            "JOIN dbo.DocumentSlot AS slot_row ON slot_row.DocumentSlotId=document_row.DocumentSlotId "
            "JOIN dbo.StoredObject AS object_row ON object_row.StoredObjectId=version_row.StoredObjectId "
            "WHERE slot_row.ApplicationId=? AND version_row.DocumentVersionId=? "
            "AND slot_row.ActiveDocumentVersionId=version_row.DocumentVersionId "
            "AND version_row.Classification IN ('UNREVIEWED','APPLICANT_VISIBLE') "
            "AND document_row.DocumentType<>'RECOMMENDATION_LETTER' "
            "AND object_row.ScanResult='CLEAN' "
            "AND NOT EXISTS (SELECT 1 FROM dbo.Recommendation AS recommendation_row "
            "WHERE recommendation_row.DocumentId=document_row.DocumentId)",
            application_id,
            version_id,
        ).fetchone()
        if row is None or bytes(row[8]) != expected_sha256:
            raise ReviewArtifactImportError("A database source PDF is unavailable or stale.")
        binding = ObjectBinding(
            UUID(str(row[0])), UUID(str(row[1])), UUID(str(row[2])), UUID(str(row[3]))
        )
        record = StoredObjectRecord(
            str(row[4]), int(row[5]), int(row[6]), bytes(row[7]), bytes(row[8]),
            bytes(row[9]), int(row[10]),
        )
        try:
            return self._store.decrypt_bytes(record, binding)
        except Exception:
            raise ReviewArtifactImportError("A database source PDF is unavailable or stale.") from None

    def apply(self, prepared: tuple[PreparedReviewArtifact, ...]) -> int:
        scans = tuple(self._scan(item.payload) for item in prepared)
        created_object_keys: list[str] = []
        applied = 0
        try:
            for artifact, scan in zip(prepared, scans, strict=True):
                payload_hash = hashlib.sha256(artifact.payload).digest()
                existing = self._connection.execute(
                    "SELECT slot_row.DocumentSlotId, document_row.DocumentId, "
                    "version_row.VersionNumber, object_row.PlaintextSha256, "
                    "version_row.DocumentVersionId "
                    "FROM dbo.DocumentSlot AS slot_row "
                    "JOIN dbo.Document AS document_row ON document_row.DocumentSlotId=slot_row.DocumentSlotId "
                    "LEFT JOIN dbo.DocumentVersion AS version_row "
                    "ON version_row.DocumentVersionId=slot_row.ActiveDocumentVersionId "
                    "LEFT JOIN dbo.StoredObject AS object_row "
                    "ON object_row.StoredObjectId=version_row.StoredObjectId "
                    "WHERE slot_row.ApplicationId=? AND slot_row.SlotCode=?",
                    artifact.application_id,
                    _slot_code(artifact.category),
                ).fetchone()
                if existing is not None and existing[3] is not None and bytes(existing[3]) == payload_hash:
                    provenance = self._connection.execute(
                        "SELECT SourceDocumentVersionId, SegmentOrder, FirstPage, LastPage, "
                        "SourcePlaintextSha256 FROM dbo.InternalReviewArtifactProvenance "
                        "WHERE ArtifactDocumentVersionId=? ORDER BY SegmentOrder",
                        existing[4],
                    ).fetchall()
                    if _matches_provenance(provenance, artifact.segments):
                        continue
                slot_id = UUID(str(existing[0])) if existing is not None else uuid4()
                document_id = UUID(str(existing[1])) if existing is not None else uuid4()
                version_number = (int(existing[2] or 0) + 1) if existing is not None else 1
                version_id, object_id = uuid4(), uuid4()
                binding = ObjectBinding(artifact.application_id, document_id, version_id, object_id)

                def register(record: StoredObjectRecord) -> None:
                    if existing is None:
                        self._connection.execute(
                            "INSERT dbo.DocumentSlot "
                            "(DocumentSlotId,ApplicationId,SlotCode,CreatedByIdentity,"
                            "ApplicantUploadMode,ApplicantVisible,SlotLabel,RequiredForCompletion) "
                            "VALUES (?,?,?,?,'CLOSED',0,?,0)",
                            slot_id, artifact.application_id, _slot_code(artifact.category),
                            artifact.reviewed_by, _slot_label(artifact.category),
                        )
                        self._connection.execute(
                            "INSERT dbo.Document "
                            "(DocumentId,DocumentSlotId,DocumentType,CreatedByIdentity) "
                            "VALUES (?,?,?,?)",
                            document_id, slot_id, _document_type(artifact.category),
                            artifact.reviewed_by,
                        )
                    self._connection.execute(
                        "INSERT dbo.StoredObject "
                        "(StoredObjectId,ObjectKey,KeyVersion,EnvelopeVersion,AesGcmNonce,"
                        "PlaintextSha256,CiphertextSha256,ByteSize,MediaType,PageCount,"
                        "ScanEngine,ScanSignature,ScannedAtUtc,ScanResult,CreatedByIdentity) "
                        "VALUES (?,?,?,?,?,?,?,?, 'application/pdf',?,?,?,?, 'CLEAN',?)",
                        object_id, record.object_key, record.key_version, record.envelope_version,
                        record.nonce, record.plaintext_sha256, record.ciphertext_sha256,
                        record.byte_size, len(PdfReader(io.BytesIO(artifact.payload)).pages),
                        scan.engine, scan.signature, scan.scanned_at_utc, artifact.reviewed_by,
                    )
                    self._connection.execute(
                        "INSERT dbo.DocumentVersion "
                        "(DocumentVersionId,DocumentId,StoredObjectId,VersionNumber,"
                        "Classification,CreatedByIdentity) VALUES (?,?,?,?,'INTERNAL_ADMINISTRATIVE',?)",
                        version_id, document_id, object_id, version_number, artifact.reviewed_by,
                    )
                    for order, segment in enumerate(artifact.segments, start=1):
                        self._connection.execute(
                            "INSERT dbo.InternalReviewArtifactProvenance "
                            "(ApplicationId,Category,ArtifactDocumentVersionId,SourceDocumentVersionId,"
                            "SegmentOrder,FirstPage,LastPage,SourcePlaintextSha256,ReviewedByIdentity) "
                            "VALUES (?,?,?,?,?,?,?,?,?)",
                            artifact.application_id, artifact.category, version_id,
                            segment.source_version_id, order, segment.first_page,
                            segment.last_page, segment.source_sha256, artifact.reviewed_by,
                        )
                    self._connection.execute(
                        "UPDATE dbo.DocumentSlot SET ActiveDocumentVersionId=? WHERE DocumentSlotId=?",
                        version_id, slot_id,
                    )
                    created_object_keys.append(record.object_key)

                self._store.store_bytes(artifact.payload, binding, register=register)
                applied += 1
            self._connection.commit()
            return applied
        except Exception:
            self._connection.rollback()
            for object_key in created_object_keys:
                self._store.path_for(object_key).unlink(missing_ok=True)
            raise ReviewArtifactImportError("The review-artifact transaction was rolled back.") from None

    def _scan(self, payload: bytes) -> ScanResult:
        self._quarantine.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix="review-artifact-", suffix=".pdf", dir=self._quarantine)
        path = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
            os.chmod(path, 0o600)
            return self._scanner.scan(path)
        finally:
            path.unlink(missing_ok=True)


def _slot_code(category: str) -> str:
    return f"REVIEW-ARTIFACT-{category}"


def _slot_label(category: str) -> str:
    return {
        "APPLICATION": "Reviewed fellowship application",
        "CURRICULUM": "Reviewed curriculum",
        "PUBLICATIONS": "Reviewed publication list",
    }[category]


def _document_type(category: str) -> str:
    return {
        "APPLICATION": "RESEARCH_PLAN",
        "CURRICULUM": "CV",
        "PUBLICATIONS": "PUBLICATION_LIST",
    }[category]


def _matches_provenance(rows: Any, segments: tuple[ReviewArtifactSegment, ...]) -> bool:
    actual = tuple(
        (UUID(str(row[0])), int(row[1]), int(row[2]), int(row[3]), bytes(row[4]))
        for row in rows
    )
    expected = tuple(
        (
            segment.source_version_id,
            order,
            segment.first_page,
            segment.last_page,
            segment.source_sha256,
        )
        for order, segment in enumerate(segments, start=1)
    )
    return actual == expected
