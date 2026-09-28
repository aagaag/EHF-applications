"""Call-scoped decisions to advance applicants to the second selection stage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SecondStageState:
    selected_application_ids: frozenset[str]

    def selected(self, application_id: str) -> bool:
        return application_id.casefold() in {item.casefold() for item in self.selected_application_ids}


class SecondStageRepository(Protocol):
    def load(self, call_id: UUID, actor_group: str) -> SecondStageState: ...
    def set(self, call_id: UUID, application_id: UUID, selected: bool,
            actor_identity: str, actor_group: str, entra_object_id: UUID | None) -> bool: ...


class EmptySecondStageRepository:
    def load(self, call_id: UUID, actor_group: str) -> SecondStageState:
        del call_id, actor_group
        return SecondStageState(frozenset())

    def set(self, call_id: UUID, application_id: UUID, selected: bool,
            actor_identity: str, actor_group: str, entra_object_id: UUID | None) -> bool:
        del call_id, application_id, selected, actor_identity, actor_group, entra_object_id
        raise PermissionError("Second-stage decisions are unavailable.")


class SqlSecondStageRepository:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def load(self, call_id: UUID, actor_group: str) -> SecondStageState:
        with self._connection_factory() as connection:
            rows = connection.execute(
                "EXEC dbo.GetCallSecondStageSelections @FellowshipCallId=?, @ActorGroup=?",
                call_id, actor_group,
            ).fetchall()
        return SecondStageState(frozenset(str(row[0]) for row in rows))

    def set(self, call_id: UUID, application_id: UUID, selected: bool,
            actor_identity: str, actor_group: str, entra_object_id: UUID | None) -> bool:
        with self._connection_factory() as connection:
            row = connection.execute(
                "EXEC dbo.SetCallSecondStageSelection @FellowshipCallId=?, @ApplicationId=?, "
                "@IsSelected=?, @ActorIdentity=?, @ActorGroup=?, @ActorEntraObjectId=?",
                call_id, application_id, selected, actor_identity, actor_group, entra_object_id,
            ).fetchone()
            if row is None:
                raise LookupError("The second-stage decision was not saved.")
            connection.commit()
        return bool(row[0])
