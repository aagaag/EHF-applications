"""Server-backed appearance preferences for authenticated EHF identities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


_SKINS = frozenset({"default", "high-contrast", "soft-earth", "blue"})


class PreferenceValidationError(ValueError):
    """Raised when an appearance preference falls outside the shared F2 contract."""


class PreferenceRepository(Protocol):
    def load(self, identity: "Identity") -> "AppearancePreference": ...

    def save(self, identity: "Identity", preference: "AppearancePreference") -> "AppearancePreference": ...


@dataclass(frozen=True, slots=True)
class Identity:
    key: str
    email: str
    display_name: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.key, self.email, self.display_name)):
            raise PreferenceValidationError("identity fields are required")
        if len(self.key) > 255 or len(self.email) > 320 or len(self.display_name) > 320:
            raise PreferenceValidationError("identity field is too long")


@dataclass(frozen=True, slots=True)
class AppearancePreference:
    skin: str = "default"
    invert: bool = False
    compact: bool = False
    reduce_motion: bool = False

    def __post_init__(self) -> None:
        if self.skin not in _SKINS:
            raise PreferenceValidationError("skin is not a supported ISAB skin")
        if not all(isinstance(value, bool) for value in (self.invert, self.compact, self.reduce_motion)):
            raise PreferenceValidationError("appearance switches must be boolean")


class SqlPreferenceRepository:
    """Use the audited, ownership-chained SQL procedure rather than browser storage."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def save(self, identity: Identity, preference: AppearancePreference) -> AppearancePreference:
        """Persist the current identity's presentation choices through the approved procedure."""
        connection = self._connection_factory()
        execute = getattr(connection, "execute", None)
        if execute is None:
            with connection as opened_connection:
                return self._save_with_connection(opened_connection, identity, preference)
        return self._save_with_connection(connection, identity, preference)

    def load(self, identity: Identity) -> AppearancePreference:
        connection = self._connection_factory()
        execute = getattr(connection, "execute", None)
        if execute is None:
            with connection as opened_connection:
                return self._load_with_connection(opened_connection, identity)
        return self._load_with_connection(connection, identity)

    @staticmethod
    def _load_with_connection(connection: Any, identity: Identity) -> AppearancePreference:
        row = connection.execute("EXEC dbo.GetUserPreference @IdentityKey=?", identity.key).fetchone()
        return AppearancePreference() if row is None else SqlPreferenceRepository._decode_row(row)

    @staticmethod
    def _save_with_connection(
        connection: Any, identity: Identity, preference: AppearancePreference
    ) -> AppearancePreference:
        cursor = connection.execute(
            "EXEC dbo.SetUserPreference @IdentityKey=?, @Email=?, @DisplayName=?, "
            "@Skin=?, @InvertColors=?, @CompactDensity=?, @ReduceMotion=?, @ActorIdentity=?",
            identity.key,
            identity.email,
            identity.display_name,
            preference.skin,
            preference.invert,
            preference.compact,
            preference.reduce_motion,
            identity.key,
        )
        row = cursor.fetchone()
        if row is None:
            return preference
        return SqlPreferenceRepository._decode_row(row)

    @staticmethod
    def _decode_row(row: Any) -> AppearancePreference:
        return AppearancePreference(
            skin=str(row[4]),
            invert=bool(row[5]),
            compact=bool(row[6]),
            reduce_motion=bool(row[7]),
        )


class InMemoryPreferenceRepository:
    """Identity-scoped preference store for synthetic and local acceptance runs."""

    def __init__(self) -> None:
        self._preferences: dict[str, AppearancePreference] = {}

    def load(self, identity: Identity) -> AppearancePreference:
        return self._preferences.get(identity.key, AppearancePreference())

    def save(
        self, identity: Identity, preference: AppearancePreference
    ) -> AppearancePreference:
        self._preferences[identity.key] = preference
        return preference
