"""Fail-closed classification decisions for imported EHF documents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DocumentClassification(StrEnum):
    """The only document visibility classifications accepted by the importer."""

    UNREVIEWED = "UNREVIEWED"
    APPLICANT_VISIBLE = "APPLICANT_VISIBLE"
    CONFIDENTIAL_RECOMMENDATION = "CONFIDENTIAL_RECOMMENDATION"
    INTERNAL_ADMINISTRATIVE = "INTERNAL_ADMINISTRATIVE"


class ClassificationDecisionError(ValueError):
    """Raised when a human classification decision is incomplete or unsafe."""


@dataclass(frozen=True, slots=True)
class ClassificationDecision:
    """An accountable human classification decision, not a classifier result."""

    administrator_id: str
    classification: DocumentClassification
    occurred_at: datetime
    reason: str | None


def is_applicant_visible(classification: DocumentClassification) -> bool:
    """Return visibility only for an explicit approved applicant-visible classification."""
    return classification is DocumentClassification.APPLICANT_VISIBLE


def record_classification_decision(
    suggestion: object,
    *,
    administrator_id: str,
    classification: DocumentClassification,
    occurred_at: datetime,
    reason: str | None = None,
) -> ClassificationDecision:
    """Record a human decision while refusing recommendation exposure and unaccountable overrides."""
    if not administrator_id.strip():
        raise ClassificationDecisionError("administrator identity is required")
    if not isinstance(classification, DocumentClassification):
        raise ClassificationDecisionError("explicit document classification is required")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ClassificationDecisionError("classification timestamp must be timezone-aware")
    normalized_reason = reason.strip() if reason is not None else None
    recommendation_signal = bool(getattr(suggestion, "recommendation_signal", False))
    if recommendation_signal and classification is DocumentClassification.APPLICANT_VISIBLE:
        raise ClassificationDecisionError("recommendation signal cannot be classified applicant-visible")
    if recommendation_signal and classification is not DocumentClassification.CONFIDENTIAL_RECOMMENDATION:
        if not normalized_reason:
            raise ClassificationDecisionError("a reason is required when overriding a recommendation signal")
    return ClassificationDecision(
        administrator_id=administrator_id.strip(),
        classification=classification,
        occurred_at=occurred_at,
        reason=normalized_reason,
    )
