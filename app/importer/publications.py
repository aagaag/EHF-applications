"""Strict, provenance-preserving import of reviewed publication manifests."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode

from app.importer.run import ImportMode


PUBLICATION_IMPORTER_VERSION = "2026.4-publications"
PUBLICATION_MANIFEST_SCHEMA = "publication-import-manifest-v1"


class PublicationImportError(RuntimeError):
    """The publication manifest or requested import operation is unsafe."""


@dataclass(frozen=True, slots=True)
class ManifestCounts:
    applicants: int
    works: int
    source_occurrences: int
    citation_statuses: int


PRODUCTION_COUNTS = ManifestCounts(36, 841, 883, 2523)


@dataclass(frozen=True, slots=True)
class PublicationApplicant:
    applicant_folder: str
    workbook_applicant: str
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CanonicalMetadata:
    doi: str | None
    doi_url: str | None
    authors_text: str | None
    title: str | None
    journal: str | None
    volume: str | None
    pages: str | None
    year: int | None


@dataclass(frozen=True, slots=True)
class PublicationResolution:
    status: str
    method: str
    evidence: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PublicationWork:
    final_work_id: str
    applicant_folder: str
    workbook_applicant: str
    source_work_ids: tuple[str, ...]
    representative_source_occurrence_id: str
    source_occurrence_ids: tuple[str, ...]
    canonical_metadata: CanonicalMetadata
    resolution: PublicationResolution
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PublicationSourceOccurrence:
    source_occurrence_id: str
    final_work_id: str
    source_work_id: str
    applicant_folder: str
    source_artifact: str
    source_record_index: int
    source_record_position: int
    normalized_doi_candidates: tuple[str, ...]
    normalized_raw_citation: str
    source_record: Mapping[str, Any]
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PublicationCitationStatus:
    final_work_id: str
    source: str
    count: int | None
    status: str
    evidence: str
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PublicationManifest:
    schema_version: str
    generated_at_utc: str
    applicants: tuple[PublicationApplicant, ...]
    works: tuple[PublicationWork, ...]
    source_occurrences: tuple[PublicationSourceOccurrence, ...]
    citation_statuses: tuple[PublicationCitationStatus, ...]
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PublicationImportResult:
    mode: ImportMode
    fingerprint: str
    application_count: int
    publication_count: int
    source_occurrence_count: int
    citation_observation_count: int
    run_id: str | None
    reused_completed_run: bool
    conflict_count: int


class PublicationRepository(Protocol):
    def apply(self, manifest: PublicationManifest, fingerprint: str) -> PublicationImportResult: ...


_TOP_KEYS = {
    "schema_version", "generated_read_only", "generated_at_utc",
    "reconciliation_policy", "inputs", "applicants", "works",
    "source_occurrences", "citation_source_statuses", "summary",
    "validation", "hashes",
}
_POLICY_KEYS = {
    "exact_crossref", "bibliographic_crossref", "conflicts",
    "deduplication", "citation_counts",
}
_INPUT_KEYS = {"path", "sha256", "schema_version"}
_APPLICANT_KEYS = {
    "applicant_folder", "workbook_applicant", "workbook_reported_total_raw",
    "workbook_reported_total", "source_preliminary_unique_work_count",
    "final_unique_work_count", "status", "difference_unique_minus_reported",
}
_WORK_KEYS = {
    "final_work_id", "applicant_folder", "workbook_applicant", "source_work_ids",
    "representative_source_occurrence_id", "source_occurrence_ids",
    "canonical_metadata", "resolution",
}
_CANONICAL_KEYS = {
    "doi", "doi_url", "authors_text", "title", "journal", "volume", "pages", "year",
}
_RESOLUTION_KEYS = {"status", "method", "evidence"}
_OCCURRENCE_KEYS = {
    "source_occurrence_id", "final_work_id", "source_work_id", "applicant_folder",
    "source_artifact", "source_record_index", "source_record_position",
    "normalized_doi_candidates", "normalized_raw_citation", "source_record",
}
_CITATION_KEYS = {"final_work_id", "source", "count", "status", "evidence"}
_SUMMARY_KEYS = {
    "source_preliminary_unique_work_total", "source_occurrence_total",
    "final_unique_work_total", "pre_merge_resolved_source_work_total",
    "pre_merge_exact_crossref_resolved_source_work_total",
    "pre_merge_bibliographic_crossref_resolved_source_work_total",
    "resolved_doi_work_total", "exact_crossref_resolved_work_total",
    "bibliographic_crossref_resolved_work_total", "unresolved_work_total",
    "ambiguous_work_total", "duplicate_merge_total", "metadata_completeness",
    "issues_file", "issues_sha256_excluding_hash", "excel_discrepancy_numeric_total",
    "excel_no_workbook_total_total", "excel_match_total",
}
_COMPLETENESS_KEYS = {
    "doi", "doi_url", "authors_text", "title", "journal", "volume", "pages", "year",
    "fully_complete_canonical_records",
}
_VALIDATION_KEYS = {
    "applicant_mappings_valid", "source_occurrence_fk_valid",
    "source_occurrence_uniqueness_valid", "final_work_uniqueness_valid",
    "per_applicant_confirmed_doi_uniqueness_valid", "canonical_field_types_valid",
    "input_hashes_valid", "manifest_self_hash_valid", "all_valid",
}
_HASH_KEYS = {"manifest_sha256_excluding_hash"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_CITATION_SOURCES = {"GOOGLE_SCHOLAR", "BIORXIV", "MEDRXIV"}
_CITATION_STATUSES = {
    "OBSERVED", "MANUAL_REQUIRED", "NOT_AVAILABLE_FROM_SOURCE", "NOT_FOUND", "NOT_APPLICABLE"
}


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PublicationImportError(f"{label} must be an object.")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise PublicationImportError(f"{label} must be a list.")
    return value


def _keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown:
        raise PublicationImportError(f"{label} has an unknown field: {sorted(unknown)[0]}.")
    if missing:
        raise PublicationImportError(f"{label} is missing field: {sorted(missing)[0]}.")


def _text(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PublicationImportError(f"{label} must be non-blank text.")
    return value


def _optional_text(value: Any, label: str) -> str | None:
    result = _text(value, label, nullable=True)
    if result == "":
        raise PublicationImportError(f"{label} must be null rather than blank.")
    return result


def _bounded_text(
    value: Any,
    label: str,
    maximum: int,
    *,
    nullable: bool = False,
) -> str | None:
    result = _text(value, label, nullable=nullable)
    if result is not None and len(result) > maximum:
        raise PublicationImportError(f"{label} exceeds {maximum} characters.")
    return result


def _identifier(value: Any, label: str, maximum: int) -> str:
    result = str(_bounded_text(value, label, maximum))
    if result != result.strip():
        raise PublicationImportError(f"{label} has surrounding whitespace.")
    return result


def _utc_timestamp(value: Any, label: str) -> str:
    raw = _text(value, label)
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as error:
        raise PublicationImportError(f"{label} must be an ISO 8601 timestamp.") from error
    if parsed.tzinfo is None or not 2000 <= parsed.year <= 2200:
        raise PublicationImportError(
            f"{label} must include a UTC offset and have a year from 2000 through 2200."
        )
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _integer(value: Any, label: str, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PublicationImportError(f"{label} must be an integer.")
    return value


def normalize_doi(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
            break
    if not _DOI_RE.fullmatch(normalized):
        raise PublicationImportError("A DOI is not syntactically valid.")
    return normalized


def _self_hash(document: Mapping[str, Any]) -> str:
    clone = json.loads(json.dumps(document, ensure_ascii=False))
    clone["hashes"]["manifest_sha256_excluding_hash"] = None
    payload = json.dumps(
        clone, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_publication_manifest(
    raw_bytes: bytes,
    *,
    expected: ManifestCounts = PRODUCTION_COUNTS,
) -> PublicationManifest:
    try:
        document = json.loads(raw_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationImportError("The publication manifest is not valid UTF-8 JSON.") from error
    root = _mapping(document, "manifest")
    _keys(root, _TOP_KEYS, "manifest")
    if root["schema_version"] != PUBLICATION_MANIFEST_SCHEMA:
        raise PublicationImportError("The publication manifest schema version is unsupported.")
    if root["generated_read_only"] is not True:
        raise PublicationImportError("The publication manifest must be read-only research output.")
    generated_at = _utc_timestamp(root["generated_at_utc"], "generated_at_utc")

    policy = _mapping(root["reconciliation_policy"], "reconciliation_policy")
    _keys(policy, _POLICY_KEYS, "reconciliation_policy")
    for name, value in policy.items():
        _text(value, f"reconciliation_policy.{name}")

    inputs = _list(root["inputs"], "inputs")
    if not inputs:
        raise PublicationImportError("The publication manifest has no inputs.")
    for index, raw_input in enumerate(inputs):
        item = _mapping(raw_input, f"inputs[{index}]")
        _keys(item, _INPUT_KEYS, f"inputs[{index}]")
        _text(item["path"], f"inputs[{index}].path")
        digest = _text(item["sha256"], f"inputs[{index}].sha256")
        if not _SHA256_RE.fullmatch(str(digest)):
            raise PublicationImportError("An input SHA-256 is invalid.")
        _optional_text(item["schema_version"], f"inputs[{index}].schema_version")

    hashes = _mapping(root["hashes"], "hashes")
    _keys(hashes, _HASH_KEYS, "hashes")
    declared_hash = _text(hashes["manifest_sha256_excluding_hash"], "manifest self-hash")
    if not _SHA256_RE.fullmatch(str(declared_hash)) or declared_hash != _self_hash(root):
        raise PublicationImportError("The publication manifest self-hash is invalid.")

    validation = _mapping(root["validation"], "validation")
    _keys(validation, _VALIDATION_KEYS, "validation")
    if any(validation[name] is not True for name in _VALIDATION_KEYS):
        raise PublicationImportError("The publication manifest validation flags are not all true.")

    summary = _mapping(root["summary"], "summary")
    _keys(summary, _SUMMARY_KEYS, "summary")
    completeness = _mapping(summary["metadata_completeness"], "metadata_completeness")
    _keys(completeness, _COMPLETENESS_KEYS, "metadata_completeness")

    applicant_values = _list(root["applicants"], "applicants")
    work_values = _list(root["works"], "works")
    occurrence_values = _list(root["source_occurrences"], "source_occurrences")
    citation_values = _list(root["citation_source_statuses"], "citation_source_statuses")
    actual_counts = ManifestCounts(
        len(applicant_values), len(work_values), len(occurrence_values), len(citation_values)
    )
    for label, actual, wanted in (
        ("applicants", actual_counts.applicants, expected.applicants),
        ("works", actual_counts.works, expected.works),
        ("source occurrences", actual_counts.source_occurrences, expected.source_occurrences),
        ("citation statuses", actual_counts.citation_statuses, expected.citation_statuses),
    ):
        if actual != wanted:
            raise PublicationImportError(f"The manifest has {actual} {label}; expected {wanted} {label}.")
    if summary["final_unique_work_total"] != expected.works:
        raise PublicationImportError("The summary work count disagrees with the manifest.")
    if summary["source_occurrence_total"] != expected.source_occurrences:
        raise PublicationImportError("The summary source occurrence count disagrees with the manifest.")

    applicants: list[PublicationApplicant] = []
    applicant_by_folder: dict[str, PublicationApplicant] = {}
    applicant_names: set[str] = set()
    for index, value in enumerate(applicant_values):
        item = _mapping(value, f"applicants[{index}]")
        _keys(item, _APPLICANT_KEYS, f"applicants[{index}]")
        folder = str(_text(item["applicant_folder"], "applicant_folder"))
        name = str(_text(item["workbook_applicant"], "workbook_applicant"))
        for integer_field in (
            "source_preliminary_unique_work_count", "final_unique_work_count",
        ):
            _integer(item[integer_field], integer_field)
        _integer(
            item["difference_unique_minus_reported"],
            "difference_unique_minus_reported",
            nullable=True,
        )
        _integer(item["workbook_reported_total"], "workbook_reported_total", nullable=True)
        if item["workbook_reported_total_raw"] is not None and not isinstance(
            item["workbook_reported_total_raw"], (str, int)
        ):
            raise PublicationImportError("workbook_reported_total_raw has an invalid type.")
        _text(item["status"], "applicant status")
        if folder in applicant_by_folder or name in applicant_names:
            raise PublicationImportError("Applicant mappings are not unique.")
        applicant = PublicationApplicant(folder, name, item)
        applicant_by_folder[folder] = applicant
        applicant_names.add(name)
        applicants.append(applicant)

    occurrences: list[PublicationSourceOccurrence] = []
    occurrence_by_id: dict[str, PublicationSourceOccurrence] = {}
    for index, value in enumerate(occurrence_values):
        item = _mapping(value, f"source_occurrences[{index}]")
        _keys(item, _OCCURRENCE_KEYS, f"source_occurrences[{index}]")
        occurrence_id = _identifier(item["source_occurrence_id"], "source_occurrence_id", 255)
        candidates = tuple(
            str(normalize_doi(str(candidate)))
            for candidate in _list(item["normalized_doi_candidates"], "normalized_doi_candidates")
        )
        occurrence = PublicationSourceOccurrence(
            occurrence_id,
            _identifier(item["final_work_id"], "occurrence final_work_id", 80),
            _identifier(item["source_work_id"], "source_work_id", 255),
            str(_text(item["applicant_folder"], "occurrence applicant_folder")),
            str(_text(item["source_artifact"], "source_artifact")),
            int(_integer(item["source_record_index"], "source_record_index")),
            int(_integer(item["source_record_position"], "source_record_position")),
            candidates,
            str(_text(item["normalized_raw_citation"], "normalized_raw_citation")),
            _mapping(item["source_record"], "source_record"),
            item,
        )
        if occurrence_id in occurrence_by_id:
            raise PublicationImportError("Source occurrence identifiers are not unique.")
        occurrence_by_id[occurrence_id] = occurrence
        occurrences.append(occurrence)

    works: list[PublicationWork] = []
    work_by_id: dict[str, PublicationWork] = {}
    doi_owners: set[tuple[str, str]] = set()
    for index, value in enumerate(work_values):
        item = _mapping(value, f"works[{index}]")
        _keys(item, _WORK_KEYS, f"works[{index}]")
        metadata_value = _mapping(item["canonical_metadata"], "canonical_metadata")
        _keys(metadata_value, _CANONICAL_KEYS, "canonical_metadata")
        doi = normalize_doi(_optional_text(metadata_value["doi"], "doi"))
        if doi is not None and len(doi) > 255:
            raise PublicationImportError("doi exceeds 255 characters.")
        doi_url = _bounded_text(metadata_value["doi_url"], "doi_url", 2048, nullable=True)
        if doi is not None and doi_url != f"https://doi.org/{doi}":
            raise PublicationImportError("A DOI URL does not match its normalized DOI.")
        year = _integer(metadata_value["year"], "year", nullable=True)
        if year is not None and not 1600 <= year <= 2200:
            raise PublicationImportError("A publication year is outside the accepted range.")
        metadata = CanonicalMetadata(
            doi, doi_url,
            _optional_text(metadata_value["authors_text"], "authors_text"),
            _bounded_text(metadata_value["title"], "title", 2000, nullable=True),
            _bounded_text(metadata_value["journal"], "journal", 1000, nullable=True),
            _bounded_text(metadata_value["volume"], "volume", 255, nullable=True),
            _bounded_text(metadata_value["pages"], "pages", 255, nullable=True),
            year,
        )
        resolution_value = _mapping(item["resolution"], "resolution")
        _keys(resolution_value, _RESOLUTION_KEYS, "resolution")
        status = str(_text(resolution_value["status"], "resolution status"))
        if status not in {"RESOLVED", "AMBIGUOUS", "UNRESOLVED"}:
            raise PublicationImportError("A publication resolution status is invalid.")
        resolution = PublicationResolution(
            status,
            str(_text(resolution_value["method"], "resolution method")),
            _mapping(resolution_value["evidence"], "resolution evidence"),
        )
        if (status == "RESOLVED") != (doi is not None):
            raise PublicationImportError("Resolution status and DOI presence disagree.")
        work_id = _identifier(item["final_work_id"], "final_work_id", 80)
        folder = str(_text(item["applicant_folder"], "work applicant_folder"))
        name = str(_text(item["workbook_applicant"], "work workbook_applicant"))
        if folder not in applicant_by_folder or applicant_by_folder[folder].workbook_applicant != name:
            raise PublicationImportError("A work has no exact applicant mapping.")
        source_work_ids = tuple(
            _identifier(value, "source_work_id", 255)
            for value in _list(item["source_work_ids"], "source_work_ids")
        )
        source_occurrence_ids = tuple(
            _identifier(value, "source_occurrence_id", 255)
            for value in _list(item["source_occurrence_ids"], "source_occurrence_ids")
        )
        representative = str(
            _text(item["representative_source_occurrence_id"], "representative_source_occurrence_id")
        )
        if (
            not source_work_ids
            or not source_occurrence_ids
            or len(set(source_work_ids)) != len(source_work_ids)
            or len(set(source_occurrence_ids)) != len(source_occurrence_ids)
            or representative not in source_occurrence_ids
        ):
            raise PublicationImportError("A work has incomplete source provenance.")
        if any(
            occurrence_id not in occurrence_by_id
            or occurrence_by_id[occurrence_id].final_work_id != work_id
            or occurrence_by_id[occurrence_id].applicant_folder != folder
            for occurrence_id in source_occurrence_ids
        ):
            raise PublicationImportError("A work/source occurrence relationship is invalid.")
        occurrence_source_work_ids = {
            occurrence_by_id[occurrence_id].source_work_id
            for occurrence_id in source_occurrence_ids
        }
        if set(source_work_ids) != occurrence_source_work_ids:
            raise PublicationImportError("A work/source-work relationship is invalid.")
        work = PublicationWork(
            work_id, folder, name, source_work_ids, representative,
            source_occurrence_ids, metadata, resolution, item,
        )
        if work_id in work_by_id:
            raise PublicationImportError("Final work identifiers are not unique.")
        if doi is not None:
            owner = (folder, doi)
            if owner in doi_owners:
                raise PublicationImportError("Confirmed DOIs are not unique per applicant.")
            doi_owners.add(owner)
        work_by_id[work_id] = work
        works.append(work)
    if set(occurrence_by_id) != {
        occurrence_id for work in works for occurrence_id in work.source_occurrence_ids
    }:
        raise PublicationImportError("An occurrence is not owned by exactly one final work.")
    actual_works_by_applicant = Counter(work.applicant_folder for work in works)
    for applicant in applicants:
        if (
            applicant.raw["final_unique_work_count"]
            != actual_works_by_applicant[applicant.applicant_folder]
        ):
            raise PublicationImportError("An applicant declared work count disagrees with the works.")
    resolution_counts = Counter(work.resolution.status for work in works)
    if (
        summary["resolved_doi_work_total"] != resolution_counts["RESOLVED"]
        or summary["unresolved_work_total"] != resolution_counts["UNRESOLVED"]
        or summary["ambiguous_work_total"] != resolution_counts["AMBIGUOUS"]
    ):
        raise PublicationImportError("The summary resolution counts disagree with the works.")

    citations: list[PublicationCitationStatus] = []
    citation_pairs: Counter[tuple[str, str]] = Counter()
    for index, value in enumerate(citation_values):
        item = _mapping(value, f"citation_source_statuses[{index}]")
        _keys(item, _CITATION_KEYS, f"citation_source_statuses[{index}]")
        work_id = str(_text(item["final_work_id"], "citation final_work_id"))
        source = str(_text(item["source"], "citation source"))
        status = str(_text(item["status"], "citation status"))
        if work_id not in work_by_id or source not in _CITATION_SOURCES or status not in _CITATION_STATUSES:
            raise PublicationImportError("A citation-source relationship or status is invalid.")
        if item["count"] is not None:
            raise PublicationImportError("The initial citation counts must remain null.")
        if status == "OBSERVED":
            raise PublicationImportError("An initial citation status cannot be OBSERVED.")
        if source == "GOOGLE_SCHOLAR" and status != "MANUAL_REQUIRED":
            raise PublicationImportError("Google Scholar must start as MANUAL_REQUIRED.")
        if source in {"BIORXIV", "MEDRXIV"} and status not in {
            "NOT_AVAILABLE_FROM_SOURCE", "NOT_FOUND", "NOT_APPLICABLE"
        }:
            raise PublicationImportError("A preprint initial citation status is invalid.")
        evidence = str(_text(item["evidence"], "citation evidence"))
        citation_pairs[(work_id, source)] += 1
        citations.append(PublicationCitationStatus(work_id, source, None, status, evidence, item))
    if any(citation_pairs[(work.final_work_id, source)] != 1 for work in works for source in _CITATION_SOURCES):
        raise PublicationImportError("Each work must have exactly one status for every citation source.")

    return PublicationManifest(
        str(root["schema_version"]), str(generated_at), tuple(applicants), tuple(works),
        tuple(occurrences), tuple(citations), root,
    )


def publication_identity(
    work: PublicationWork,
    occurrences: Sequence[PublicationSourceOccurrence],
) -> str:
    if work.canonical_metadata.doi is not None:
        basis = f"doi\0{work.canonical_metadata.doi}"
    else:
        occurrence_by_id = {item.source_occurrence_id: item for item in occurrences}
        try:
            raw_citation = occurrence_by_id[
                work.representative_source_occurrence_id
            ].normalized_raw_citation
        except KeyError as error:
            raise PublicationImportError("The representative source occurrence is missing.") from error
        normalized = " ".join(raw_citation.casefold().split())
        basis = f"citation\0{normalized}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


_CANONICAL_DATABASE_FIELDS = (
    "doi",
    "http_link",
    "authors_text",
    "title",
    "journal_text",
    "volume_text",
    "pages_text",
    "publication_year",
)


def reconcile_canonical_values(
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, tuple[Any, Any]]]:
    """Return safe blank fills and non-blank discrepancies without mutating either input."""
    fills: dict[str, Any] = {}
    conflicts: dict[str, tuple[Any, Any]] = {}
    for field in _CANONICAL_DATABASE_FIELDS:
        old_value = existing.get(field)
        new_value = incoming.get(field)
        if old_value is None and new_value is not None:
            fills[field] = new_value
        elif old_value is not None and new_value is not None and old_value != new_value:
            conflicts[field] = (old_value, new_value)
    return fills, conflicts


def _canonical_database_values(work: PublicationWork) -> dict[str, Any]:
    metadata = work.canonical_metadata
    return {
        "doi": metadata.doi,
        "http_link": metadata.doi_url,
        "authors_text": metadata.authors_text,
        "title": metadata.title,
        "journal_text": metadata.journal,
        "volume_text": metadata.volume,
        "pages_text": metadata.pages,
        "publication_year": metadata.year,
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class SqlPublicationRepository:
    """Privileged SQL writer that preserves canonical values and append-only evidence."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def apply(
        self,
        manifest: PublicationManifest,
        fingerprint: str,
    ) -> PublicationImportResult:
        call_rows = self._connection.execute(
            "SELECT CONVERT(varchar(36), FellowshipCallId) "
            "FROM dbo.FellowshipCall WHERE CallCode = N'EHF-2026'"
        ).fetchall()
        if len(call_rows) != 1:
            raise PublicationImportError("The EHF-2026 call cannot be resolved uniquely.")
        call_id = str(call_rows[0][0])
        completed = self._connection.execute(
            "SELECT TOP (1) CONVERT(varchar(36), ImportRunId) FROM dbo.ImportRun "
            "WHERE FellowshipCallId = ? "
            "AND ImportFingerprintSha256 = CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)) "
            "AND RunStatus = 'COMPLETED' ORDER BY CompletedAtUtc DESC",
            call_id,
            fingerprint,
        ).fetchone()
        if completed is not None:
            conflict_row = self._connection.execute(
                "SELECT COUNT(*) FROM dbo.ImportException WHERE ImportRunId = ? "
                "AND ExceptionCode LIKE 'PUBLICATION_CONFLICT_%'",
                str(completed[0]),
            ).fetchone()
            return PublicationImportResult(
                ImportMode.APPLY,
                fingerprint,
                len(manifest.applicants),
                len(manifest.works),
                len(manifest.source_occurrences),
                len(manifest.citation_statuses),
                str(completed[0]),
                True,
                0 if conflict_row is None else int(conflict_row[0]),
            )

        application_ids: dict[str, str] = {}
        for applicant in manifest.applicants:
            application_rows = self._connection.execute(
                "SELECT CONVERT(varchar(36), application_row.ApplicationId) "
                "FROM dbo.Application AS application_row "
                "JOIN dbo.Applicant AS applicant_row "
                "ON applicant_row.ApplicantId = application_row.ApplicantId "
                "WHERE application_row.FellowshipCallId = ? "
                "AND CONCAT(applicant_row.LegalGivenNames, N' ', applicant_row.LegalFamilyName) = ?",
                call_id,
                applicant.workbook_applicant,
            ).fetchall()
            if len(application_rows) != 1:
                raise PublicationImportError(
                    "A publication applicant does not match exactly one EHF-2026 application."
                )
            application_ids[applicant.workbook_applicant] = str(application_rows[0][0])
        if len(set(application_ids.values())) != len(application_ids):
            raise PublicationImportError(
                "Publication applicants do not map to distinct EHF-2026 applications."
            )

        run_row = self._connection.execute(
            "INSERT dbo.ImportRun "
            "(FellowshipCallId, ImportFingerprintSha256, ImporterVersion, RunStatus, StartedByIdentity) "
            "OUTPUT CONVERT(varchar(36), inserted.ImportRunId) "
            "VALUES (?, CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), ?, 'RUNNING', 'ISAB01_PUBLICATION_IMPORT')",
            call_id,
            fingerprint,
            PUBLICATION_IMPORTER_VERSION,
        ).fetchone()
        if run_row is None:
            raise PublicationImportError("The publication import run could not be created.")
        run_id = str(run_row[0])
        self._connection.commit()
        conflicts = 0
        occurrences_by_id = {
            occurrence.source_occurrence_id: occurrence
            for occurrence in manifest.source_occurrences
        }
        citations_by_work: dict[str, list[PublicationCitationStatus]] = {}
        for citation in manifest.citation_statuses:
            citations_by_work.setdefault(citation.final_work_id, []).append(citation)
        works_by_applicant: dict[str, list[PublicationWork]] = {}
        for work in manifest.works:
            works_by_applicant.setdefault(work.workbook_applicant, []).append(work)
        try:
            for row_number, applicant in enumerate(manifest.applicants, start=1):
                application_id = application_ids[applicant.workbook_applicant]
                applicant_hash = _payload_hash(applicant.raw)
                import_row = self._connection.execute(
                    "INSERT dbo.ImportRow "
                    "(ImportRunId, SourceRowNumber, ApplicationId, SourceRowSha256, MatchStatus) "
                    "OUTPUT CONVERT(varchar(36), inserted.ImportRowId) "
                    "VALUES (?, ?, ?, CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), 'MATCHED')",
                    run_id,
                    row_number,
                    application_id,
                    applicant_hash,
                ).fetchone()
                if import_row is None:
                    raise PublicationImportError("A publication import row could not be created.")
                import_row_id = str(import_row[0])
                for work in works_by_applicant.get(applicant.workbook_applicant, []):
                    publication_id, work_conflicts = self._upsert_publication(
                        application_id,
                        run_id,
                        import_row_id,
                        work,
                        manifest.source_occurrences,
                    )
                    conflicts += work_conflicts
                    for occurrence_id in work.source_occurrence_ids:
                        self._record_occurrence(
                            publication_id,
                            run_id,
                            occurrences_by_id[occurrence_id],
                        )
                    self._record_metadata(
                        publication_id,
                        run_id,
                        manifest.generated_at_utc,
                        work,
                    )
                    for citation in citations_by_work[work.final_work_id]:
                        self._record_citation(publication_id, run_id, citation)
                self._connection.commit()
            self._connection.execute(
                "UPDATE dbo.ImportRun SET RunStatus = 'COMPLETED', CompletedAtUtc = SYSUTCDATETIME() "
                "WHERE ImportRunId = ? "
                "AND ImportFingerprintSha256 = CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)) "
                "AND RunStatus = 'RUNNING'",
                run_id,
                fingerprint,
            )
            self._connection.commit()
        except Exception as error:
            self._connection.rollback()
            self._connection.execute(
                "UPDATE dbo.ImportRun SET RunStatus = 'FAILED', CompletedAtUtc = NULL "
                "WHERE ImportRunId = ? AND RunStatus = 'RUNNING'",
                run_id,
            )
            self._connection.commit()
            if isinstance(error, PublicationImportError):
                raise
            raise PublicationImportError("The publication import failed.") from error
        return PublicationImportResult(
            ImportMode.APPLY,
            fingerprint,
            len(manifest.applicants),
            len(manifest.works),
            len(manifest.source_occurrences),
            len(manifest.citation_statuses),
            run_id,
            False,
            conflicts,
        )

    def _upsert_publication(
        self,
        application_id: str,
        run_id: str,
        import_row_id: str,
        work: PublicationWork,
        occurrences: Sequence[PublicationSourceOccurrence],
    ) -> tuple[str, int]:
        identity = publication_identity(work, occurrences)
        incoming = _canonical_database_values(work)
        select_columns = (
            "CONVERT(varchar(36), ApplicationPublicationId), Doi, HttpLink, AuthorsText, "
            "Title, JournalText, VolumeText, PagesText, PublicationYear"
        )
        existing_row = None
        if incoming["doi"] is not None:
            existing_row = self._connection.execute(
                f"SELECT TOP (1) {select_columns} FROM dbo.ApplicationPublication "
                "WHERE ApplicationId = ? AND Doi = ?",
                application_id,
                incoming["doi"],
            ).fetchone()
        if existing_row is None:
            existing_row = self._connection.execute(
                f"SELECT TOP (1) {select_columns} FROM dbo.ApplicationPublication "
                "WHERE ApplicationId = ? AND ManifestWorkKey = ?",
                application_id,
                work.final_work_id,
            ).fetchone()
        if existing_row is None:
            existing_row = self._connection.execute(
                f"SELECT TOP (1) {select_columns} FROM dbo.ApplicationPublication "
                "WHERE ApplicationId = ? "
                "AND PublicationIdentitySha256 = CONVERT(binary(32), CONVERT(varbinary(32), ?, 2))",
                application_id,
                identity,
            ).fetchone()
        if existing_row is None:
            publication_row = self._connection.execute(
                "INSERT dbo.ApplicationPublication "
                "(ApplicationId, CreatedByImportRunId, PublicationIdentitySha256, ManifestWorkKey, "
                "Doi, HttpLink, AuthorsText, Title, JournalText, VolumeText, PagesText, PublicationYear, ResolutionStatus) "
                "OUTPUT CONVERT(varchar(36), inserted.ApplicationPublicationId) "
                "VALUES (?, ?, CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                application_id,
                run_id,
                identity,
                work.final_work_id,
                incoming["doi"],
                incoming["http_link"],
                incoming["authors_text"],
                incoming["title"],
                incoming["journal_text"],
                incoming["volume_text"],
                incoming["pages_text"],
                incoming["publication_year"],
                work.resolution.status,
            ).fetchone()
            if publication_row is None:
                raise PublicationImportError("A publication row could not be created.")
            return str(publication_row[0]), 0

        publication_id = str(existing_row[0])
        existing = dict(zip(_CANONICAL_DATABASE_FIELDS, existing_row[1:], strict=True))
        fills, conflicts = reconcile_canonical_values(existing, incoming)
        if fills:
            self._connection.execute(
                "UPDATE dbo.ApplicationPublication SET "
                "Doi = COALESCE(Doi, ?), HttpLink = COALESCE(HttpLink, ?), "
                "AuthorsText = COALESCE(AuthorsText, ?), Title = COALESCE(Title, ?), "
                "JournalText = COALESCE(JournalText, ?), VolumeText = COALESCE(VolumeText, ?), "
                "PagesText = COALESCE(PagesText, ?), PublicationYear = COALESCE(PublicationYear, ?) "
                "WHERE ApplicationPublicationId = ?",
                *(incoming[field] for field in _CANONICAL_DATABASE_FIELDS),
                publication_id,
            )
        for field, (old_value, new_value) in conflicts.items():
            detail_hash = _payload_hash(
                {"field": field, "existing": old_value, "incoming": new_value}
            )
            self._connection.execute(
                "INSERT dbo.ImportException "
                "(ImportRunId, ImportRowId, ExceptionCode, DetailSha256) "
                "VALUES (?, ?, ?, CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)))",
                run_id,
                import_row_id,
                f"PUBLICATION_CONFLICT_{field.upper()}",
                detail_hash,
            )
        return publication_id, len(conflicts)

    def _record_occurrence(
        self,
        publication_id: str,
        run_id: str,
        occurrence: PublicationSourceOccurrence,
    ) -> None:
        locator_hash = _payload_hash(
            {
                "source_artifact": occurrence.source_artifact,
                "source_occurrence_id": occurrence.source_occurrence_id,
                "source_record_index": occurrence.source_record_index,
                "source_record_position": occurrence.source_record_position,
            }
        )
        payload_hash = _payload_hash(occurrence.raw)
        raw_citation_value = occurrence.source_record.get("raw_citation_text")
        raw_citation = (
            raw_citation_value
            if isinstance(raw_citation_value, str) and raw_citation_value.strip()
            else occurrence.normalized_raw_citation
        )
        page_value = occurrence.source_record.get("pdf_page")
        source_page = page_value if isinstance(page_value, int) and page_value > 0 else None
        self._connection.execute(
            "IF NOT EXISTS "
            "(SELECT 1 FROM dbo.ApplicationPublicationSourceOccurrence "
            "WHERE ApplicationPublicationId = ? "
            "AND SourceLocatorSha256 = CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)) "
            "AND PayloadSha256 = CONVERT(binary(32), CONVERT(varbinary(32), ?, 2))) "
            "INSERT dbo.ApplicationPublicationSourceOccurrence "
            "(ApplicationPublicationId, ImportRunId, SourceType, SourceLocatorSha256, "
            "SourcePage, RawCitation, PayloadSha256) "
            "VALUES (?, ?, 'DOSSIER', CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), ?, ?, "
            "CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)))",
            publication_id,
            locator_hash,
            payload_hash,
            publication_id,
            run_id,
            locator_hash,
            source_page,
            raw_citation,
            payload_hash,
        )

    def _record_metadata(
        self,
        publication_id: str,
        run_id: str,
        observed_at_utc: str,
        work: PublicationWork,
    ) -> None:
        source_code = "CROSSREF" if "CROSSREF" in work.resolution.method else "DOSSIER"
        metadata_json = _canonical_json(work.raw)
        payload_hash = hashlib.sha256(metadata_json.encode("utf-8")).hexdigest()
        self._connection.execute(
            "IF NOT EXISTS (SELECT 1 FROM dbo.PublicationMetadataObservation "
            "WHERE ApplicationPublicationId = ? AND SourceCode = ? "
            "AND PayloadSha256 = CONVERT(binary(32), CONVERT(varbinary(32), ?, 2))) "
            "INSERT dbo.PublicationMetadataObservation "
            "(ApplicationPublicationId, ImportRunId, SourceCode, SourceIdentifier, MetadataJson, ObservedAtUtc, PayloadSha256) "
            "VALUES (?, ?, ?, ?, ?, CONVERT(datetime2(7), ?, 127), "
            "CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)))",
            publication_id,
            source_code,
            payload_hash,
            publication_id,
            run_id,
            source_code,
            work.canonical_metadata.doi or work.final_work_id,
            metadata_json,
            observed_at_utc,
            payload_hash,
        )

    def _record_citation(
        self,
        publication_id: str,
        run_id: str,
        citation: PublicationCitationStatus,
    ) -> None:
        evidence_json = _canonical_json({"evidence": citation.evidence})
        payload_hash = _payload_hash(citation.raw)
        self._connection.execute(
            "IF NOT EXISTS (SELECT 1 FROM dbo.PublicationCitationObservation "
            "WHERE ApplicationPublicationId = ? AND SourceCode = ? "
            "AND PayloadSha256 = CONVERT(binary(32), CONVERT(varbinary(32), ?, 2))) "
            "INSERT dbo.PublicationCitationObservation "
            "(ApplicationPublicationId, ImportRunId, SourceCode, CitationCount, CitationStatus, "
            "EvidenceJson, ObservedAtUtc, PayloadSha256) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)))",
            publication_id,
            citation.source,
            payload_hash,
            publication_id,
            run_id,
            citation.source,
            citation.count,
            citation.status,
            evidence_json,
            payload_hash,
        )


def manifest_fingerprint(raw_bytes: bytes) -> str:
    return hashlib.sha256(
        raw_bytes + b"\0" + PUBLICATION_IMPORTER_VERSION.encode("ascii")
    ).hexdigest()


def run_publication_import(
    raw_bytes: bytes,
    *,
    mode: ImportMode,
    repository_factory: Callable[[], PublicationRepository],
    expected: ManifestCounts = PRODUCTION_COUNTS,
) -> PublicationImportResult:
    manifest = load_publication_manifest(raw_bytes, expected=expected)
    fingerprint = manifest_fingerprint(raw_bytes)
    if mode == ImportMode.PLAN_ONLY:
        return PublicationImportResult(
            mode, fingerprint, len(manifest.applicants), len(manifest.works),
            len(manifest.source_occurrences), len(manifest.citation_statuses),
            None, False, 0,
        )
    if mode != ImportMode.APPLY:
        raise PublicationImportError("The publication import mode is invalid.")
    return repository_factory().apply(manifest, fingerprint)


_LEGACY_QUEUE_FIELDS = (
    "applicant", "final_work_id", "doi", "title", "year",
    "google_scholar_search_url", "citation_count", "result_url",
    "observed_at_utc", "reviewer",
)
GOOGLE_SCHOLAR_QUEUE_FIELDS = (
    "applicant", "final_work_id", "doi", "title", "year",
    "google_scholar_search_url", "citation_status", "citation_count",
    "result_url", "observed_at_utc", "reviewer",
)


def write_google_scholar_queue(manifest: PublicationManifest, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    preserved_reviews: dict[str, dict[str, str]] = {}
    if output.exists():
        with output.open(newline="", encoding="utf-8-sig") as existing_handle:
            reader = csv.DictReader(existing_handle)
            fieldnames = tuple(reader.fieldnames or ())
            if fieldnames not in {_LEGACY_QUEUE_FIELDS, GOOGLE_SCHOLAR_QUEUE_FIELDS}:
                raise PublicationImportError(
                    "The existing Google Scholar queue has an unexpected schema."
                )
            for row in reader:
                work_id = row["final_work_id"]
                if work_id in preserved_reviews:
                    raise PublicationImportError(
                        "The existing Google Scholar queue has duplicate work identifiers."
                    )
                status = row.get("citation_status", "")
                if fieldnames == _LEGACY_QUEUE_FIELDS and not status and row["citation_count"]:
                    status = "OBSERVED"
                preserved_reviews[work_id] = {
                    "citation_status": status,
                    **{
                        field: row[field]
                        for field in ("citation_count", "result_url", "observed_at_utc", "reviewer")
                    },
                }
    temporary_handle = tempfile.NamedTemporaryFile(
        "w",
        newline="",
        encoding="utf-8-sig",
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(temporary_handle.name)
    try:
        handle = temporary_handle
        writer = csv.DictWriter(handle, fieldnames=GOOGLE_SCHOLAR_QUEUE_FIELDS)
        writer.writeheader()
        for work in sorted(
            manifest.works, key=lambda item: (item.workbook_applicant.casefold(), item.final_work_id)
        ):
            metadata = work.canonical_metadata
            query = metadata.doi or metadata.title or work.final_work_id
            review = preserved_reviews.get(work.final_work_id, {})
            writer.writerow(
                {
                    "applicant": _csv_safe(work.workbook_applicant),
                    "final_work_id": work.final_work_id,
                    "doi": metadata.doi or "",
                    "title": _csv_safe(metadata.title or ""),
                    "year": "" if metadata.year is None else str(metadata.year),
                    "google_scholar_search_url": "https://scholar.google.com/scholar?" + urlencode({"q": query}),
                    "citation_status": review.get("citation_status", ""),
                    "citation_count": review.get("citation_count", ""),
                    "result_url": review.get("result_url", ""),
                    "observed_at_utc": review.get("observed_at_utc", ""),
                    "reviewer": review.get("reviewer", ""),
                }
            )
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(temporary, output)
    except Exception:
        temporary_handle.close()
        temporary.unlink(missing_ok=True)
        raise


def _csv_safe(value: str) -> str:
    stripped = value.lstrip()
    if stripped.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
