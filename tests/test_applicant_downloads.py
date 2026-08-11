from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.applicant.documents import DocumentSlotRepository
from app.auth.applicant import ApplicantSessionContext


APPLICATION_A = UUID("81000000-0000-4000-8000-000000000001")
APPLICATION_B = UUID("81000000-0000-4000-8000-000000000002")


def _context(application: UUID) -> ApplicantSessionContext:
    return ApplicantSessionContext(
        application,
        bytes(32),
        datetime.now(UTC) + timedelta(minutes=30),
        datetime.now(UTC) + timedelta(hours=24),
    )


def test_applicant_slot_listing_is_session_scoped_and_excludes_internal_slots() -> None:
    """Break caught: document checklist could list another applicant or internal material."""
    repository = DocumentSlotRepository()
    repository.add_slot(APPLICATION_A, "CV", "Curriculum vitae", required=True)
    repository.add_slot(APPLICATION_A, "INTERNAL", "Internal file", required=False, applicant_visible=False)
    repository.add_slot(APPLICATION_B, "CV", "Other curriculum vitae", required=True)

    listed = repository.applicant_slots(_context(APPLICATION_A))

    assert [slot.label for slot in listed] == ["Curriculum vitae"]
    assert "Other" not in repr(listed)
    assert "Internal" not in repr(listed)


def test_recommendation_slot_is_never_applicant_visible_even_if_requested() -> None:
    """Break caught: an administrator mistake could create an applicant-facing recommendation slot."""
    repository = DocumentSlotRepository()

    try:
        repository.add_slot(
            APPLICATION_A,
            "RECOMMENDATION",
            "Recommendation letter",
            required=False,
            applicant_visible=True,
        )
    except ValueError:
        pass

    assert repository.applicant_slots(_context(APPLICATION_A)) == ()


def test_confidential_or_recommendation_linked_slot_is_hidden_independent_of_code() -> None:
    """Break caught: a recommendation under an innocuous slot code could be exposed."""
    repository = DocumentSlotRepository()

    for attributes in (
        {"classification": "CONFIDENTIAL_RECOMMENDATION"},
        {"document_type": "RECOMMENDATION_LETTER"},
        {"recommendation_linked": True},
    ):
        with pytest.raises(ValueError):
            repository.add_slot(
                APPLICATION_A,
                "REFERENCE",
                "Reference material",
                required=False,
                applicant_visible=True,
                **attributes,
            )

    assert repository.applicant_slots(_context(APPLICATION_A)) == ()
