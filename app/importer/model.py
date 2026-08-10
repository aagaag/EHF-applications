"""Immutable values produced by the read-only source inventory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceOccurrence:
    """One source-tree file occurrence, without exposing an absolute source path."""

    relative_path: str
    sha256: str
    byte_size: int
    is_pdf: bool
    is_internal: bool


@dataclass(frozen=True, slots=True)
class InventoryIssue:
    """A source entry that could not safely be inventoried."""

    relative_path: str
    message: str


@dataclass(frozen=True, slots=True)
class SourceInventory:
    """A deterministic, non-mutating inventory of a source tree."""

    source_root: Path
    applicant_directories: tuple[str, ...]
    occurrences: tuple[SourceOccurrence, ...]
    issues: tuple[InventoryIssue, ...]

    @property
    def duplicate_hashes(self) -> dict[str, tuple[str, ...]]:
        grouped: dict[str, list[str]] = {}
        for occurrence in self.occurrences:
            grouped.setdefault(occurrence.sha256, []).append(occurrence.relative_path)
        return {
            digest: tuple(paths)
            for digest, paths in grouped.items()
            if len(paths) > 1
        }

    @property
    def internal_occurrences(self) -> tuple[SourceOccurrence, ...]:
        return tuple(occurrence for occurrence in self.occurrences if occurrence.is_internal)
