from __future__ import annotations

from uuid import UUID

import pytest

from app.applicant.drafts import DraftConflict, DraftLocked, InMemoryDraftRepository


APPLICATION = UUID("60000000-0000-4000-8000-000000000001")


def test_autosave_commits_then_records_minimal_correction_history() -> None:
    """Break caught: the UI could report saved without a committed version and provenance."""
    repository = InMemoryDraftRepository()

    first = repository.save(
        APPLICATION,
        "identity",
        {"preferredName": "First"},
        expected_row_version=None,
        source="APPLICANT",
    )
    second = repository.save(
        APPLICATION,
        "identity",
        {"preferredName": "Second"},
        expected_row_version=first.row_version,
        source="APPLICANT",
    )

    assert first.row_version == 1
    assert second.row_version == 2
    assert repository.load(APPLICATION, "identity") == second
    assert [(change.field, change.before, change.after) for change in repository.corrections] == [
        ("preferredName", None, "First"),
        ("preferredName", "First", "Second"),
    ]


def test_stale_autosave_fails_without_overwriting_current_values() -> None:
    """Break caught: a stale browser could silently overwrite a newer correction."""
    repository = InMemoryDraftRepository()
    current = repository.save(
        APPLICATION, "identity", {"preferredName": "Current"}, None, "APPLICANT"
    )

    with pytest.raises(DraftConflict):
        repository.save(
            APPLICATION, "identity", {"preferredName": "Stale"}, 0, "APPLICANT"
        )

    assert repository.load(APPLICATION, "identity") == current


def test_locked_application_rejects_writes_until_exact_section_is_reopened() -> None:
    """Break caught: final submission could remain globally editable or reopen too broadly."""
    repository = InMemoryDraftRepository()
    repository.lock(APPLICATION)

    with pytest.raises(DraftLocked):
        repository.save(APPLICATION, "identity", {"preferredName": "Blocked"}, None, "APPLICANT")

    repository.reopen(APPLICATION, "identity")
    saved = repository.save(
        APPLICATION, "identity", {"preferredName": "Allowed"}, None, "APPLICANT"
    )
    with pytest.raises(DraftLocked):
        repository.save(APPLICATION, "publications", {"hIndex": 1}, None, "APPLICANT")

    assert saved.values["preferredName"] == "Allowed"


def test_administrator_correction_keeps_its_distinct_provenance() -> None:
    """Break caught: staff corrections could be misattributed to the applicant."""
    repository = InMemoryDraftRepository()
    repository.save(
        APPLICATION,
        "identity",
        {"telephone": "+41 00 000 00 00"},
        None,
        "ADMINISTRATOR",
    )

    assert repository.corrections[-1].source == "ADMINISTRATOR"
