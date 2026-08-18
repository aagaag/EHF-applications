"""Validated autosave and explicit-confirmation orchestration."""

from __future__ import annotations

from typing import Any

from app.applicant.confirmations import SectionConfirmation, SectionConfirmationService
from app.applicant.drafts import DraftConflict, DraftSnapshot, InMemoryDraftRepository
from app.applicant.fields import (
    FieldValidationError,
    field_metadata,
    upgrade_legacy_section,
    validate_section,
)
from app.applicant.publications import (
    InvalidDoi,
    PublicationLookupReceipts,
    normalize_doi,
)
from app.auth.applicant import ApplicantSessionContext


class ApplicantReviewService:
    def __init__(
        self,
        drafts: InMemoryDraftRepository,
        confirmations: SectionConfirmationService,
        publication_receipts: PublicationLookupReceipts,
    ) -> None:
        self._drafts = drafts
        self._confirmations = confirmations
        self._publication_receipts = publication_receipts

    def metadata(self) -> tuple[dict[str, Any], ...]:
        return field_metadata()

    def load(
        self, session: ApplicantSessionContext, section: str
    ) -> DraftSnapshot | None:
        snapshot = self._drafts.load(session.application_id, section)
        return self._present(snapshot) if snapshot is not None else None

    def save(
        self,
        session: ApplicantSessionContext,
        section: str,
        values: dict[str, object],
        expected_row_version: int | None,
    ) -> DraftSnapshot:
        prepared = self._verified_publications(session, section, values)
        normalized = validate_section(section, prepared, final=False)
        persistence_values = self._dual_format(
            section,
            normalized,
            self._drafts.load(session.application_id, section),
        )
        saved = self._drafts.save(
            session.application_id,
            section,
            persistence_values,
            expected_row_version,
            "APPLICANT",
        )
        return self._present(saved)

    def confirm(
        self,
        session: ApplicantSessionContext,
        section: str,
        expected_row_version: int,
    ) -> SectionConfirmation:
        snapshot = self._drafts.load(session.application_id, section)
        if snapshot is None or snapshot.row_version != expected_row_version:
            raise DraftConflict("The applicant draft changed before confirmation.")
        validate_section(section, upgrade_legacy_section(section, snapshot.values), final=True)
        return self._confirmations.confirm(session.application_id, section, snapshot)

    def is_current(
        self, session: ApplicantSessionContext, section: str, snapshot: DraftSnapshot
    ) -> bool:
        raw = self._drafts.load(session.application_id, section)
        return raw is not None and self._confirmations.is_current(
            session.application_id, section, raw
        )

    def publication_lookup_receipt(
        self, session: ApplicantSessionContext, doi: object
    ) -> str:
        return self._publication_receipts.issue(session.application_id, doi)

    @staticmethod
    def _present(snapshot: DraftSnapshot) -> DraftSnapshot:
        return DraftSnapshot(
            snapshot.application_id,
            snapshot.section,
            upgrade_legacy_section(snapshot.section, snapshot.values),
            snapshot.row_version,
            snapshot.return_reason,
            snapshot.returned_at_utc,
        )

    def _verified_publications(
        self,
        session: ApplicantSessionContext,
        section: str,
        values: dict[str, object],
    ) -> dict[str, object]:
        if section != "publications" or "publications" not in values:
            return values
        rows = values["publications"]
        if not isinstance(rows, list):
            return values
        current = self._drafts.load(session.application_id, section)
        existing: set[str] = set()
        if current is not None:
            for row in current.values.get("publications", []):
                if isinstance(row, dict):
                    try:
                        existing.add(normalize_doi(row.get("doi")))
                    except InvalidDoi:
                        pass
        stripped: list[object] = []
        for row in rows:
            if not isinstance(row, dict):
                stripped.append(row)
                continue
            allowed = {"doi", "confirmed", "lookupReceipt"}
            if not set(row).issubset(allowed):
                stripped.append(row)
                continue
            try:
                doi = normalize_doi(row.get("doi"))
            except InvalidDoi:
                stripped.append(row)
                continue
            receipt = row.get("lookupReceipt")
            verified = (
                receipt is None and doi in existing
            ) or self._publication_receipts.valid(
                session.application_id, doi, receipt
            )
            if not verified:
                raise FieldValidationError(
                    {
                        "publications": (
                            "Look up and confirm every new DOI before saving it."
                        )
                    }
                )
            stripped.append({"doi": doi, "confirmed": row.get("confirmed")})
        prepared = dict(values)
        prepared["publications"] = stripped
        return prepared

    @staticmethod
    def _dual_format(
        section: str,
        values: dict[str, object],
        current: DraftSnapshot | None,
    ) -> dict[str, object]:
        """Keep v16 readers safe while v17 is the rollback-compatible release."""
        compatible = dict(values)
        if section == "identity":
            compatible["genderSelfDescription"] = None
        elif section == "qualifications":
            degrees = compatible.get("degrees")
            degree_rows = degrees if isinstance(degrees, list) else []
            types = {
                row.get("degreeType")
                for row in degree_rows
                if isinstance(row, dict)
            }
            if "MD" in types and "PhD" in types:
                compatible["degreeCategory"] = "MD_PHD"
            elif "PhD" in types:
                compatible["degreeCategory"] = "PHD"
            elif "MD" in types:
                compatible["degreeCategory"] = "MD"
            else:
                compatible["degreeCategory"] = None
            compatible["phdDate"] = next(
                (
                    row.get("conferralDate")
                    for row in degree_rows
                    if isinstance(row, dict) and row.get("degreeType") == "PhD"
                ),
                None,
            )
        elif section == "publications":
            has_profile = compatible.get("hasGoogleScholarProfile")
            compatible["noGoogleScholarProfile"] = (
                not has_profile if isinstance(has_profile, bool) else None
            )
            if (
                current is not None
                and "googleScholarCitationTotal" in current.values
            ):
                compatible["googleScholarCitationTotal"] = current.values[
                    "googleScholarCitationTotal"
                ]
        return compatible
