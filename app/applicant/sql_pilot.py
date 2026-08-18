"""SQL-backed, Entra-scoped applicant portal repositories."""

from __future__ import annotations

import contextvars
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pyodbc

from app.applicant.drafts import DraftConflict, DraftLocked, DraftSnapshot
from app.applicant.access import ApplicantAccessRequest, ApplicantAccessService
from app.applicant.documents import (
    ApplicantDocumentSlot,
    ApplicantDocumentVersion,
    DocumentUnavailable,
    DocumentUploadRejected,
)
from app.applicant.confirmations import SectionConfirmation, _canonical_hash
from app.applicant.finalize import (
    FinalConfirmation,
    FinalizationBlocked,
    FinalizationSessionUnavailable,
    REQUIRED_SECTIONS,
    _manifest_hash,
)
from app.applicant.approval import (
    ApplicantDocumentReview,
    ApplicantSubmissionBundle,
    ApplicantSubmissionReview,
    REVIEWER_GROUPS,
)
from app.applicant.projection import _RawProjection
from app.applicant.projection import ApplicantProjectionService
from app.applicant.review import ApplicantReviewService
from app.auth.applicant import (
    ApplicantAuthService,
    ApplicantSessionContext,
    CapturingVerificationDelivery,
    StoredSession,
)
from app.config import Settings
from app.db import connect
from app.documents.keys import load_keyring
from app.documents.malware import ClamDScanner, ScanResult
from app.documents.store import (
    DocumentStoreError,
    EncryptedObjectStore,
    ObjectBinding,
    StoredObjectRecord,
)
from app.documents.validation import ValidatedPdf, validate_pdf


ConnectionFactory = Callable[[], AbstractContextManager[Any]]


@dataclass(frozen=True, slots=True)
class EntraApplicantServices:
    auth: ApplicantAuthService
    projection: ApplicantProjectionService
    review: ApplicantReviewService
    documents: "SqlApplicantDocumentService"
    finalization: "SqlApplicantFinalizationService"
    approval: "SqlApplicantApprovalService"
    access: ApplicantAccessService


def build_entra_applicant_services(settings: Settings) -> EntraApplicantServices:
    connections: ConnectionFactory = lambda: connect(settings)
    scope = ApplicantSqlSessionScope()
    auth_repository = SqlEntraApplicantAuthRepository(connections, scope)
    auth = ApplicantAuthService(
        auth_repository,  # type: ignore[arg-type]
        CapturingVerificationDelivery(),
        otp_pepper=settings.read_otp_pepper().encode("utf-8"),
        session_pepper=settings.read_session_pepper().encode("utf-8"),
    )
    drafts = SqlSyntheticDraftRepository(connections, scope)
    confirmations = SqlSectionConfirmationService(connections, scope)
    document_repository = SqlApplicantDocumentRepository(connections, scope)
    review = ApplicantReviewService(drafts, confirmations)  # type: ignore[arg-type]
    return EntraApplicantServices(
        auth=auth,
        projection=ApplicantProjectionService(
            SqlSyntheticProjectionRepository(connections, scope)  # type: ignore[arg-type]
        ),
        review=review,
        documents=SqlApplicantDocumentService(
            document_repository,
            EncryptedObjectStore(
                Path(settings.document_root or ""),
                load_keyring(Path(settings.document_encryption_keyring_path or "")),
            ),
            ClamDScanner(Path(__file__).resolve().parents[2] / "infra" / "ehf-clamav.conf"),
        ),
        finalization=SqlApplicantFinalizationService(
            connections, scope, drafts, confirmations, document_repository
        ),
        approval=SqlApplicantApprovalService(connections),
        access=ApplicantAccessService(SqlApplicantAccessRepository(connections)),
    )


class ApplicantSqlSessionScope:
    """Hold only the authenticated session hash for the current request context."""

    def __init__(self) -> None:
        self._value: contextvars.ContextVar[bytes | None] = contextvars.ContextVar(
            "ehf_applicant_sql_session", default=None
        )

    def bind(self, session_hash: bytes) -> None:
        if len(session_hash) != 32:
            raise ValueError("applicant session hash must be 32 bytes")
        self._value.set(session_hash)

    def clear(self) -> None:
        self._value.set(None)

    def current(self) -> bytes | None:
        return self._value.get()

    def required(self) -> bytes:
        current = self.current()
        if current is None:
            raise PermissionError("An authenticated applicant session is required.")
        return current


class SqlEntraApplicantAuthRepository:
    """Persist Entra-derived applicant sessions without accepting application IDs."""

    def __init__(self, connections: ConnectionFactory, scope: ApplicantSqlSessionScope) -> None:
        self._connections = connections
        self._scope = scope

    def application_for_entra(self, entra_object_id: UUID) -> UUID | None:
        with self._connections() as connection:
            row = connection.execute(
                "EXEC dbo.GetApplicationForEntraApplicant @EntraObjectId = ?",
                entra_object_id,
            ).fetchone()
        return None if row is None else UUID(str(row[0]))

    def put_session(self, record: StoredSession) -> None:
        if record.entra_object_id is None or record.invitation_id is not None:
            raise PermissionError("The Entra applicant session source is invalid.")
        with self._connections() as connection:
            connection.execute(
                "EXEC dbo.CreateEntraApplicantSession "
                "@EntraObjectId = ?, @SessionTokenSha256 = ?, @CsrfTokenSha256 = ?, "
                "@IdleExpiresAtUtc = ?, @AbsoluteExpiresAtUtc = ?",
                record.entra_object_id,
                record.session_hash,
                record.csrf_hash,
                _sql_time(record.idle_expires_at),
                _sql_time(record.absolute_expires_at),
            )
            connection.commit()

    def session(self, session_hash: bytes, now: datetime) -> StoredSession | None:
        proposed_idle = min(now + timedelta(minutes=30), now + timedelta(hours=24))
        with self._connections() as connection:
            row = connection.execute(
                "EXEC dbo.GetApplicantSession "
                "@SessionTokenSha256 = ?, @IdleExpiresAtUtc = ?",
                session_hash,
                _sql_time(proposed_idle),
            ).fetchone()
            connection.commit()
        if row is None:
            self._scope.clear()
            return None
        stored = StoredSession(
            application_id=UUID(str(row[0])),
            session_hash=session_hash,
            csrf_hash=bytes(row[1]),
            idle_expires_at=_utc(row[2]),
            absolute_expires_at=_utc(row[3]),
            invitation_id=UUID(str(row[4])) if row[4] is not None else None,
            entra_object_id=UUID(str(row[5])) if row[5] is not None else None,
        )
        self._scope.bind(session_hash)
        return stored


class SqlApplicantAccessRepository:
    def __init__(self, connections: ConnectionFactory) -> None:
        self._connections = connections

    def request(self, email: str, display_name: str) -> ApplicantAccessRequest:
        with self._connections() as connection:
            row = connection.execute(
                "EXEC dbo.RequestApplicantAccess @RequestedEmail=?, @RequestedDisplayName=?",
                email, display_name,
            ).fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("The access request could not be recorded.")
        return _access_request(row)

    def pending(self) -> tuple[ApplicantAccessRequest, ...]:
        return tuple(item for item in self.actionable() if item.status == "PENDING")

    def actionable(self) -> tuple[ApplicantAccessRequest, ...]:
        with self._connections() as connection:
            rows = connection.execute(
                "EXEC dbo.ListPendingApplicantAccessRequests"
            ).fetchall()
        return tuple(_access_request(row) for row in rows)

    def review(
        self, request_id: UUID, decision: str, actor: str, actor_group: str
    ) -> ApplicantAccessRequest:
        with self._connections() as connection:
            row = connection.execute(
                "EXEC dbo.ReviewApplicantAccessRequest "
                "@ApplicantAccessRequestId=?, @Decision=?, "
                "@ReviewedByIdentity=?, @ReviewerGroup=?",
                request_id, decision, actor, actor_group,
            ).fetchone()
            connection.commit()
        if row is None:
            raise LookupError("The access request is unavailable.")
        return _access_request(row)

    def provision(
        self,
        request_id: UUID,
        application_id: UUID,
        entra_object_id: UUID,
        actor: str,
        actor_group: str,
    ) -> ApplicantAccessRequest:
        try:
            with self._connections() as connection:
                row = connection.execute(
                    "EXEC dbo.ProvisionApplicantAccessRequest "
                    "@ApplicantAccessRequestId=?, @ApplicationId=?, @EntraObjectId=?, "
                    "@ProvisionedByIdentity=?, @ProvisionerGroup=?",
                    request_id, application_id, entra_object_id, actor, actor_group,
                ).fetchone()
                connection.commit()
        except pyodbc.Error as error:
            if _sql_error_has(error, "52615"):
                raise LookupError("The approved access request is unavailable.") from None
            if _sql_error_has(error, "52616", "52617"):
                raise ValueError("The applicant identity mapping is unavailable.") from None
            raise
        if row is None:
            raise LookupError("The approved access request is unavailable.")
        return _access_request(row)


class SqlSyntheticProjectionRepository:
    def __init__(self, connections: ConnectionFactory, scope: ApplicantSqlSessionScope) -> None:
        self._connections = connections
        self._scope = scope

    def load(self, application_id: UUID) -> _RawProjection | None:
        with self._connections() as connection:
            row = connection.execute(
                "EXEC dbo.GetApplicantProjection @SessionTokenSha256 = ?",
                self._scope.required(),
            ).fetchone()
        if row is None or UUID(str(row[0])) != application_id:
            return None
        try:
            payload = json.loads(str(row[1]))
            applicant = payload["applicant"]
            sections = payload.get("sections", {})
            documents = payload.get("documents", [])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(applicant, dict) or not isinstance(sections, dict) or not isinstance(documents, list):
            return None
        return _RawProjection(
            dict(applicant),
            {str(code): dict(section) for code, section in sections.items() if isinstance(section, dict)},
            tuple(dict(document) for document in documents if isinstance(document, dict)),
            {},
        )


class SqlSyntheticDraftRepository:
    def __init__(self, connections: ConnectionFactory, scope: ApplicantSqlSessionScope) -> None:
        self._connections = connections
        self._scope = scope

    def load(self, application_id: UUID, section: str) -> DraftSnapshot | None:
        with self._connections() as connection:
            row = connection.execute(
                "EXEC dbo.GetApplicantSectionDraft @SessionTokenSha256 = ?, @SectionCode = ?",
                self._scope.required(),
                section,
            ).fetchone()
        return self._snapshot(row, application_id, section)

    def save(
        self,
        application_id: UUID,
        section: str,
        values: dict[str, Any],
        expected_row_version: int | None,
        source: str,
    ) -> DraftSnapshot:
        if source != "APPLICANT":
            raise ValueError("the applicant portal accepts applicant-originated drafts only")
        draft_json = json.dumps(
            values,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=_json_default,
        )
        expected = (
            None
            if expected_row_version is None
            else expected_row_version.to_bytes(8, "big", signed=False)
        )
        try:
            with self._connections() as connection:
                row = connection.execute(
                    "EXEC dbo.SaveApplicantSectionDraft "
                    "@SessionTokenSha256 = ?, @SectionCode = ?, @DraftJson = ?, "
                    "@ExpectedRowVersion = ?",
                    self._scope.required(),
                    section,
                    draft_json,
                    expected,
                ).fetchone()
                connection.commit()
        except pyodbc.Error as error:
            if _sql_error_has(error, "52026"):
                raise DraftConflict("The applicant draft changed before save.") from None
            if _sql_error_has(error, "52025", "52027"):
                raise DraftLocked("The applicant draft is locked.") from None
            raise
        snapshot = self._snapshot(row, application_id, section)
        if snapshot is None:
            raise RuntimeError("The applicant draft write returned no scoped record.")
        return snapshot

    def lock(self, _application_id: UUID) -> None:
        return None

    def reopen(self, _application_id: UUID, _section: str) -> None:
        raise PermissionError("Applicant sections reopen through internal review only.")

    @staticmethod
    def _snapshot(
        row: Any, application_id: UUID, section: str
    ) -> DraftSnapshot | None:
        if row is None:
            return None
        offset = 1 if len(row) >= 5 else 0
        if (
            UUID(str(row[offset])) != application_id
            or str(row[offset + 1]) != section
        ):
            return None
        try:
            values = json.loads(str(row[offset + 2]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(values, dict):
            return None
        version_bytes = bytes(row[offset + 3])
        return DraftSnapshot(
            application_id,
            section,
            values,
            int.from_bytes(version_bytes, "big", signed=False),
        )


class SqlApplicantDocumentRepository:
    """Read applicant-visible slots only through the authenticated SQL session."""

    def __init__(self, connections: ConnectionFactory, scope: ApplicantSqlSessionScope) -> None:
        self._connections = connections
        self._scope = scope

    def applicant_slots(self, session: ApplicantSessionContext) -> tuple[ApplicantDocumentSlot, ...]:
        with self._connections() as connection:
            rows = connection.execute(
                "EXEC dbo.GetApplicantDocumentSlots @SessionTokenSha256 = ?",
                self._scope.required(),
            ).fetchall()
        return tuple(
            ApplicantDocumentSlot(
                slot_id=UUID(str(row[0])),
                application_id=session.application_id,
                code=str(row[1]),
                label=str(row[2]),
                required=bool(row[3]),
                applicant_visible=True,
                upload_mode=str(row[4]),
                row_version=int.from_bytes(bytes(row[5]), "big", signed=False),
                active_version_id=UUID(str(row[6])) if row[6] is not None else None,
                document_id=UUID(str(row[7])) if row[7] is not None else None,
                document_type=str(row[8]) if row[8] is not None else "OTHER",
            )
            for row in rows
        )

    def register_submission(
        self,
        session: ApplicantSessionContext,
        slot: ApplicantDocumentSlot,
        expected_row_version: int,
        binding: ObjectBinding,
        record: StoredObjectRecord,
        validation: ValidatedPdf,
        scan: ScanResult,
        display_name: str,
    ) -> ApplicantDocumentVersion:
        with self._connections() as connection:
            row = connection.execute(
                "EXEC dbo.RegisterApplicantDocumentSubmission "
                "@SessionTokenSha256=?, @DocumentSlotId=?, @ExpectedRowVersion=?, "
                "@DocumentId=?, @DocumentVersionId=?, @StoredObjectId=?, "
                "@ObjectKey=?, @KeyVersion=?, @EnvelopeVersion=?, @AesGcmNonce=?, "
                "@PlaintextSha256=?, @CiphertextSha256=?, @ByteSize=?, @MediaType=?, "
                "@PageCount=?, @ScanEngine=?, @ScanSignature=?, @ScannedAtUtc=?, "
                "@SubmittedDisplayName=?",
                self._scope.required(), slot.slot_id,
                expected_row_version.to_bytes(8, "big", signed=False),
                binding.document_id, binding.version_id, binding.object_id,
                record.object_key, record.key_version, record.envelope_version,
                record.nonce, record.plaintext_sha256, record.ciphertext_sha256,
                record.byte_size, validation.media_type, validation.page_count,
                scan.engine, scan.signature, _sql_time(scan.scanned_at_utc),
                Path(display_name).name,
            ).fetchone()
            connection.commit()
        if row is None or UUID(str(row[0])) != session.application_id:
            raise DocumentUnavailable("The document slot is unavailable.")
        return ApplicantDocumentVersion(
            binding.version_id, slot.slot_id, binding.document_id, int(row[3]),
            "PENDING", record, binding, Path(display_name).name,
            document_type=slot.document_type,
        )

    def download_record(
        self, session: ApplicantSessionContext, slot_id: UUID
    ) -> tuple[StoredObjectRecord, ObjectBinding] | None:
        with self._connections() as connection:
            row = connection.execute(
                "EXEC dbo.GetApplicantDocumentDownload "
                "@SessionTokenSha256=?, @DocumentSlotId=?",
                self._scope.required(), slot_id,
            ).fetchone()
        if row is None or UUID(str(row[0])) != session.application_id:
            return None
        binding = ObjectBinding(
            UUID(str(row[0])), UUID(str(row[1])), UUID(str(row[2])), UUID(str(row[3]))
        )
        return StoredObjectRecord(
            str(row[4]), int(row[5]), int(row[6]), bytes(row[7]), bytes(row[8]),
            bytes(row[9]), int(row[10])
        ), binding

    def final_documents(self) -> tuple[dict[str, Any], ...]:
        with self._connections() as connection:
            rows = connection.execute(
                "EXEC dbo.GetApplicantFinalDocuments @SessionTokenSha256=?",
                self._scope.required(),
            ).fetchall()
        return tuple(
            {
                "slotCode": str(row[0]),
                "documentVersionId": str(UUID(str(row[1]))),
                "plaintextSha256": bytes(row[2]).hex(),
            }
            for row in rows
        )

    def completion_issues(self) -> tuple[str, ...]:
        with self._connections() as connection:
            rows = connection.execute(
                "EXEC dbo.GetApplicantFinalDocumentIssues @SessionTokenSha256=?",
                self._scope.required(),
            ).fetchall()
        return tuple(str(row[0]) for row in rows)


class SqlSectionConfirmationService:
    def __init__(self, connections: ConnectionFactory, scope: ApplicantSqlSessionScope) -> None:
        self._connections = connections
        self._scope = scope

    def confirm(
        self, application_id: UUID, section: str, snapshot: DraftSnapshot
    ) -> SectionConfirmation:
        if snapshot.application_id != application_id or snapshot.section != section:
            raise ValueError("confirmation scope does not match the draft")
        canonical = _canonical_hash(snapshot.values, snapshot.row_version)
        with self._connections() as connection:
            row = connection.execute(
                "EXEC dbo.ConfirmApplicantSection "
                "@SessionTokenSha256 = ?, @SectionCode = ?, "
                "@CanonicalSectionSha256 = ?, @DraftRowVersion = ?",
                self._scope.required(),
                section,
                bytes.fromhex(canonical),
                snapshot.row_version.to_bytes(8, "big", signed=False),
            ).fetchone()
            connection.commit()
        if row is None or str(row[1]) != section:
            raise RuntimeError("The section confirmation returned no scoped record.")
        return SectionConfirmation(application_id, section, snapshot.row_version, canonical)

    def current(self, application_id: UUID, section: str) -> SectionConfirmation | None:
        with self._connections() as connection:
            row = connection.execute(
                "EXEC dbo.GetApplicantSectionConfirmation "
                "@SessionTokenSha256 = ?, @SectionCode = ?",
                self._scope.required(),
                section,
            ).fetchone()
        if row is None or UUID(str(row[0])) != application_id or str(row[1]) != section:
            return None
        return SectionConfirmation(
            application_id,
            section,
            int.from_bytes(bytes(row[3]), "big", signed=False),
            bytes(row[2]).hex(),
        )

    def is_current(
        self, application_id: UUID, section: str, snapshot: DraftSnapshot
    ) -> bool:
        current = self.current(application_id, section)
        return current == SectionConfirmation(
            application_id,
            section,
            snapshot.row_version,
            _canonical_hash(snapshot.values, snapshot.row_version),
        )

    def invalidate(self, _application_id: UUID, _section: str) -> None:
        raise PermissionError("Section confirmations are invalidated by reviewer workflow only.")


class SqlApplicantDocumentService:
    def __init__(
        self,
        repository: SqlApplicantDocumentRepository,
        object_store: EncryptedObjectStore,
        scanner: ClamDScanner,
    ) -> None:
        self._repository = repository
        self._object_store = object_store
        self._scanner = scanner

    def slots(self, session: ApplicantSessionContext) -> tuple[ApplicantDocumentSlot, ...]:
        return self._repository.applicant_slots(session)

    def upload(
        self, session: ApplicantSessionContext, slot_id: UUID,
        expected_row_version: int, source: Path, filename: str, media_type: str,
    ) -> ApplicantDocumentVersion:
        slot = next((
            item for item in self.slots(session)
            if item.slot_id == slot_id
            and item.upload_mode in {"MISSING", "REPLACEMENT"}
            and item.row_version == expected_row_version
        ), None)
        if slot is None:
            raise DocumentUnavailable("The document slot is unavailable.")
        binding = ObjectBinding(
            session.application_id, slot.document_id or uuid4(), uuid4(), uuid4()
        )
        validation: ValidatedPdf | None = None
        scan: ScanResult | None = None
        registered: ApplicantDocumentVersion | None = None

        def validator(path: Path) -> ValidatedPdf:
            nonlocal validation
            validation = validate_pdf(
                path, declared_filename=filename, declared_media_type=media_type
            )
            return validation

        class ScanCapture:
            def scan(_self, path: Path) -> ScanResult:
                nonlocal scan
                scan = self._scanner.scan(path)
                return scan

        def register(record: StoredObjectRecord) -> None:
            nonlocal registered
            if validation is None or scan is None:
                raise RuntimeError("Document admission was incomplete.")
            registered = self._repository.register_submission(
                session, slot, expected_row_version, binding, record,
                validation, scan, filename,
            )

        try:
            self._object_store.ingest_file(
                source, binding, validator=validator, scanner=ScanCapture(), register=register
            )
        except (DocumentStoreError, OSError):
            raise DocumentUploadRejected("The PDF could not be accepted.") from None
        if registered is None:
            raise DocumentUploadRejected("The PDF could not be accepted.")
        return registered

    def download(self, session: ApplicantSessionContext, slot_id: UUID) -> bytes | None:
        item = self._repository.download_record(session, slot_id)
        if item is None:
            return None
        return self._object_store.decrypt_bytes(*item)


class SqlApplicantFinalizationService:
    def __init__(
        self,
        connections: ConnectionFactory,
        scope: ApplicantSqlSessionScope,
        drafts: SqlSyntheticDraftRepository,
        confirmations: SqlSectionConfirmationService,
        documents: SqlApplicantDocumentRepository,
    ) -> None:
        self._connections = connections
        self._scope = scope
        self._drafts = drafts
        self._confirmations = confirmations
        self._documents = documents

    def preview(self, session: ApplicantSessionContext) -> dict[str, Any]:
        manifest, unresolved = self._manifest(session)
        return {"manifest": manifest, "unresolved": unresolved, "ready": not unresolved}

    def submit(self, session: ApplicantSessionContext) -> FinalConfirmation:
        manifest, unresolved = self._manifest(session)
        if unresolved:
            raise FinalizationBlocked(unresolved)
        manifest_json = json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        manifest_hash = _manifest_hash(manifest)
        try:
            with self._connections() as connection:
                row = connection.execute(
                    "EXEC dbo.SubmitApplicantFinalConfirmation "
                    "@SessionTokenSha256 = ?, @ManifestJson = ?, @ManifestSha256 = ?",
                    self._scope.required(),
                    manifest_json,
                    bytes.fromhex(manifest_hash),
                ).fetchone()
                connection.commit()
        except pyodbc.Error as error:
            if _sql_error_has(error, "52133"):
                raise FinalizationSessionUnavailable(
                    "The applicant session is unavailable."
                ) from None
            if _sql_error_has(error, "52135", "52136"):
                raise FinalizationBlocked(("section:stale",)) from None
            if _sql_error_has(
                error, "52430", "52431", "52432", "52433", "52434", "52435"
            ):
                raise FinalizationBlocked(
                    self._documents.completion_issues() or ("document:validation",)
                ) from None
            raise
        if row is None:
            raise RuntimeError("The applicant submission returned no scoped record.")
        return FinalConfirmation(
            UUID(str(row[0])),
            session.application_id,
            manifest,
            manifest_hash,
            _utc(row[2]),
        )

    def _manifest(
        self, session: ApplicantSessionContext
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        unresolved: list[str] = []
        sections: list[dict[str, Any]] = []
        for section in REQUIRED_SECTIONS:
            snapshot = self._drafts.load(session.application_id, section)
            confirmation = self._confirmations.current(session.application_id, section)
            if snapshot is None or confirmation is None or not self._confirmations.is_current(
                session.application_id, section, snapshot
            ):
                unresolved.append(f"section:{section}")
                continue
            sections.append(
                {
                    "section": section,
                    "rowVersion": snapshot.row_version,
                    "canonicalSha256": confirmation.canonical_sha256,
                }
            )
        unresolved.extend(self._documents.completion_issues())
        return (
            {
                "schemaVersion": 1,
                "sections": sections,
                "documents": list(self._documents.final_documents()),
            },
            tuple(unresolved),
        )


class SqlApplicantApprovalService:
    def __init__(self, connections: ConnectionFactory) -> None:
        self._connections = connections

    def pending(self) -> tuple[ApplicantSubmissionReview, ...]:
        with self._connections() as connection:
            rows = connection.execute("EXEC dbo.ListPendingApplicantSubmissions").fetchall()
        return tuple(
            ApplicantSubmissionReview(UUID(str(row[0])), UUID(str(row[1])), _utc(row[2]))
            for row in rows
        )

    def detail(self, confirmation_id: UUID) -> ApplicantSubmissionBundle:
        with self._connections() as connection:
            cursor = connection.execute(
                "EXEC dbo.GetApplicantSubmissionReview "
                "@ApplicantFinalConfirmationId=?", confirmation_id,
            )
            header = cursor.fetchone()
            if header is None:
                raise LookupError("The applicant submission is unavailable.")
            cursor.nextset()
            rows = cursor.fetchall()
        try:
            baseline = json.loads(str(header[2]))
            manifest = json.loads(str(header[3]))
            drafts = {str(row[0]): json.loads(str(row[1])) for row in rows}
        except (TypeError, ValueError, json.JSONDecodeError):
            raise RuntimeError("The applicant review bundle is invalid.") from None
        return ApplicantSubmissionBundle(
            UUID(str(header[0])), UUID(str(header[1])),
            baseline, manifest, drafts,
        )

    def approve(
        self, confirmation_id: UUID, *, actor: str, actor_group: str
    ) -> ApplicantSubmissionReview:
        if actor_group not in REVIEWER_GROUPS or not actor.strip():
            raise PermissionError("Administrator or trustee authorization is required.")
        with self._connections() as connection:
            row = connection.execute(
                "EXEC dbo.ApproveApplicantSubmission "
                "@ApplicantFinalConfirmationId = ?, @ReviewedByIdentity = ?, "
                "@ReviewerGroup = ?",
                confirmation_id,
                actor.strip(),
                actor_group,
            ).fetchone()
            connection.commit()
        if row is None:
            raise LookupError("The applicant submission is unavailable.")
        return ApplicantSubmissionReview(
            UUID(str(row[0])),
            UUID(str(row[1])),
            _utc(row[4]),
            status=str(row[2]),
            reviewed_by=str(row[3]),
            reviewed_at_utc=_utc(row[4]),
        )

    def pending_documents(self) -> tuple[ApplicantDocumentReview, ...]:
        with self._connections() as connection:
            rows = connection.execute(
                "EXEC dbo.ListPendingApplicantDocumentSubmissions"
            ).fetchall()
        return tuple(
            ApplicantDocumentReview(
                UUID(str(row[0])), UUID(str(row[1])), UUID(str(row[2])),
                UUID(str(row[3])), str(row[4]), _utc(row[5]),
            )
            for row in rows
        )

    def accept_document(
        self, submission_id: UUID, *, actor: str, actor_group: str
    ) -> ApplicantDocumentReview:
        return self._review_document(
            submission_id, "ACCEPTED", actor=actor, actor_group=actor_group
        )

    def reject_document(
        self, submission_id: UUID, *, actor: str, actor_group: str, reason: str
    ) -> ApplicantDocumentReview:
        if not reason.strip():
            raise ValueError("A rejection reason is required.")
        return self._review_document(
            submission_id, "REJECTED", actor=actor,
            actor_group=actor_group, reason=reason.strip(),
        )

    def _review_document(
        self, submission_id: UUID, decision: str, *, actor: str,
        actor_group: str, reason: str | None = None,
    ) -> ApplicantDocumentReview:
        if actor_group not in REVIEWER_GROUPS or not actor.strip():
            raise PermissionError("Administrator or trustee authorization is required.")
        with self._connections() as connection:
            row = connection.execute(
                "EXEC dbo.ReviewApplicantDocumentSubmission "
                "@ApplicantDocumentSubmissionId=?, @Decision=?, "
                "@ReviewedByIdentity=?, @ReviewerGroup=?, @ReviewReason=?",
                submission_id, decision, actor.strip(), actor_group, reason,
            ).fetchone()
            connection.commit()
        if row is None:
            raise LookupError("The applicant document submission is unavailable.")
        return ApplicantDocumentReview(
            UUID(str(row[0])), UUID(str(row[1])), UUID(int=0), UUID(int=0), "",
            _utc(row[4]), status=str(row[2]), reviewed_by=str(row[3]),
            reviewed_at_utc=_utc(row[4]), reason=reason,
        )


def _json_default(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Unsupported applicant draft value: {type(value).__name__}")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _sql_time(value: datetime) -> datetime:
    return _utc(value).replace(tzinfo=None)


def _sql_error_has(error: pyodbc.Error, *codes: str) -> bool:
    message = " ".join(str(item) for item in error.args)
    return any(code in message for code in codes)


def _access_request(row: Any) -> ApplicantAccessRequest:
    return ApplicantAccessRequest(
        UUID(str(row[0])), str(row[1]), str(row[2]), _utc(row[3]),
        status=str(row[4]),
        reviewed_by=str(row[5]) if row[5] is not None else None,
        reviewer_group=str(row[6]) if row[6] is not None else None,
        reviewed_at_utc=_utc(row[7]) if row[7] is not None else None,
    )
