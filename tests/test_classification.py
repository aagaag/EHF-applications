from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.documents.classification import (
    ClassificationDecisionError,
    DocumentClassification,
    is_applicant_visible,
    record_classification_decision,
)
from app.importer.classify import DocumentType, suggest_classification


@pytest.mark.parametrize(
    ("filename", "first_page_text", "evidence_code"),
    [
        ("reference-letter.pdf", "", "FILENAME_REFERENCE_LETTER"),
        ("support.pdf", "I recommend the candidate without reservation.", "TEXT_RECOMMENDATION"),
        ("forwarded.pdf", "Forwarded message\nReferee letter attached", "TEXT_REFEREE"),
        ("Synthetic Applicant recommendation.pdf", "", "FILENAME_RECOMMENDATION"),
        ("Support Letter.pdf", "", "FILENAME_SUPPORT_OR_LOR"),
        ("LoR_Candidate.pdf", "", "FILENAME_SUPPORT_OR_LOR"),
        ("RefLetby_PI.pdf", "", "FILENAME_SUPPORT_OR_LOR"),
        ("cv.pdf", "To the selection committee: I strongly recommend this applicant.", "TEXT_RECOMMENDATION"),
    ],
)
def test_recommendation_signals_remain_unreviewed_and_never_applicant_visible(
    filename: str, first_page_text: str, evidence_code: str
) -> None:
    """Break caught: a filename or forwarding path could expose a confidential recommendation."""
    suggestion = suggest_classification(filename, first_page_text)

    assert suggestion.initial_classification is DocumentClassification.UNREVIEWED
    assert suggestion.document_type is DocumentType.RECOMMENDATION_LETTER
    assert suggestion.suggested_confidentiality is DocumentClassification.CONFIDENTIAL_RECOMMENDATION
    assert suggestion.recommendation_signal is True
    assert evidence_code in suggestion.evidence_codes
    assert is_applicant_visible(suggestion.initial_classification) is False

    with pytest.raises(ClassificationDecisionError, match="recommendation signal"):
        record_classification_decision(
            suggestion,
            administrator_id="administrator-1",
            classification=DocumentClassification.APPLICANT_VISIBLE,
            occurred_at=datetime(2026, 8, 10, tzinfo=UTC),
        )

    decision = record_classification_decision(
        suggestion,
        administrator_id="administrator-1",
        classification=DocumentClassification.CONFIDENTIAL_RECOMMENDATION,
        occurred_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    assert is_applicant_visible(decision.classification) is False


@pytest.mark.parametrize(
    ("filename", "first_page_text", "document_type", "confidence"),
    [
        ("CV.pdf", "", DocumentType.CV, DocumentClassification.APPLICANT_VISIBLE),
        ("cv.pdf", "Curriculum vitae", DocumentType.CV, DocumentClassification.APPLICANT_VISIBLE),
        ("publications.pdf", "Selected publications", DocumentType.PUBLICATION_LIST, DocumentClassification.APPLICANT_VISIBLE),
        ("research-plan.pdf", "", DocumentType.RESEARCH_PLAN, DocumentClassification.APPLICANT_VISIBLE),
        ("proposal.pdf", "Research plan", DocumentType.RESEARCH_PLAN, DocumentClassification.APPLICANT_VISIBLE),
        ("letter.pdf", "Dear selection committee, I am applying", DocumentType.COVER_LETTER, DocumentClassification.APPLICANT_VISIBLE),
        ("attachment.pdf", "Unrelated material", DocumentType.UNKNOWN, None),
    ],
)
def test_non_recommendation_suggestions_are_explainable_but_do_not_authorize_visibility(
    filename: str,
    first_page_text: str,
    document_type: DocumentType,
    confidence: DocumentClassification | None,
) -> None:
    """Break caught: ordinary-looking documents could bypass the required human classification review."""
    suggestion = suggest_classification(filename, first_page_text)

    assert suggestion.document_type is document_type
    assert suggestion.suggested_confidentiality is confidence
    assert suggestion.initial_classification is DocumentClassification.UNREVIEWED
    assert is_applicant_visible(suggestion.initial_classification) is False
    assert suggestion.evidence_codes


def test_non_confidential_override_requires_identity_timestamp_and_reason() -> None:
    """Break caught: an administrator could override a recommendation signal without accountable review."""
    suggestion = suggest_classification("reference.pdf", "")
    timestamp = datetime(2026, 8, 10, tzinfo=UTC)

    with pytest.raises(ClassificationDecisionError, match="administrator identity"):
        record_classification_decision(
            suggestion,
            administrator_id=" ",
            classification=DocumentClassification.INTERNAL_ADMINISTRATIVE,
            occurred_at=timestamp,
            reason="Reviewed as administrative correspondence",
        )
    with pytest.raises(ClassificationDecisionError, match="reason"):
        record_classification_decision(
            suggestion,
            administrator_id="administrator-1",
            classification=DocumentClassification.INTERNAL_ADMINISTRATIVE,
            occurred_at=timestamp,
        )
    with pytest.raises(ClassificationDecisionError, match="timezone-aware"):
        record_classification_decision(
            suggestion,
            administrator_id="administrator-1",
            classification=DocumentClassification.INTERNAL_ADMINISTRATIVE,
            occurred_at=datetime(2026, 8, 10),
            reason="Reviewed as administrative correspondence",
        )
