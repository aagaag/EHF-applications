"""Validated autosave and explicit-confirmation orchestration."""

from __future__ import annotations

from typing import Any

from app.applicant.confirmations import SectionConfirmation, SectionConfirmationService
from app.applicant.drafts import DraftConflict, DraftSnapshot, InMemoryDraftRepository
from app.applicant.fields import field_metadata, validate_section
from app.auth.applicant import ApplicantSessionContext


class ApplicantReviewService:
    def __init__(
        self,
        drafts: InMemoryDraftRepository,
        confirmations: SectionConfirmationService,
    ) -> None:
        self._drafts = drafts
        self._confirmations = confirmations

    def metadata(self) -> tuple[dict[str, Any], ...]:
        return field_metadata()

    def load(
        self, session: ApplicantSessionContext, section: str
    ) -> DraftSnapshot | None:
        return self._drafts.load(session.application_id, section)

    def save(
        self,
        session: ApplicantSessionContext,
        section: str,
        values: dict[str, object],
        expected_row_version: int | None,
    ) -> DraftSnapshot:
        normalized = validate_section(section, values, final=False)
        return self._drafts.save(
            session.application_id,
            section,
            normalized,
            expected_row_version,
            "APPLICANT",
        )

    def confirm(
        self,
        session: ApplicantSessionContext,
        section: str,
        expected_row_version: int,
    ) -> SectionConfirmation:
        snapshot = self.load(session, section)
        if snapshot is None or snapshot.row_version != expected_row_version:
            raise DraftConflict("The applicant draft changed before confirmation.")
        validate_section(section, snapshot.values, final=True)
        return self._confirmations.confirm(session.application_id, section, snapshot)

    def is_current(
        self, session: ApplicantSessionContext, section: str, snapshot: DraftSnapshot
    ) -> bool:
        return self._confirmations.is_current(session.application_id, section, snapshot)
