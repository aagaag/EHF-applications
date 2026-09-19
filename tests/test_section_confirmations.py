from __future__ import annotations

from uuid import UUID

from app.applicant.confirmations import SectionConfirmationService
from app.applicant.drafts import InMemoryDraftRepository


APPLICATION = UUID("70000000-0000-4000-8000-000000000001")


def test_confirmation_binds_canonical_values_and_current_row_version() -> None:
    """Break caught: clicking through could confirm a different or stale section version."""
    drafts = InMemoryDraftRepository()
    confirmations = SectionConfirmationService()
    snapshot = drafts.save(
        APPLICATION,
        "identity",
        {"fullName": "Synthetic Person", "birthMonth": 1, "birthYear": 1990},
        None,
        "APPLICANT",
    )

    confirmation = confirmations.confirm(APPLICATION, "identity", snapshot)

    assert confirmation.row_version == 1
    assert len(confirmation.canonical_sha256) == 64
    assert confirmations.is_current(APPLICATION, "identity", snapshot) is True


def test_any_later_change_visibly_invalidates_prior_confirmation() -> None:
    """Break caught: a confirmed badge could survive a post-confirmation correction."""
    drafts = InMemoryDraftRepository()
    confirmations = SectionConfirmationService()
    first = drafts.save(
        APPLICATION, "identity", {"preferredName": "First"}, None, "APPLICANT"
    )
    confirmations.confirm(APPLICATION, "identity", first)
    changed = drafts.save(
        APPLICATION, "identity", {"preferredName": "Second"}, 1, "APPLICANT"
    )

    assert confirmations.is_current(APPLICATION, "identity", changed) is False


def test_resaving_identical_content_keeps_the_section_confirmed() -> None:
    """Break caught: an autosave of unchanged content could strand a confirmed section.

    ConfirmApplicantSection keys a confirmation on the canonical hash of the saved
    content, so the stored row version is historical.  A later save that produces the
    same canonical content must therefore keep the section current, otherwise the
    applicant form (which autosaves on every edit) could never reach final submission.
    """
    drafts = InMemoryDraftRepository()
    confirmations = SectionConfirmationService()
    first = drafts.save(
        APPLICATION, "identity", {"preferredName": "Same"}, None, "APPLICANT"
    )
    confirmations.confirm(APPLICATION, "identity", first)
    resaved = drafts.save(
        APPLICATION, "identity", {"preferredName": "Same"}, 1, "APPLICANT"
    )

    assert resaved.row_version != first.row_version
    assert confirmations.is_current(APPLICATION, "identity", resaved) is True
