"""Task 6 contract tests for server-backed EHF appearance preferences."""

from __future__ import annotations

from dataclasses import dataclass


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

    def execute(self, sql: str, *parameters: object) -> "RecordingConnection":
        self.executed.append((sql, parameters))
        return self

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


def test_sql_preference_repository_reads_and_writes_only_the_current_identity() -> None:
    """Break caught: preferences could be held in browser state or written for another identity."""
    from app.preferences import AppearancePreference, Identity, SqlPreferenceRepository

    connection = RecordingConnection([])
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
