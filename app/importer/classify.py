"""Deterministic, review-only document classification suggestions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from app.documents.classification import DocumentClassification


class DocumentType(StrEnum):
    """Document-type suggestions that never authorize a visibility decision."""

    RECOMMENDATION_LETTER = "RECOMMENDATION_LETTER"
    CV = "CV"
    PUBLICATION_LIST = "PUBLICATION_LIST"
    RESEARCH_PLAN = "RESEARCH_PLAN"
    COVER_LETTER = "COVER_LETTER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ClassificationSuggestion:
    """Evidence-based suggestion pending a separate accountable human decision."""

    document_type: DocumentType
    suggested_confidentiality: DocumentClassification | None
    initial_classification: DocumentClassification
    recommendation_signal: bool
    evidence_codes: tuple[str, ...]


def suggest_classification(filename: str, first_page_text: str | None = None) -> ClassificationSuggestion:
    """Classify deterministic text signals without reading, changing, or authorizing the source."""
    filename_text = _normalize(filename)
    page_text = _normalize(first_page_text or "")
    evidence = _recommendation_evidence(filename_text, page_text)
    if evidence:
        return ClassificationSuggestion(
            document_type=DocumentType.RECOMMENDATION_LETTER,
            suggested_confidentiality=DocumentClassification.CONFIDENTIAL_RECOMMENDATION,
            initial_classification=DocumentClassification.UNREVIEWED,
            recommendation_signal=True,
            evidence_codes=tuple(evidence),
        )

    document_type, evidence_code = _applicant_document_signal(filename_text, page_text)
    suggested_confidentiality = (
        DocumentClassification.APPLICANT_VISIBLE
        if document_type is not DocumentType.UNKNOWN
        else None
    )
    return ClassificationSuggestion(
        document_type=document_type,
        suggested_confidentiality=suggested_confidentiality,
        initial_classification=DocumentClassification.UNREVIEWED,
        recommendation_signal=False,
        evidence_codes=(evidence_code,),
    )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.casefold())).strip()


def _recommendation_evidence(filename: str, text: str) -> list[str]:
    evidence: list[str] = []
    if "recommendation" in filename:
        evidence.append("FILENAME_RECOMMENDATION")
    elif "reference letter" in filename or "reference" in filename:
        evidence.append("FILENAME_REFERENCE_LETTER")
    elif "referee" in filename:
        evidence.append("FILENAME_REFEREE")
    elif (
        "support letter" in filename
        or "letter of support" in filename
        or "letter of recommend" in filename
        or re.search(r"(?:^| )lor(?: |$)", filename)
        or re.search(r"(?:^| )ref ?let", filename)
    ):
        evidence.append("FILENAME_SUPPORT_OR_LOR")
    if (
        re.search(r"\bi (?:strongly |highly |wholeheartedly |enthusiastically )?recommend\b", text)
        or "letter of recommendation" in text
        or "recommendation for" in text
    ):
        evidence.append("TEXT_RECOMMENDATION")
    if "referee report" in text or "referee letter" in text or "as a referee" in text:
        evidence.append("TEXT_REFEREE")
    if "forwarded" in text:
        evidence.append("TEXT_FORWARDED")
    return evidence


def _applicant_document_signal(filename: str, text: str) -> tuple[DocumentType, str]:
    if filename.split(" ", 1)[0] == "cv" or "curriculum vitae" in text:
        return DocumentType.CV, "CV_SIGNAL"
    if "publication" in filename or "selected publications" in text:
        return DocumentType.PUBLICATION_LIST, "PUBLICATION_SIGNAL"
    if (
        "research plan" in filename
        or "research plan" in text
        or "research proposal" in text
        or "proposal" in filename
    ):
        return DocumentType.RESEARCH_PLAN, "RESEARCH_PLAN_SIGNAL"
    if "cover letter" in filename or "dear selection committee" in text:
        return DocumentType.COVER_LETTER, "COVER_LETTER_SIGNAL"
    return DocumentType.UNKNOWN, "NO_CLASSIFICATION_SIGNAL"
