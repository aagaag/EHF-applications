"""Deterministic, read-only inventory of an EHF call source tree."""

from __future__ import annotations

import hashlib
import csv
import json
from pathlib import Path
import argparse

from app.importer.model import InventoryIssue, SourceInventory, SourceOccurrence

_INTERNAL_DIRECTORY = "selection committee"


def inventory_source_tree(source_root: Path) -> SourceInventory:
    """Return every safely reachable file occurrence without changing the source tree."""
    root = source_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("source root must be a directory")

    occurrences: list[SourceOccurrence] = []
    issues: list[InventoryIssue] = []
    applicant_directories: list[str] = []
    visited_directories: set[Path] = set()

    def walk(directory: Path) -> None:
        resolved_directory = _resolve_inside_root(directory, root, issues)
        if resolved_directory is None or resolved_directory in visited_directories:
            return
        visited_directories.add(resolved_directory)
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: (entry.name.casefold(), entry.name))
        except OSError as error:
            issues.append(InventoryIssue(_relative_path(directory, root), _error_message(error)))
            return

        for entry in entries:
            resolved_entry = _resolve_inside_root(entry, root, issues)
            if resolved_entry is None:
                continue
            try:
                if entry.is_dir():
                    if directory == root and entry.name.casefold() != _INTERNAL_DIRECTORY:
                        applicant_directories.append(entry.name)
                    walk(entry)
                elif entry.is_file():
                    occurrences.append(_occurrence(entry, root))
            except OSError as error:
                issues.append(InventoryIssue(_relative_path(entry, root), _error_message(error)))

    walk(root)
    occurrences.sort(key=lambda occurrence: occurrence.relative_path)
    issues.sort(key=lambda issue: (issue.relative_path, issue.message))
    applicant_directories.sort(key=lambda name: (name.casefold(), name))
    return SourceInventory(root, tuple(applicant_directories), tuple(occurrences), tuple(issues))


def write_inventory_manifests(report: SourceInventory, output_root: Path) -> tuple[Path, Path]:
    """Write deterministic JSON and CSV reports outside the read-only source tree."""
    destination = output_root.resolve()
    try:
        destination.relative_to(report.source_root)
    except ValueError:
        pass
    else:
        raise ValueError("inventory output must be outside the source tree")

    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "i.json"
    csv_path = destination / "i.csv"
    payload = {
        "duplicates": report.duplicate_hashes,
        "issues": [
            {"message": issue.message, "relative_path": issue.relative_path}
            for issue in report.issues
        ],
        "occurrences": [
            {
                "byte_size": occurrence.byte_size,
                "is_internal": occurrence.is_internal,
                "is_pdf": occurrence.is_pdf,
                "relative_path": occurrence.relative_path,
                "sha256": occurrence.sha256,
            }
            for occurrence in report.occurrences
        ],
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as destination_file:
        writer = csv.DictWriter(
            destination_file,
            fieldnames=("relative_path", "sha256", "byte_size", "is_pdf", "is_internal"),
        )
        writer.writeheader()
        writer.writerows(
            {
                "relative_path": occurrence.relative_path,
                "sha256": occurrence.sha256,
                "byte_size": occurrence.byte_size,
                "is_pdf": occurrence.is_pdf,
                "is_internal": occurrence.is_internal,
            }
            for occurrence in report.occurrences
        )
    return json_path, csv_path


def _fingerprint(report: SourceInventory) -> str:
    payload = {
        "applicant_directories": report.applicant_directories,
        "issues": [(issue.relative_path, issue.message) for issue in report.issues],
        "occurrences": [
            (
                occurrence.relative_path,
                occurrence.sha256,
                occurrence.byte_size,
                occurrence.is_pdf,
                occurrence.is_internal,
            )
            for occurrence in report.occurrences
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def main() -> int:
    """Create source inventory manifests and verify that the source remained unchanged."""
    parser = argparse.ArgumentParser(description="Read-only EHF call source inventory")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    arguments = parser.parse_args()

    before = inventory_source_tree(arguments.source_root)
    write_inventory_manifests(before, arguments.output_root)
    after = inventory_source_tree(arguments.source_root)
    unchanged = _fingerprint(before) == _fingerprint(after)
    print(f"Applicant directory candidates: {len(before.applicant_directories)}")
    print(f"File occurrences: {len(before.occurrences)}")
    print(f"PDF occurrences: {sum(occurrence.is_pdf for occurrence in before.occurrences)}")
    print(f"Duplicate hash groups: {len(before.duplicate_hashes)}")
    print(f"Exceptions: {len(before.issues)}")
    print(f"Source hash unchanged: {unchanged}")
    return 0 if unchanged else 3


def _occurrence(path: Path, root: Path) -> SourceOccurrence:
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            byte_size += len(chunk)
    relative_path = _relative_path(path, root)
    return SourceOccurrence(
        relative_path=relative_path,
        sha256=digest.hexdigest(),
        byte_size=byte_size,
        is_pdf=path.suffix.casefold() == ".pdf",
        is_internal=relative_path.split("/", 1)[0].casefold() == _INTERNAL_DIRECTORY,
    )


def _resolve_inside_root(path: Path, root: Path, issues: list[InventoryIssue]) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        issues.append(InventoryIssue(_relative_path(path, root), _error_message(error)))
        return None
    return resolved


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _error_message(error: Exception) -> str:
    return error.__class__.__name__


if __name__ == "__main__":
    raise SystemExit(main())
