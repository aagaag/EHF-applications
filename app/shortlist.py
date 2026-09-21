"""Identity-bound trustee shortlist persistence for the internal report."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

RICKY_ENTRA_OBJECT_ID = UUID("7747ffa7-5193-4cc8-9221-08a1dd24b026")
MAGDA_ENTRA_OBJECT_ID = UUID("09d14671-38e1-4763-8d67-512c9787d379")
ADRIANO_ENTRA_OBJECT_ID = UUID("d5c5fb6a-f9c3-456c-97b1-20b450647f8c")
TRUSTEE_OBJECT_IDS = {
    "ricky": RICKY_ENTRA_OBJECT_ID,
    "magda": MAGDA_ENTRA_OBJECT_ID,
    "adriano": ADRIANO_ENTRA_OBJECT_ID,
}


def editable_trustee(entra_object_id: UUID | None) -> str | None:
    return next((code for code, oid in TRUSTEE_OBJECT_IDS.items() if oid == entra_object_id), None)


@dataclass(frozen=True, slots=True)
class ShortlistState:
    selections: Mapping[str, frozenset[str]]
    editable_trustee: str | None

    def selected(self, application_id: str, trustee_code: str) -> bool:
        return trustee_code in self.selections.get(application_id.casefold(), frozenset())


class ShortlistRepository(Protocol):
    def load(self, actor_identity: str, actor_group: str, entra_object_id: UUID | None) -> ShortlistState: ...
    def set(self, application_id: UUID, trustee_code: str, selected: bool, actor_identity: str, actor_group: str, entra_object_id: UUID | None) -> bool: ...


class EmptyShortlistRepository:
    def load(self, actor_identity: str, actor_group: str, entra_object_id: UUID | None) -> ShortlistState:
        del actor_identity, actor_group
        return ShortlistState({}, editable_trustee(entra_object_id))

    def set(self, application_id: UUID, trustee_code: str, selected: bool, actor_identity: str, actor_group: str, entra_object_id: UUID | None) -> bool:
        del application_id, trustee_code, selected, actor_identity, actor_group, entra_object_id
        raise PermissionError("Shortlist persistence is unavailable.")


class SqlShortlistRepository:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def load(self, actor_identity: str, actor_group: str, entra_object_id: UUID | None) -> ShortlistState:
        with self._connection_factory() as connection:
            rows = connection.execute(
                "EXEC dbo.GetInternalShortlistSelections @ActorIdentity=?, @ActorGroup=?, @ActorEntraObjectId=?",
                actor_identity, actor_group, entra_object_id,
            ).fetchall()
        selections: dict[str, set[str]] = {}
        for application_id, trustee_code, selected in rows:
            if bool(selected):
                selections.setdefault(str(application_id).casefold(), set()).add(str(trustee_code))
        return ShortlistState(
            {application_id: frozenset(codes) for application_id, codes in selections.items()},
            editable_trustee(entra_object_id),
        )

    def set(self, application_id: UUID, trustee_code: str, selected: bool, actor_identity: str, actor_group: str, entra_object_id: UUID | None) -> bool:
        with self._connection_factory() as connection:
            row = connection.execute(
                "EXEC dbo.SetInternalShortlistSelection @ApplicationId=?, @TrusteeCode=?, @IsSelected=?, @ActorIdentity=?, @ActorGroup=?, @ActorEntraObjectId=?",
                application_id, trustee_code, selected, actor_identity, actor_group, entra_object_id,
            ).fetchone()
            if row is None:
                raise LookupError("The shortlist selection was not saved.")
            connection.commit()
        return bool(row[0])
