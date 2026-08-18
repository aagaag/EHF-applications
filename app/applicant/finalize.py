"""Atomic, idempotent applicant finalization and narrowly scoped reopening."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.applicant.confirmations import SectionConfirmationService
from app.applicant.documents import DocumentSlotRepository
from app.applicant.documents import ApplicantDocumentSlot
from app.applicant.drafts import InMemoryDraftRepository
from app.applicant.review import ApplicantReviewService
from app.auth.applicant import ApplicantSessionContext


REQUIRED_SECTIONS = (
    "identity",
    "employment",
    "qualifications",
    "publications",
    "contribution",
)
ADMINISTRATOR_GROUP = "EHF-Administrators"


class FinalizationBlocked(RuntimeError):
    def __init__(self, unresolved: tuple[str, ...]) -> None:
        super().__init__("The application is not ready for final submission.")
        self.unresolved = unresolved


class FinalizationSessionUnavailable(RuntimeError):
    """The database rejected a final write because its applicant session disappeared."""


@dataclass(frozen=True, slots=True)
class FinalConfirmation:
    confirmation_id: UUID
    application_id: UUID
    manifest: dict[str, Any]
    manifest_sha256: str
    confirmed_at_utc: datetime
    superseded: bool = False


@dataclass(frozen=True, slots=True)
class FinalizationAuditEvent:
    application_id: UUID
    action: str
    actor: str
    scope: str | None
    reason: str | None
    occurred_at_utc: datetime


class FinalizationService:
    def __init__(
        self,
        review: ApplicantReviewService,
        drafts: InMemoryDraftRepository,
        section_confirmations: SectionConfirmationService,
        document_slots: DocumentSlotRepository,
    ) -> None:
        self._review = review
        self._drafts = drafts
        self._section_confirmations = section_confirmations
        self._document_slots = document_slots
        self._confirmations: list[FinalConfirmation] = []
        self._audit_events: list[FinalizationAuditEvent] = []

    @property
    def confirmations(self) -> tuple[FinalConfirmation, ...]:
        return tuple(self._confirmations)

    @property
    def audit_events(self) -> tuple[FinalizationAuditEvent, ...]:
        return tuple(self._audit_events)

    def preview(self, session: ApplicantSessionContext) -> dict[str, Any]:
        manifest, unresolved = self._manifest(session)
        return {"manifest": manifest, "unresolved": unresolved, "ready": not unresolved}

    def submit(self, session: ApplicantSessionContext) -> FinalConfirmation:
        manifest, unresolved = self._manifest(session)
        if unresolved:
            raise FinalizationBlocked(unresolved)
        manifest_hash = _manifest_hash(manifest)
        active = self._active(session.application_id)
        if active is not None and active.manifest_sha256 == manifest_hash:
            return active
        confirmation = FinalConfirmation(
            uuid4(), session.application_id, manifest, manifest_hash, datetime.now(UTC)
        )
        self._confirmations.append(confirmation)
        self._drafts.lock(session.application_id)
        self._audit_events.append(
            FinalizationAuditEvent(
                session.application_id,
                "FINAL_SUBMISSION",
                "APPLICANT",
                None,
                None,
                confirmation.confirmed_at_utc,
            )
        )
        return confirmation

    def reopen_section(
        self,
        application_id: UUID,
        section: str,
        reason: str,
        actor: str,
        actor_group: str,
    ) -> None:
        if actor_group != ADMINISTRATOR_GROUP:
            raise PermissionError("Administrator authorization is required.")
        if section not in REQUIRED_SECTIONS or not actor.strip() or not reason.strip():
            raise ValueError("A valid section, actor, and reason are required.")
        self._supersede_active(application_id)
        self._section_confirmations.invalidate(application_id, section)
        self._drafts.reopen(application_id, section)
        self._audit_events.append(
            FinalizationAuditEvent(
                application_id,
                "SECTION_REOPENED",
                actor.strip(),
                section,
                reason.strip(),
                datetime.now(UTC),
            )
        )

    def reopen_document_slot(
        self,
        application_id: UUID,
        slot_id: UUID,
        reason: str,
        actor: str,
        actor_group: str,
    ) -> ApplicantDocumentSlot:
        if actor_group != ADMINISTRATOR_GROUP:
            raise PermissionError("Administrator authorization is required.")
        if not actor.strip() or not reason.strip():
            raise ValueError("A valid actor and reason are required.")
        self._supersede_active(application_id)
        reopened = self._document_slots.open_slot(
            application_id, slot_id, "REPLACEMENT", actor.strip(), reason.strip()
        )
        self._audit_events.append(
            FinalizationAuditEvent(
                application_id,
                "DOCUMENT_SLOT_REOPENED",
                actor.strip(),
                reopened.code,
                reason.strip(),
                datetime.now(UTC),
            )
        )
        return reopened

    def _supersede_active(self, application_id: UUID) -> None:
        active = self._active(application_id)
        if active is None:
            raise FinalizationBlocked(("final-confirmation",))
        self._confirmations = [
            replace(item, superseded=True)
            if item.confirmation_id == active.confirmation_id
            else item
            for item in self._confirmations
        ]

    def _active(self, application_id: UUID) -> FinalConfirmation | None:
        return next(
            (
                item
                for item in reversed(self._confirmations)
                if item.application_id == application_id and not item.superseded
            ),
            None,
        )

    def _manifest(
        self, session: ApplicantSessionContext
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        unresolved: list[str] = []
        sections: list[dict[str, Any]] = []
        for section in REQUIRED_SECTIONS:
            snapshot = self._drafts.load(session.application_id, section)
            confirmation = self._section_confirmations.current(
                session.application_id, section
            )
            if (
                snapshot is None
                or confirmation is None
                or not self._section_confirmations.is_current(
                    session.application_id, section, snapshot
                )
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

        documents: list[dict[str, Any]] = []
        for slot in self._document_slots.slots_for_application(session.application_id):
            version = self._document_slots.active_version(slot)
            versions = self._document_slots.versions(slot.slot_id)
            latest = versions[-1] if versions else None
            unresolved_upload = (
                slot.upload_mode != "CLOSED"
                or (latest is not None and latest.status != "ACCEPTED")
            )
            if unresolved_upload or (slot.required and version is None):
                unresolved.append(f"document:{slot.code}")
                continue
            if version is None:
                continue
            documents.append(
                {
                    "slotCode": slot.code,
                    "slotRowVersion": slot.row_version,
                    "documentVersionId": str(version.version_id),
                    "documentVersionNumber": version.version_number,
                    "plaintextSha256": version.object_record.plaintext_sha256.hex(),
                }
            )

        return (
            {
                "schemaVersion": 1,
                "sections": sections,
                "documents": documents,
            },
            tuple(unresolved),
        )


def _manifest_hash(manifest: dict[str, Any]) -> str:
    payload = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-16le")
    return hashlib.sha256(payload).hexdigest()
