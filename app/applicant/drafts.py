"""Optimistic, provenance-preserving applicant section drafts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


class DraftConflict(RuntimeError):
    pass


class DraftLocked(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DraftSnapshot:
    application_id: UUID
    section: str
    values: dict[str, Any]
    row_version: int


@dataclass(frozen=True, slots=True)
class FieldCorrection:
    application_id: UUID
    section: str
    field: str
    before: Any
    after: Any
    source: str


class InMemoryDraftRepository:
    def __init__(self) -> None:
        self._drafts: dict[tuple[UUID, str], DraftSnapshot] = {}
        self._locked: set[UUID] = set()
        self._reopened: dict[UUID, set[str]] = {}
        self._corrections: list[FieldCorrection] = []

    @property
    def corrections(self) -> tuple[FieldCorrection, ...]:
        return tuple(self._corrections)

    def load(self, application_id: UUID, section: str) -> DraftSnapshot | None:
        return self._drafts.get((application_id, section))

    def save(
        self,
        application_id: UUID,
        section: str,
        values: dict[str, Any],
        expected_row_version: int | None,
        source: str,
    ) -> DraftSnapshot:
        if source not in {"APPLICANT", "ADMINISTRATOR"}:
            raise ValueError("draft provenance source is invalid")
        if application_id in self._locked and section not in self._reopened.get(application_id, set()):
            raise DraftLocked("The application section is locked.")
        current = self.load(application_id, section)
        actual = current.row_version if current is not None else None
        if expected_row_version != actual:
            raise DraftConflict("The applicant draft changed before this update.")
        merged = dict(current.values) if current is not None else {}
        changes: list[FieldCorrection] = []
        for field, after in values.items():
            before = merged.get(field)
            if before != after:
                changes.append(FieldCorrection(application_id, section, field, before, after, source))
                merged[field] = after
        snapshot = DraftSnapshot(application_id, section, merged, (actual or 0) + 1)
        self._drafts[(application_id, section)] = snapshot
        self._corrections.extend(changes)
        return snapshot

    def lock(self, application_id: UUID) -> None:
        self._locked.add(application_id)
        self._reopened.pop(application_id, None)

    def reopen(self, application_id: UUID, section: str) -> None:
        if application_id not in self._locked:
            raise DraftLocked("Only a locked application can be reopened.")
        self._reopened.setdefault(application_id, set()).add(section)
