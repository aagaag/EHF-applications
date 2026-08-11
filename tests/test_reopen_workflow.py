from __future__ import annotations

from pathlib import Path

import pytest

from app.applicant.finalize import FinalizationBlocked
from tests.test_final_confirmation import (
    _accepted_required_document,
    _complete_sections,
    _services,
    _session,
)


def test_administrator_reopens_only_named_section_and_requires_reconfirmation(
    tmp_path: Path,
) -> None:
    """Break caught: a reopen could unlock every section or preserve stale final state."""
    finalization, review, _drafts, slots = _services(tmp_path)
    _complete_sections(review)
    _accepted_required_document(tmp_path, slots)
    original = finalization.submit(_session())

    finalization.reopen_section(
        _session().application_id,
        "identity",
        "Correction requested",
        "administrator@example.test",
        "EHF-Administrators",
    )
    identity = review.load(_session(), "identity")
    assert identity is not None
    changed = review.save(
        _session(), "identity", {"preferredName": "Corrected"}, identity.row_version
    )
    with pytest.raises(FinalizationBlocked):
        finalization.submit(_session())
    review.confirm(_session(), "identity", changed.row_version)
    replacement = finalization.submit(_session())

    assert replacement.confirmation_id != original.confirmation_id
    assert finalization.confirmations[0].superseded is True
    with pytest.raises(Exception):
        review.save(_session(), "publications", {"hIndex": 4}, 1)


def test_trustee_cannot_reopen_an_application(tmp_path: Path) -> None:
    """Break caught: a read-only trustee could reopen applicant editing."""
    finalization, _review, _drafts, _slots = _services(tmp_path)

    with pytest.raises(PermissionError):
        finalization.reopen_section(
            _session().application_id,
            "identity",
            "Not authorized",
            "trustee@example.test",
            "EHF-Trustees",
        )


def test_administrator_reopens_only_named_document_slot(tmp_path: Path) -> None:
    """Break caught: replacing one document could unlock data or other document slots."""
    finalization, review, _drafts, slots = _services(tmp_path)
    _complete_sections(review)
    _accepted_required_document(tmp_path, slots)
    finalization.submit(_session())
    cv = next(slot for slot in slots.slots_for_application(_session().application_id) if slot.code == "CV")

    reopened = finalization.reopen_document_slot(
        _session().application_id,
        cv.slot_id,
        "Please upload a clearer copy",
        "administrator@example.test",
        "EHF-Administrators",
    )

    assert reopened.code == "CV"
    assert reopened.upload_mode == "REPLACEMENT"
    assert finalization.confirmations[0].superseded is True
    with pytest.raises(FinalizationBlocked) as raised:
        finalization.submit(_session())
    assert raised.value.unresolved == ("document:CV",)
    with pytest.raises(Exception):
        review.save(_session(), "identity", {"preferredName": "Still locked"}, 1)
