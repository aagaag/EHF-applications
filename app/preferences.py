"""Server-backed appearance preferences for authenticated EHF identities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


_SKINS = frozenset({"default", "high-contrast", "soft-earth", "blue"})


class PreferenceValidationError(ValueError):
    """Raised when an appearance preference falls outside the shared F2 contract."""


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
        return AppearancePreference(
            skin=str(row[0]),
            invert=bool(row[1]),
            compact=bool(row[2]),
            reduce_motion=bool(row[3]),
        )
