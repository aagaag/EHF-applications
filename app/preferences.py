"""Server-backed appearance preferences for authenticated EHF identities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol
from uuid import UUID


_SKINS = frozenset({"default", "high-contrast", "soft-earth", "blue"})
_CALL_MODES = frozenset({"resume-last-opened", "latest-application-deadline"})


class PreferenceValidationError(ValueError):
    """Raised when an appearance preference falls outside the shared F2 contract."""


class PreferenceRepository(Protocol):
    def load(self, identity: "Identity") -> "AppearancePreference": ...

    def save(self, identity: "Identity", preference: "AppearancePreference") -> "AppearancePreference": ...

    def load_call_navigation(self, identity: "Identity") -> "CallNavigationPreference": ...

    def save_call_navigation(
        self, identity: "Identity", preference: "CallNavigationPreference"
    ) -> "CallNavigationPreference": ...


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


@dataclass(frozen=True, slots=True)
class CallNavigationPreference:
    mode: str = "resume-last-opened"
    last_fellowship_call_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.mode not in _CALL_MODES:
            raise PreferenceValidationError("call-selection mode is not supported")
        if self.last_fellowship_call_id is not None and not isinstance(
            self.last_fellowship_call_id, UUID
        ):
            raise PreferenceValidationError("last fellowship call ID is invalid")


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

    def load_call_navigation(self, identity: Identity) -> CallNavigationPreference:
        connection = self._connection_factory()
        execute = getattr(connection, "execute", None)
        if execute is None:
            with connection as opened_connection:
                return self._load_call_navigation_with_connection(opened_connection, identity)
        return self._load_call_navigation_with_connection(connection, identity)

    def save_call_navigation(
        self, identity: Identity, preference: CallNavigationPreference
    ) -> CallNavigationPreference:
        connection = self._connection_factory()
        execute = getattr(connection, "execute", None)
        if execute is None:
            with connection as opened_connection:
                return self._save_call_navigation_with_connection(
                    opened_connection, identity, preference
                )
        return self._save_call_navigation_with_connection(connection, identity, preference)

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
        # The connection is request-scoped and not autocommitted, so the write must be
        # committed here or it is rolled back when the connection closes.
        connection.commit()
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

    @staticmethod
    def _load_call_navigation_with_connection(
        connection: Any, identity: Identity
    ) -> CallNavigationPreference:
        row = connection.execute(
            "EXEC dbo.GetCallNavigationPreference @IdentityKey=?", identity.key
        ).fetchone()
        if row is None:
            return CallNavigationPreference()
        return CallNavigationPreference(
            mode=str(row[0]),
            last_fellowship_call_id=None if row[1] is None else UUID(str(row[1])),
        )

    @staticmethod
    def _save_call_navigation_with_connection(
        connection: Any,
        identity: Identity,
        preference: CallNavigationPreference,
    ) -> CallNavigationPreference:
        row = connection.execute(
            "EXEC dbo.SetCallNavigationPreference @IdentityKey=?, @Email=?, @DisplayName=?, "
            "@DefaultCallMode=?, @LastFellowshipCallId=?, @ActorIdentity=?",
            identity.key,
            identity.email,
            identity.display_name,
            preference.mode,
            preference.last_fellowship_call_id,
            identity.key,
        ).fetchone()
        connection.commit()
        if row is None:
            return preference
        return CallNavigationPreference(
            mode=str(row[0]),
            last_fellowship_call_id=None if row[1] is None else UUID(str(row[1])),
        )


class InMemoryPreferenceRepository:
    """Identity-scoped preference store for synthetic and local acceptance runs."""

    def __init__(self) -> None:
        self._preferences: dict[str, AppearancePreference] = {}
        self._call_navigation: dict[str, CallNavigationPreference] = {}

    def load(self, identity: Identity) -> AppearancePreference:
        return self._preferences.get(identity.key, AppearancePreference())

    def save(
        self, identity: Identity, preference: AppearancePreference
    ) -> AppearancePreference:
        self._preferences[identity.key] = preference
        return preference

    def load_call_navigation(self, identity: Identity) -> CallNavigationPreference:
        return self._call_navigation.get(identity.key, CallNavigationPreference())

    def save_call_navigation(
        self, identity: Identity, preference: CallNavigationPreference
    ) -> CallNavigationPreference:
        self._call_navigation[identity.key] = preference
        return preference
