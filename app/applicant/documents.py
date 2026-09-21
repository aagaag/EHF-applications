"""Controlled, immutable applicant document-slot workflow."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID, uuid4

from app.auth.applicant import ApplicantSessionContext
from app.documents.malware import MalwareDetectedError, MalwareUnavailableError
from app.documents.store import (
    DocumentStoreError,
    DuplicatePlaintextError,
    EncryptedObjectStore,
    ObjectBinding,
    StoredObjectRecord,
)
from app.documents.validation import validate_pdf
from app.documents.package import PdfPackageError, build_pdf_package


REQUIRED_SLOT_CODES = (
    "CV",
    "PUBLICATION_LIST",
    "RESEARCH_PLAN",
    "COVER_LETTER_CAREER_PLAN",
    "FUTURE_UZH_EMPLOYMENT_PROOF",
)

REVIEW_ARTIFACT_SLOT_CODES = {
    "application": "REVIEW-ARTIFACT-APPLICATION",
    "curriculum": "REVIEW-ARTIFACT-CURRICULUM",
    "publications": "REVIEW-ARTIFACT-PUBLICATIONS",
}


class DocumentUnavailable(RuntimeError):
    pass


class DocumentUploadRejected(RuntimeError):
    pass


class DocumentScannerUnavailable(DocumentUploadRejected):
    """The malware scanner could not provide a verdict, so nothing may be accepted."""


class DocumentAlreadySubmitted(DocumentUploadRejected):
    """An identical document is already part of this application's dossier."""


@dataclass(frozen=True, slots=True)
class ApplicantDocumentSlot:
    slot_id: UUID
    application_id: UUID
    code: str
    label: str
    required: bool
    applicant_visible: bool
    classification: str = "APPLICANT_VISIBLE"
    document_type: str = "OTHER"
    recommendation_linked: bool = False
    upload_mode: str = "CLOSED"
    row_version: int = 1
    active_version_id: UUID | None = None
    document_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ApplicantDocumentVersion:
    version_id: UUID
    slot_id: UUID
    document_id: UUID
    version_number: int
    status: str
    object_record: StoredObjectRecord
    binding: ObjectBinding
    display_name: str
    classification: str = "UNREVIEWED"
    document_type: str = "OTHER"
    recommendation_linked: bool = False
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class InternalDocumentSummary:
    slot_id: UUID
    version_id: UUID
    code: str
    label: str
    version_number: int
    status: str


@dataclass(frozen=True, slots=True)
class InternalReviewArtifactSummary:
    category: str
    version_id: UUID


@dataclass(frozen=True, slots=True)
class DocumentAccessEvent:
    application_id: UUID
    version_id: UUID
    actor: str
    actor_group: str
    purpose: str
    outcome: str


class DocumentSlotRepository:
    def __init__(self) -> None:
        self._slots: dict[UUID, ApplicantDocumentSlot] = {}
        self._versions: dict[UUID, ApplicantDocumentVersion] = {}
        self._slot_versions: dict[UUID, list[UUID]] = {}

    def add_slot(
        self,
        application_id: UUID,
        code: str,
        label: str,
        *,
        required: bool,
        applicant_visible: bool = True,
        classification: str = "APPLICANT_VISIBLE",
        document_type: str = "OTHER",
        recommendation_linked: bool = False,
    ) -> ApplicantDocumentSlot:
        normalized = code.strip().upper()
        confidential = (
            classification != "APPLICANT_VISIBLE"
            or document_type == "RECOMMENDATION_LETTER"
            or recommendation_linked
            or "RECOMMEND" in normalized
        )
        if confidential and applicant_visible:
            raise ValueError("confidential or recommendation slots cannot be applicant-visible")
        if not normalized or not label.strip():
            raise ValueError("document slot code and label are required")
        slot = ApplicantDocumentSlot(
            uuid4(), application_id, normalized, label.strip(), required, applicant_visible,
            classification, document_type, recommendation_linked,
        )
        self._slots[slot.slot_id] = slot
        self._slot_versions[slot.slot_id] = []
        return slot

    def slot(self, slot_id: UUID) -> ApplicantDocumentSlot:
        return self._slots[slot_id]

    def applicant_slots(
        self, session: ApplicantSessionContext
    ) -> tuple[ApplicantDocumentSlot, ...]:
        return tuple(
            slot
            for slot in self._slots.values()
            if slot.application_id == session.application_id
            and _safe_applicant_slot(slot)
        )

    def slots_for_application(
        self, application_id: UUID
    ) -> tuple[ApplicantDocumentSlot, ...]:
        return tuple(
            slot
            for slot in self._slots.values()
            if slot.application_id == application_id
            and _safe_applicant_slot(slot)
        )

    def active_version(
        self, slot: ApplicantDocumentSlot
    ) -> ApplicantDocumentVersion | None:
        if slot.active_version_id is None:
            return None
        version = self._versions.get(slot.active_version_id)
        if version is None or version.slot_id != slot.slot_id:
            return None
        return version

    def open_slot(
        self,
        application_id: UUID,
        slot_id: UUID,
        mode: str,
        actor: str,
        reason: str,
    ) -> ApplicantDocumentSlot:
        if mode not in {"MISSING", "REPLACEMENT"} or not actor.strip() or not reason.strip():
            raise ValueError("a valid upload mode, actor, and reason are required")
        slot = self._slots.get(slot_id)
        if slot is None or slot.application_id != application_id or not _safe_applicant_slot(slot):
            raise DocumentUnavailable("The document slot is unavailable.")
        updated = replace(slot, upload_mode=mode, row_version=slot.row_version + 1)
        self._slots[slot_id] = updated
        return updated

    def require_upload(
        self,
        application_id: UUID,
        slot_id: UUID,
        expected_row_version: int,
    ) -> ApplicantDocumentSlot:
        slot = self._slots.get(slot_id)
        if (
            slot is None
            or slot.application_id != application_id
            or not _safe_applicant_slot(slot)
            or slot.upload_mode not in {"MISSING", "REPLACEMENT"}
            or slot.row_version != expected_row_version
        ):
            raise DocumentUnavailable("The document slot is unavailable.")
        return slot

    def register_pending(
        self,
        slot: ApplicantDocumentSlot,
        expected_row_version: int,
        version_id: UUID,
        document_id: UUID,
        binding: ObjectBinding,
        record: StoredObjectRecord,
        display_name: str,
    ) -> ApplicantDocumentVersion:
        current = self.require_upload(slot.application_id, slot.slot_id, expected_row_version)
        existing = self._slot_versions[current.slot_id]
        version = ApplicantDocumentVersion(
            version_id,
            current.slot_id,
            document_id,
            len(existing) + 1,
            "PENDING",
            record,
            binding,
            display_name,
            "UNREVIEWED",
            current.document_type,
            current.recommendation_linked,
        )
        self._versions[version_id] = version
        existing.append(version_id)
        self._slots[current.slot_id] = replace(
            current,
            upload_mode="CLOSED",
            row_version=current.row_version + 1,
            document_id=document_id,
        )
        return version

    def versions(self, slot_id: UUID) -> tuple[ApplicantDocumentVersion, ...]:
        return tuple(self._versions[version_id] for version_id in self._slot_versions.get(slot_id, []))

    def internal_documents(
        self, application_id: UUID
    ) -> tuple[tuple[ApplicantDocumentSlot, ApplicantDocumentVersion], ...]:
        result = []
        for slot in self.slots_for_application(application_id):
            version = self.active_version(slot)
            if (
                version is not None
                and version.status == "ACCEPTED"
                and version.classification == "APPLICANT_VISIBLE"
                and version.document_type != "RECOMMENDATION_LETTER"
                and not version.recommendation_linked
            ):
                result.append((slot, version))
        return tuple(result)

    def internal_version(
        self, application_id: UUID, version_id: UUID
    ) -> ApplicantDocumentVersion | None:
        for slot in self.slots_for_application(application_id):
            for version in self.versions(slot.slot_id):
                if version.version_id != version_id:
                    continue
                if version.document_type == "RECOMMENDATION_LETTER" or version.recommendation_linked:
                    return None
                if version.status == "PENDING":
                    return version
                if (
                    version.status == "ACCEPTED"
                    and version.classification == "APPLICANT_VISIBLE"
                    and slot.active_version_id == version.version_id
                ):
                    return version
                return None
        return None

    def internal_review_artifacts(
        self, application_id: UUID
    ) -> tuple[InternalReviewArtifactSummary, ...]:
        categories_by_code = {code: category for category, code in REVIEW_ARTIFACT_SLOT_CODES.items()}
        artifacts: list[InternalReviewArtifactSummary] = []
        for slot, version in self.internal_documents(application_id):
            category = categories_by_code.get(slot.code)
            if category is not None:
                artifacts.append(InternalReviewArtifactSummary(category, version.version_id))
        return tuple(artifacts)

    def accept(self, version_id: UUID, actor: str) -> ApplicantDocumentVersion:
        if not actor.strip():
            raise ValueError("reviewing actor is required")
        version = self._versions.get(version_id)
        if version is None or version.status != "PENDING":
            raise DocumentUnavailable("The document version is unavailable.")
        if version.document_type == "RECOMMENDATION_LETTER" or version.recommendation_linked:
            raise DocumentUnavailable("The document version is unavailable.")
        accepted = replace(version, status="ACCEPTED", classification="APPLICANT_VISIBLE")
        self._versions[version_id] = accepted
        slot = self._slots[version.slot_id]
        self._slots[version.slot_id] = replace(
            slot, active_version_id=version_id, row_version=slot.row_version + 1
        )
        return accepted

    def reject(self, version_id: UUID, actor: str, reason: str) -> ApplicantDocumentVersion:
        if not actor.strip() or not reason.strip():
            raise ValueError("reviewing actor and reason are required")
        version = self._versions.get(version_id)
        if version is None or version.status != "PENDING":
            raise DocumentUnavailable("The document version is unavailable.")
        rejected = replace(version, status="REJECTED", rejection_reason=reason.strip())
        self._versions[version_id] = rejected
        return rejected

    def restore(self, slot_id: UUID, version_id: UUID, actor: str) -> ApplicantDocumentVersion:
        if not actor.strip():
            raise ValueError("reviewing actor is required")
        version = self._versions.get(version_id)
        slot = self._slots.get(slot_id)
        if version is None or slot is None or version.slot_id != slot_id or version.status != "ACCEPTED":
            raise DocumentUnavailable("The document version is unavailable.")
        self._slots[slot_id] = replace(
            slot, active_version_id=version_id, row_version=slot.row_version + 1
        )
        return version


class ApplicantDocumentService:
    def __init__(
        self,
        repository: DocumentSlotRepository,
        object_store: EncryptedObjectStore,
        scanner: object,
    ) -> None:
        self._repository = repository
        self._object_store = object_store
        self._scanner = scanner
        self._access_events: list[DocumentAccessEvent] = []

    def slots(
        self, session: ApplicantSessionContext
    ) -> tuple[ApplicantDocumentSlot, ...]:
        return self._repository.applicant_slots(session)

    def upload(
        self,
        session: ApplicantSessionContext,
        slot_id: UUID,
        expected_row_version: int,
        source: Path,
        filename: str,
        media_type: str,
    ) -> ApplicantDocumentVersion:
        slot = self._repository.require_upload(
            session.application_id, slot_id, expected_row_version
        )
        document_id = slot.document_id or uuid4()
        version_id = uuid4()
        binding = ObjectBinding(session.application_id, document_id, version_id, uuid4())
        registered: ApplicantDocumentVersion | None = None

        def register(record: StoredObjectRecord) -> None:
            nonlocal registered
            registered = self._repository.register_pending(
                slot,
                expected_row_version,
                version_id,
                document_id,
                binding,
                record,
                Path(filename).name,
            )

        try:
            self._object_store.ingest_file(
                source,
                binding,
                validator=lambda staged: validate_pdf(
                    staged,
                    declared_filename=filename,
                    declared_media_type=media_type,
                ),
                scanner=self._scanner,
                register=register,
            )
        except MalwareDetectedError:
            raise DocumentUploadRejected("The PDF could not be accepted.") from None
        except MalwareUnavailableError:
            raise DocumentScannerUnavailable("Document scanning is unavailable.") from None
        except DuplicatePlaintextError:
            raise DocumentAlreadySubmitted(
                "An identical document is already registered."
            ) from None
        except (DocumentStoreError, OSError):
            raise DocumentUploadRejected("The PDF could not be accepted.") from None
        if registered is None:
            raise DocumentUploadRejected("The PDF could not be accepted.")
        return registered

    def download(self, session: ApplicantSessionContext, slot_id: UUID) -> bytes | None:
        slot = next((item for item in self.slots(session) if item.slot_id == slot_id), None)
        if slot is None or slot.active_version_id is None:
            return None
        version = next(
            (item for item in self._repository.versions(slot_id) if item.version_id == slot.active_version_id),
            None,
        )
        if (
            version is None
            or version.status != "ACCEPTED"
            or version.classification != "APPLICANT_VISIBLE"
            or version.document_type == "RECOMMENDATION_LETTER"
            or version.recommendation_linked
        ):
            return None
        return self._object_store.decrypt_bytes(version.object_record, version.binding)

    def package(self, session: ApplicantSessionContext) -> bytes | None:
        sources = tuple(
            payload
            for slot in self.slots(session)
            if (payload := self.download(session, slot.slot_id)) is not None
        )
        if not sources:
            return None
        try:
            return build_pdf_package(sources)
        except PdfPackageError:
            return None

    @property
    def access_events(self) -> tuple[DocumentAccessEvent, ...]:
        return tuple(self._access_events)

    def internal_documents(
        self, application_id: UUID, *, actor: str, actor_group: str
    ) -> tuple[InternalDocumentSummary, ...]:
        _authorize_internal_document_access(actor, actor_group)
        return tuple(
            InternalDocumentSummary(
                slot.slot_id,
                version.version_id,
                slot.code,
                slot.label,
                version.version_number,
                version.status,
            )
            for slot, version in self._repository.internal_documents(application_id)
        )

    def internal_review_artifacts(
        self, application_id: UUID, *, actor: str, actor_group: str
    ) -> tuple[InternalReviewArtifactSummary, ...]:
        _authorize_internal_document_access(actor, actor_group)
        return self._repository.internal_review_artifacts(application_id)

    def internal_review_artifact(
        self,
        application_id: UUID,
        category: str,
        *,
        actor: str,
        actor_group: str,
    ) -> bytes | None:
        normalized = _review_artifact_category(category)
        summary = next(
            (
                item
                for item in self.internal_review_artifacts(
                    application_id, actor=actor, actor_group=actor_group
                )
                if item.category == normalized
            ),
            None,
        )
        if summary is None:
            return None
        return self.internal_download(
            application_id,
            summary.version_id,
            actor=actor,
            actor_group=actor_group,
            purpose="VIEW",
        )

    def internal_download(
        self,
        application_id: UUID,
        version_id: UUID,
        *,
        actor: str,
        actor_group: str,
        purpose: str,
    ) -> bytes | None:
        _authorize_internal_document_access(actor, actor_group)
        if purpose not in {"VIEW", "DOWNLOAD", "PACKAGE"}:
            raise ValueError("A valid document-access purpose is required.")
        event = DocumentAccessEvent(
            application_id, version_id, actor.strip(), actor_group, purpose, "REQUESTED"
        )
        self._access_events.append(event)
        version = self._repository.internal_version(application_id, version_id)
        if version is None:
            self._access_events.append(replace(event, outcome="FAILED"))
            return None
        try:
            payload = self._object_store.decrypt_bytes(version.object_record, version.binding)
        except DocumentStoreError:
            self._access_events.append(replace(event, outcome="FAILED"))
            return None
        self._access_events.append(replace(event, outcome="SUCCEEDED"))
        return payload

    def internal_package(
        self, application_id: UUID, *, actor: str, actor_group: str
    ) -> bytes | None:
        summaries = self.internal_documents(
            application_id, actor=actor, actor_group=actor_group
        )
        sources = tuple(
            payload
            for summary in summaries
            if (
                payload := self.internal_download(
                    application_id,
                    summary.version_id,
                    actor=actor,
                    actor_group=actor_group,
                    purpose="PACKAGE",
                )
            )
            is not None
        )
        if len(sources) != len(summaries) or not sources:
            return None
        try:
            return build_pdf_package(sources)
        except PdfPackageError:
            return None


def _safe_applicant_slot(slot: ApplicantDocumentSlot) -> bool:
    return (
        slot.applicant_visible
        and slot.classification == "APPLICANT_VISIBLE"
        and slot.document_type != "RECOMMENDATION_LETTER"
        and not slot.recommendation_linked
        and "RECOMMEND" not in slot.code
    )


def _authorize_internal_document_access(actor: str, actor_group: str) -> None:
    if actor_group not in {"EHF-Administrators", "EHF-Trustees"} or not actor.strip():
        raise PermissionError("Administrator or trustee authorization is required.")


def _review_artifact_category(category: str) -> str:
    normalized = category.strip().lower()
    if normalized not in REVIEW_ARTIFACT_SLOT_CODES:
        raise ValueError("A valid review-artifact category is required.")
    return normalized
