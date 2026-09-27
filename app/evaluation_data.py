"""Call-owned applicant and reviewer-grade projection for grouped evaluations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from app.evaluation_groups import EvaluationApplicant


@dataclass(frozen=True, slots=True)
class EvaluationSnapshot:
    roster: tuple[tuple[str, str], ...]
    applicants: tuple[EvaluationApplicant, ...]
    legacy_codes: dict[str, str] = field(default_factory=dict)


class EvaluationRepository(Protocol):
    def load(self, call_id: UUID, actor_group: str) -> EvaluationSnapshot: ...
    def set_comment(self, call_id: UUID, application_id: UUID, comment: str,
                    actor_identity: str, actor_group: str,
                    entra_object_id: UUID | None) -> str | None: ...


class EmptyEvaluationRepository:
    def load(self, call_id: UUID, actor_group: str) -> EvaluationSnapshot:
        del call_id, actor_group
        return EvaluationSnapshot((), (), {})

    def set_comment(self, call_id: UUID, application_id: UUID, comment: str,
                    actor_identity: str, actor_group: str,
                    entra_object_id: UUID | None) -> str | None:
        del call_id, application_id, comment, actor_identity, actor_group, entra_object_id
        raise PermissionError("Evaluation comments are unavailable.")


class SqlEvaluationRepository:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def load(self, call_id: UUID, actor_group: str) -> EvaluationSnapshot:
        with self._connection_factory() as connection:
            cursor = connection.execute(
                "EXEC dbo.GetCallEvaluationOverview @FellowshipCallId=?, @ActorGroup=?",
                call_id, actor_group,
            )
            roster_rows = cursor.fetchall()
            cursor.nextset()
            applicant_rows = cursor.fetchall()
        roster = tuple((str(row[0]), str(row[1])) for row in roster_rows)
        legacy_codes = {str(row[0]): str(row[3]) for row in roster_rows if row[3] is not None}
        applicants: dict[str, tuple[str, str, dict[str, str | None], dict[str, str | None]]] = {}
        for application_id, name, number, reviewer_id, grade, comment in applicant_rows:
            key = str(application_id)
            if key not in applicants:
                applicants[key] = (str(name), str(number), {}, {})
            if reviewer_id is not None:
                applicants[key][2][str(reviewer_id)] = str(grade) if grade is not None else None
                if comment is not None:
                    applicants[key][3][str(reviewer_id)] = str(comment)
        return EvaluationSnapshot(
            roster=roster,
            applicants=tuple(
                EvaluationApplicant(application_id, name, number, grades, comments)
                for application_id, (name, number, grades, comments) in applicants.items()
            ),
            legacy_codes=legacy_codes,
        )

    def set_comment(self, call_id: UUID, application_id: UUID, comment: str,
                    actor_identity: str, actor_group: str,
                    entra_object_id: UUID | None) -> str | None:
        with self._connection_factory() as connection:
            row = connection.execute(
                "EXEC dbo.SetCallEvaluationComment @FellowshipCallId=?, @ApplicationId=?, "
                "@CommentText=?, @ActorIdentity=?, @ActorGroup=?, @ActorEntraObjectId=?",
                call_id, application_id, comment, actor_identity, actor_group, entra_object_id,
            ).fetchone()
            if row is None:
                raise LookupError("The evaluation comment was not saved.")
            connection.commit()
        return str(row[0]) if row[0] is not None else None
