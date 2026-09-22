"""Task 6 contract tests for server-backed EHF appearance preferences."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


def test_preference_model_accepts_only_the_shared_four_skins() -> None:
    """Break caught: a page-specific skin could escape the common ISAB tokens."""
    from app.preferences import AppearancePreference, PreferenceValidationError

    assert AppearancePreference(skin="default").skin == "default"
    assert AppearancePreference(skin="high-contrast").skin == "high-contrast"
    assert AppearancePreference(skin="soft-earth").skin == "soft-earth"
    assert AppearancePreference(skin="blue").skin == "blue"

    try:
        AppearancePreference(skin="purple")
    except PreferenceValidationError:
        pass
    else:
        raise AssertionError("unknown skins must fail closed")


@dataclass
class RecordingConnection:
    executed: list[tuple[str, tuple[object, ...]]]

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0

    def execute(self, sql: str, *parameters: object) -> "RecordingConnection":
        self.executed.append((sql, parameters))
        return self

    def commit(self) -> None:
        self.commits += 1

    def fetchone(self) -> tuple[object, ...]:
        return (
            "preference-001",
            "entra:person-001",
            "person@example.org",
            "Preview Person",
            "blue",
            True,
            True,
            False,
        )


def test_sql_preference_repository_commits_the_write_it_reports_as_saved() -> None:
    """Break caught: a reported preference save could be rolled back at request end."""
    from app.preferences import AppearancePreference, Identity, SqlPreferenceRepository

    connection = RecordingConnection()
    identity = Identity(
        key="entra:person-001", email="person@example.org", display_name="Preview Person"
    )
    repository = SqlPreferenceRepository(lambda: connection)

    repository.save(
        identity,
        AppearancePreference(skin="blue", invert=True, compact=True, reduce_motion=False),
    )

    assert connection.commits == 1


def test_sql_preference_repository_reads_and_writes_only_the_current_identity() -> None:
    """Break caught: preferences could be held in browser state or written for another identity."""
    from app.preferences import AppearancePreference, Identity, SqlPreferenceRepository

    connection = RecordingConnection()
    identity = Identity(
        key="entra:person-001",
        email="person@example.org",
        display_name="Preview Person",
    )
    repository = SqlPreferenceRepository(lambda: connection)

    saved = repository.save(
        identity,
        AppearancePreference(skin="blue", invert=True, compact=True, reduce_motion=False),
    )

    assert saved.skin == "blue"
    assert saved.invert is True
    assert saved.compact is True
    assert saved.reduce_motion is False
    assert len(connection.executed) == 1
    sql, parameters = connection.executed[0]
    assert "dbo.SetUserPreference" in sql
    assert parameters[0] == identity.key
    assert parameters[-1] == identity.key
    assert "localStorage" not in sql

    loaded = repository.load(identity)
    assert loaded == saved
    load_sql, load_parameters = connection.executed[1]
    assert "dbo.GetUserPreference" in load_sql
    assert load_parameters == (identity.key,)


def test_call_navigation_preference_defaults_to_resuming_the_last_opened_call() -> None:
    """Break caught: a new identity could default to an undocumented call-selection rule."""
    from app.preferences import CallNavigationPreference

    preference = CallNavigationPreference()

    assert preference.mode == "resume-last-opened"
    assert preference.last_fellowship_call_id is None


def test_call_navigation_preference_accepts_only_the_two_supported_modes() -> None:
    """Break caught: an unsupported mode could make default-call resolution ambiguous."""
    from app.preferences import CallNavigationPreference, PreferenceValidationError

    call_id = UUID("26000000-0000-4000-8000-000000000001")
    assert CallNavigationPreference("latest-application-deadline", call_id).mode == (
        "latest-application-deadline"
    )
    try:
        CallNavigationPreference("first-database-row", call_id)
    except PreferenceValidationError:
        pass
    else:
        raise AssertionError("unsupported call-selection modes must fail closed")


def test_in_memory_call_navigation_preference_is_scoped_by_identity() -> None:
    """Break caught: one reviewer could inherit another reviewer's last-opened call."""
    from app.preferences import (
        CallNavigationPreference,
        Identity,
        InMemoryPreferenceRepository,
    )

    repository = InMemoryPreferenceRepository()
    first = Identity("entra:first", "first@example.org", "First")
    second = Identity("entra:second", "second@example.org", "Second")
    call_id = UUID("26000000-0000-4000-8000-000000000001")

    repository.save_call_navigation(
        first, CallNavigationPreference("latest-application-deadline", call_id)
    )

    assert repository.load_call_navigation(first).last_fellowship_call_id == call_id
    assert repository.load_call_navigation(second) == CallNavigationPreference()
