"""Immutable, authorization-scoped fellowship-call contexts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Protocol
from uuid import UUID


_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9]|-(?!-)){1,78}[a-z0-9]\Z")


def validate_public_slug(slug: str) -> str:
    """Accept only the URL-safe call key accepted by the database constraint."""
    if not isinstance(slug, str) or _SLUG.fullmatch(slug) is None:
        raise ValueError("call slug is invalid")
    return slug


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class CallContext:
    fellowship_call_id: UUID
    call_code: str
    public_slug: str
    display_name: str
    compact_title: str
    call_status: str
    applicant_review_status: str
    internal_selection_status: str
    invitations_enabled: bool
    analysis_profile_code: str
    application_deadline_utc: datetime
    applicant_review_deadline_utc: datetime | None
    row_version: bytes

    def __post_init__(self) -> None:
        validate_public_slug(self.public_slug)
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.call_code, self.display_name, self.compact_title, self.analysis_profile_code)
        ):
            raise ValueError("call labels are required")
        if not isinstance(self.application_deadline_utc, datetime):
            raise ValueError("application deadline is required")
        object.__setattr__(self, "application_deadline_utc", _utc(self.application_deadline_utc))
        object.__setattr__(self, "applicant_review_deadline_utc", _utc(self.applicant_review_deadline_utc))


@dataclass(frozen=True, slots=True)
class PublicCallContext:
    public_slug: str
    call_code: str
    display_name: str
    application_deadline_utc: datetime
    applicant_review_deadline_utc: datetime | None
    applicant_review_status: str

    def __post_init__(self) -> None:
        validate_public_slug(self.public_slug)
        object.__setattr__(self, "application_deadline_utc", _utc(self.application_deadline_utc))
        object.__setattr__(self, "applicant_review_deadline_utc", _utc(self.applicant_review_deadline_utc))


@dataclass(frozen=True, slots=True)
class CallSummary:
    context: CallContext
    applicant_count: int
    latest_import_completed_at_utc: datetime | None
    activated_analysis_evidence_id: UUID | None
    active_shortlister_count: int
    roster_state: str


class CallCatalog(Protocol):
    def list_authorized(self, actor_group: str) -> tuple[CallSummary, ...]: ...

    def resolve(self, slug: str, actor_group: str, required_role: str) -> CallContext: ...

    def resolve_public(self, slug: str) -> PublicCallContext: ...


class InMemoryCallCatalog:
    """A fail-closed catalog used by unit and server-route acceptance tests."""

    def __init__(
        self,
        contexts: tuple[CallContext, ...] = (),
        access: dict[str, frozenset[str]] | None = None,
    ) -> None:
        self._contexts = {context.public_slug: context for context in contexts}
        self._access = access or {}

    def list_authorized(self, actor_group: str) -> tuple[CallSummary, ...]:
        return tuple(
            CallSummary(context, 0, None, None, 0, "UNAVAILABLE")
            for slug, context in self._contexts.items()
            if actor_group in self._access.get(slug, frozenset())
        )

    def resolve(self, slug: str, actor_group: str, required_role: str) -> CallContext:
        validate_public_slug(slug)
        if required_role not in {"READ", "ADMINISTER"}:
            raise ValueError("call role is invalid")
        context = self._contexts.get(slug)
        if context is None or actor_group not in self._access.get(slug, frozenset()):
            raise LookupError("call is unavailable")
        return context

    def resolve_public(self, slug: str) -> PublicCallContext:
        validate_public_slug(slug)
        context = self._contexts.get(slug)
        if context is None or context.call_status not in {"OPEN", "CLOSED"}:
            raise LookupError("public call is unavailable")
        return PublicCallContext(
            public_slug=context.public_slug,
            call_code=context.call_code,
            display_name=context.display_name,
            application_deadline_utc=context.application_deadline_utc,
            applicant_review_deadline_utc=context.applicant_review_deadline_utc,
            applicant_review_status=context.applicant_review_status,
        )


class SqlCallCatalog:
    """Map execution-only stored procedure result rows into frozen call contexts."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def list_authorized(self, actor_group: str) -> tuple[CallSummary, ...]:
        with self._connection_factory() as connection:
            rows = connection.execute(
                "EXEC dbo.ListAuthorizedFellowshipCalls @ActorGroup=?", actor_group
            ).fetchall()
        return tuple(self._summary(row) for row in rows)

    def resolve(self, slug: str, actor_group: str, required_role: str) -> CallContext:
        validate_public_slug(slug)
        if required_role not in {"READ", "ADMINISTER"}:
            raise ValueError("call role is invalid")
        with self._connection_factory() as connection:
            row = connection.execute(
                "EXEC dbo.GetAuthorizedFellowshipCallBySlug @PublicSlug=?, @ActorGroup=?, @RequiredRole=?",
                slug,
                actor_group,
                required_role,
            ).fetchone()
        if row is None:
            raise LookupError("call is unavailable")
        return self._context(row)

    def resolve_public(self, slug: str) -> PublicCallContext:
        validate_public_slug(slug)
        with self._connection_factory() as connection:
            row = connection.execute(
                "EXEC dbo.GetPublicFellowshipCallBySlug @PublicSlug=?", slug
            ).fetchone()
        if row is None:
            raise LookupError("public call is unavailable")
        return PublicCallContext(
            public_slug=str(row[0]), call_code=str(row[1]), display_name=str(row[2]),
            application_deadline_utc=row[3], applicant_review_deadline_utc=row[4],
            applicant_review_status=str(row[5]),
        )

    @staticmethod
    def _context(row: Any) -> CallContext:
        return CallContext(
            fellowship_call_id=UUID(str(row[0])), call_code=str(row[1]), public_slug=str(row[2]),
            display_name=str(row[3]), compact_title=str(row[4]), call_status=str(row[5]),
            applicant_review_status=str(row[6]), internal_selection_status=str(row[7]),
            invitations_enabled=bool(row[8]), analysis_profile_code=str(row[9]),
            application_deadline_utc=row[10], applicant_review_deadline_utc=row[11],
            row_version=bytes(row[12]),
        )

    @classmethod
    def _summary(cls, row: Any) -> CallSummary:
        return CallSummary(
            context=cls._context(row), applicant_count=int(row[13]),
            latest_import_completed_at_utc=_utc(row[14]),
            activated_analysis_evidence_id=None if row[15] is None else UUID(str(row[15])),
            active_shortlister_count=int(row[16]), roster_state=str(row[17]),
        )
