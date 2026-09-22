"""Audited repository boundary for pending publication review."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

@dataclass(frozen=True, slots=True)
class PendingPublication:
    publication_id: UUID
    applicant_name: str
    authors: str | None
    title: str | None
    journal: str | None
    volume: str | None
    pages: str | None
    year: int | None
    doi: str | None
    url: str | None
    raw_citation: str | None
    resolution_status: str

class PendingPublicationReviewRepository(Protocol):
    def list(self, group: str) -> tuple[PendingPublication, ...]: ...
    def record(self, publication_id: UUID, disposition: str, actor: str, group: str) -> None: ...

class EmptyPendingPublicationReviewRepository:
    def list(self, group: str) -> tuple[PendingPublication, ...]:
        del group
        return ()
    def record(self, publication_id: UUID, disposition: str, actor: str, group: str) -> None:
        del publication_id, disposition, actor, group
        raise LookupError

class SqlPendingPublicationReviewRepository:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory
    def list(self, group: str) -> tuple[PendingPublication, ...]:
        with self._connection_factory() as connection:
            rows = connection.execute("EXEC dbo.ListPendingPublicationReviews @ActorGroup=?", group).fetchall()
        return tuple(_publication(row) for row in rows)
    def record(self, publication_id: UUID, disposition: str, actor: str, group: str) -> None:
        try:
            with self._connection_factory() as connection:
                connection.execute(
                    "EXEC dbo.RecordPendingPublicationReview @ApplicationPublicationId=?, "
                    "@ReviewDisposition=?, @ReviewerIdentity=?, @ActorGroup=?",
                    publication_id, disposition, actor, group,
                )
                connection.commit()
        except Exception as error:
            raise LookupError("The publication is no longer pending review.") from error

def _publication(row: Any) -> PendingPublication:
    text = lambda value: None if value is None else str(value)
    return PendingPublication(UUID(str(row[0])), str(row[1]), text(row[2]), text(row[3]),
        text(row[4]), text(row[5]), text(row[6]), None if row[7] is None else int(row[7]),
        text(row[8]), text(row[9]), text(row[10]), str(row[11]))
