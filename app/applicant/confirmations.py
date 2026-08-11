"""Explicit confirmations bound to canonical section data versions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from app.applicant.drafts import DraftSnapshot


@dataclass(frozen=True, slots=True)
class SectionConfirmation:
    application_id: UUID
    section: str
    row_version: int
    canonical_sha256: str


class SectionConfirmationService:
    def __init__(self) -> None:
        self._confirmations: dict[tuple[UUID, str], SectionConfirmation] = {}

    def confirm(
        self, application_id: UUID, section: str, snapshot: DraftSnapshot
    ) -> SectionConfirmation:
        if snapshot.application_id != application_id or snapshot.section != section:
            raise ValueError("confirmation scope does not match the draft")
        confirmation = SectionConfirmation(
            application_id,
            section,
            snapshot.row_version,
            _canonical_hash(snapshot.values, snapshot.row_version),
        )
        self._confirmations[(application_id, section)] = confirmation
        return confirmation

    def is_current(
        self, application_id: UUID, section: str, snapshot: DraftSnapshot
    ) -> bool:
        current = self._confirmations.get((application_id, section))
        return current is not None and current == SectionConfirmation(
            application_id,
            section,
            snapshot.row_version,
            _canonical_hash(snapshot.values, snapshot.row_version),
        )

    def current(
        self, application_id: UUID, section: str
    ) -> SectionConfirmation | None:
        return self._confirmations.get((application_id, section))

    def invalidate(self, application_id: UUID, section: str) -> None:
        self._confirmations.pop((application_id, section), None)


def _canonical_hash(values: dict[str, Any], row_version: int) -> str:
    payload = json.dumps(
        values,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    ).encode("utf-16le")
    return hashlib.sha256(payload).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Unsupported canonical value: {type(value).__name__}")
