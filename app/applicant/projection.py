"""One-session, one-application applicant-facing allowlist projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.auth.applicant import ApplicantSessionContext


_APPLICANT_FIELDS = (
    "fullName",
    "preferredName",
    "registeredEmail",
    "alternativeEmail",
    "telephone",
    "birthMonth",
    "birthYear",
    "gender",
    "genderSelfDescription",
    "institute",
    "principalInvestigator",
    "positionTitle",
    "postdoctoralEmploymentStatus",
    "employmentStartDate",
    "employmentEndDate",
    "futureStartDate",
    "researchArea",
    "clinicalWorkPercent",
    "firstAuthorDeclaration",
    "degreeCategory",
    "phdDate",
    "firstAuthorPaperCount",
    "lastAuthorPaperCount",
    "totalPaperCount",
    "hIndex",
    "applicantReportedCitationTotal",
    "orcid",
    "googleScholarProfileUrl",
    "noGoogleScholarProfile",
    "googleScholarCitationTotal",
    "contributionStatement",
    "locked",
)
_SECTION_FIELDS = ("confirmed", "missing", "status", "editable")
_DOCUMENT_FIELDS = (
    "documentId",
    "versionId",
    "slotCode",
    "displayName",
    "sha256",
    "byteSize",
    "mediaType",
    "status",
    "uploadOpen",
    "replacementOpen",
    "rowVersion",
)


@dataclass(slots=True)
class _RawProjection:
    applicant: dict[str, Any]
    sections: dict[str, dict[str, Any]]
    documents: tuple[dict[str, Any], ...]
    internal: dict[str, Any]


class InMemoryApplicantProjectionRepository:
    """Synthetic repository that deliberately retains internal fields for leak tests."""

    def __init__(self) -> None:
        self._records: dict[UUID, _RawProjection] = {}

    def add_application(
        self,
        application_id: UUID,
        *,
        applicant: dict[str, Any],
        sections: dict[str, dict[str, Any]],
        documents: tuple[dict[str, Any], ...],
        internal: dict[str, Any] | None = None,
    ) -> None:
        self._records[application_id] = _RawProjection(
            dict(applicant),
            {name: dict(value) for name, value in sections.items()},
            tuple(dict(document) for document in documents),
            dict(internal or {}),
        )

    def load(self, application_id: UUID) -> _RawProjection | None:
        return self._records.get(application_id)


class ApplicantProjectionService:
    """Serialize only approved fields from the application bound to the session."""

    def __init__(self, repository: InMemoryApplicantProjectionRepository) -> None:
        self._repository = repository

    def load(self, session: ApplicantSessionContext) -> dict[str, Any] | None:
        raw = self._repository.load(session.application_id)
        if raw is None:
            return None
        documents = [
            visible
            for document in raw.documents
            if (visible := _visible_document(document)) is not None
        ]
        return {
            "applicant": _allow(raw.applicant, _APPLICANT_FIELDS),
            "sections": {
                code: _allow(section, _SECTION_FIELDS)
                for code, section in raw.sections.items()
                if _safe_code(code)
            },
            "documents": documents,
        }

    def visible_document(
        self, session: ApplicantSessionContext, document_id: str
    ) -> dict[str, Any] | None:
        raw = self._repository.load(session.application_id)
        if raw is None:
            return None
        for document in raw.documents:
            if document.get("documentId") == document_id:
                return _visible_document(document)
        return None


def _visible_document(document: dict[str, Any]) -> dict[str, Any] | None:
    if document.get("classification") != "APPLICANT_VISIBLE":
        return None
    if document.get("documentType") == "RECOMMENDATION_LETTER":
        return None
    if document.get("recommendationLinked") is True:
        return None
    return _allow(document, _DOCUMENT_FIELDS)


def _allow(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


def _safe_code(value: str) -> bool:
    return bool(value) and len(value) <= 80 and all(
        character.isascii() and (character.isalnum() or character in "_-")
        for character in value
    )
