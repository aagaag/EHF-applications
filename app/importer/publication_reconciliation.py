"""Additive reconciliation of parsed PDF publication evidence into a manifest."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import html
import json
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from app.importer.publication_extraction import (
    GrobidCitationParser,
    DocumentExtractionAudit,
    PublicationCandidate,
    PublicationClassification,
    ParsedPublication,
    classify_publication,
    extract_corpus,
    fallback_parse_candidate,
    iter_candidates,
)
from app.importer.publications import ManifestCounts, load_publication_manifest
from app.importer.publication_resolution import CrossrefBibliographicResolver


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    document: dict[str, Any]
    audit_rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class CorpusRunResult:
    paths: dict[str, Path]
    manifest_counts: ManifestCounts
    accepted_counts_before: dict[str, int]
    accepted_counts_after: dict[str, int]


_NON_APPLICANT_DIRECTORIES = {"selection committee", "summary table"}


def map_applicant_folders(
    source_root: Path, applicants: Sequence[Mapping[str, Any]]
) -> dict[str, str]:
    """Map human-named source folders to canonical applicant names."""
    names = [str(applicant["workbook_applicant"]) for applicant in applicants]
    mapping: dict[str, str] = {}
    for directory in sorted(
        (path for path in source_root.iterdir() if path.is_dir()),
        key=lambda path: path.name.casefold(),
    ):
        folder_key = "".join(character for character in _fold(directory.name) if character.isalnum())
        if _fold(directory.name) in _NON_APPLICANT_DIRECTORIES:
            continue
        matches = [
            name
            for name in names
            if folder_key
            and folder_key
            in "".join(character for character in _fold(name) if character.isalnum())
        ]
        if len(matches) == 1:
            mapping[directory.name] = matches[0]
        elif any(directory.rglob("*.pdf")):
            raise ValueError(
                f"Applicant folder {directory.name!r} has {len(matches)} manifest matches."
            )
    return mapping


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def normalize_title(value: str | None) -> str:
    if not value:
        return ""
    plain = re.sub(r"<[^>]*>", "", html.unescape(value))
    return "".join(character for character in _fold(plain) if character.isalnum())


def _review_rank(work: Mapping[str, Any]) -> int:
    disposition = work["resolution"]["evidence"].get("review_disposition")
    return {
        "PUBLISHED": 5,
        "ACCEPTED_PREPRINT": 4,
        "UNDER_PREPARATION": 3,
        "PENDING_REVIEW": 2,
        "NON_PUBLICATION": 1,
    }.get(disposition, 0)


def _quarantine_empty_legacy_works(document: dict[str, Any]) -> set[str]:
    """Mark fieldless legacy parser rows as non-publication artifacts."""
    touched: set[str] = set()
    for work in document["works"]:
        metadata = work["canonical_metadata"]
        meaningful = any(
            metadata.get(field) not in (None, "")
            for field in ("doi", "authors_text", "title", "journal", "year")
        )
        evidence = work["resolution"]["evidence"]
        disposition = evidence.get("review_disposition")
        if meaningful or disposition not in (None, "PENDING_REVIEW"):
            continue
        evidence.update(
            {
                "review_disposition": "NON_PUBLICATION",
                "review_reason": "Empty legacy parser artifact with no bibliographic fields.",
                "review_evidence": {
                    "verification_method": "CORPUS_PDF_REEXTRACTION_EMPTY_ARTIFACT",
                    "previous_disposition": disposition,
                },
            }
        )
        touched.add(work["applicant_folder"])
    return touched


def _deduplicate_exact_title_works(document: dict[str, Any]) -> set[str]:
    """Quarantine applicant-scoped exact-title copies without deleting database identities."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for work in document["works"]:
        title = normalize_title(work["canonical_metadata"].get("title"))
        if len(title) >= 16:
            grouped.setdefault((work["applicant_folder"], title), []).append(work)

    touched: set[str] = set()
    for (folder, _title), works in grouped.items():
        if len(works) < 2:
            continue
        primary = max(
            works,
            key=lambda work: (
                _review_rank(work),
                bool(work["canonical_metadata"].get("doi")),
                work["resolution"]["status"] == "RESOLVED",
            ),
        )
        primary_id = primary["final_work_id"]
        for duplicate in works:
            if duplicate is primary:
                continue
            evidence = duplicate["resolution"]["evidence"]
            evidence.update(
                {
                    "review_disposition": "NON_PUBLICATION",
                    "review_reason": f"Exact-title duplicate of canonical work {primary_id}.",
                    "review_evidence": {
                        "verification_method": "CORPUS_EXACT_TITLE_DUPLICATE",
                        "canonical_work_id": primary_id,
                    },
                }
            )
            touched.add(folder)
    return touched


def _stable_token(*values: object) -> str:
    payload = "\0".join(str(value) for value in values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def _occurrence_id(candidate: PublicationCandidate) -> str:
    return "parser-occ-" + _stable_token(
        candidate.applicant_name,
        candidate.filename,
        candidate.page_start,
        candidate.page_end,
        candidate.normalized_citation,
    )


def _source_work_id(candidate: PublicationCandidate) -> str:
    return "parser-source-" + _stable_token(
        candidate.applicant_name, candidate.normalized_citation
    )


def _final_work_id(candidate: PublicationCandidate, parsed: ParsedPublication) -> str:
    return "parser-" + _stable_token(
        candidate.applicant_name,
        parsed.doi or "",
        normalize_title(parsed.title),
        parsed.year or "",
        candidate.normalized_citation,
    )


def _authors_text(parsed: ParsedPublication) -> str | None:
    return "; ".join(parsed.authors) if parsed.authors else None


def _parse_candidate(
    candidate: PublicationCandidate,
    citation_parser: Callable[[str], ParsedPublication] | None,
) -> ParsedPublication:
    fallback = fallback_parse_candidate(candidate)
    if citation_parser is None:
        return fallback
    try:
        structured = citation_parser(candidate.raw_citation)
    except Exception:
        return fallback
    return ParsedPublication(
        authors=structured.authors or fallback.authors,
        title=structured.title or fallback.title,
        journal=structured.journal or fallback.journal,
        volume=structured.volume or fallback.volume,
        issue=structured.issue or fallback.issue,
        pages=structured.pages or fallback.pages,
        year=structured.year or fallback.year,
        doi=structured.doi or fallback.doi,
        url=structured.url or fallback.url,
        raw_citation=candidate.raw_citation,
        parser_method=f"{structured.parser_method}+deterministic",
        field_evidence=tuple(dict.fromkeys((*structured.field_evidence, *fallback.field_evidence))),
    )


def _canonical_metadata(parsed: ParsedPublication) -> dict[str, Any]:
    doi = parsed.doi.casefold() if parsed.doi else None
    return {
        "doi": doi,
        "doi_url": f"https://doi.org/{doi}" if doi else None,
        "authors_text": _authors_text(parsed),
        "title": parsed.title,
        "journal": parsed.journal,
        "volume": parsed.volume,
        "pages": parsed.pages,
        "year": parsed.year,
    }


def _complete_published_metadata(metadata: Mapping[str, Any]) -> bool:
    return all(metadata.get(field) not in (None, "") for field in ("authors_text", "title", "journal", "year"))


def _review_values(
    candidate: PublicationCandidate,
    parsed: ParsedPublication,
    classification: PublicationClassification,
) -> dict[str, Any]:
    return {
        "review_disposition": classification.disposition,
        "review_reason": (
            "Corpus-wide PDF re-extraction: " + classification.reason
        ),
        "review_evidence": {
            "parser_method": parsed.parser_method,
            "parser_confidence": classification.confidence,
            "source_artifact": candidate.filename,
            "source_page_start": candidate.page_start,
            "source_page_end": candidate.page_end,
            "section_label": candidate.section_label,
            "segmentation_method": candidate.segmentation_method,
            "field_evidence": list(parsed.field_evidence),
        },
    }


def _classification_for_metadata(
    classification: PublicationClassification, metadata: Mapping[str, Any]
) -> PublicationClassification:
    if classification.disposition != "PUBLISHED" or _complete_published_metadata(metadata):
        return classification
    missing = [
        field
        for field in ("authors_text", "title", "journal", "year")
        if metadata.get(field) in (None, "")
    ]
    return PublicationClassification(
        "PENDING_REVIEW", 0.35, "; ".join(f"missing {field}" for field in missing)
    )


def _match_work(
    works: Sequence[dict[str, Any]],
    *,
    applicant_folder: str,
    parsed: ParsedPublication,
    raw_citation: str,
) -> tuple[dict[str, Any] | None, str | None]:
    applicant_works = [
        work
        for work in works
        if work["applicant_folder"] == applicant_folder
        and work["resolution"]["evidence"].get("review_disposition") != "NON_PUBLICATION"
    ]
    if parsed.doi:
        doi = parsed.doi.casefold()
        doi_matches = [
            work
            for work in applicant_works
            if (work["canonical_metadata"].get("doi") or "").casefold() == doi
        ]
        if len(doi_matches) == 1:
            return doi_matches[0], "MATCHED_DOI"

    raw_key = normalize_title(raw_citation)
    embedded_by_title: dict[str, list[dict[str, Any]]] = {}
    for work in applicant_works:
        existing_title = normalize_title(work["canonical_metadata"].get("title"))
        if len(existing_title) >= 16 and existing_title in raw_key:
            embedded_by_title.setdefault(existing_title, []).append(work)
    maximal_titles = {
        title
        for title in embedded_by_title
        if not any(title != other and title in other for other in embedded_by_title)
    }
    if len(maximal_titles) > 1:
        return None, "AMBIGUOUS_MULTIPLE_TITLES"
    embedded_all = [
        work for title in maximal_titles for work in embedded_by_title[title]
    ]

    title = normalize_title(parsed.title)
    title_matches = (
        [
            work
            for work in applicant_works
            if normalize_title(work["canonical_metadata"].get("title")) == title
        ]
        if title
        else []
    )
    compatible: list[dict[str, Any]] = []
    for work in title_matches:
        existing_year = work["canonical_metadata"].get("year")
        if parsed.year is None or existing_year is None or abs(parsed.year - existing_year) <= 1:
            compatible.append(work)
    if len(compatible) == 1:
        return compatible[0], "MATCHED_TITLE"
    if len(compatible) > 1 and parsed.year is not None:
        exact = [
            work for work in compatible if work["canonical_metadata"].get("year") == parsed.year
        ]
        if len(exact) == 1:
            return exact[0], "MATCHED_TITLE"

    embedded: list[dict[str, Any]] = []
    for work in embedded_all:
        existing_title = normalize_title(work["canonical_metadata"].get("title"))
        existing_year = work["canonical_metadata"].get("year")
        year_compatible = (
            parsed.year is None
            or existing_year is None
            or abs(parsed.year - existing_year) <= 1
        )
        if existing_title and year_compatible:
            embedded.append(work)
    if len(embedded) == 1:
        return embedded[0], "MATCHED_TITLE_IN_CITATION"
    return None, None


def _add_occurrence(
    document: dict[str, Any],
    work: dict[str, Any],
    candidate: PublicationCandidate,
    parsed: ParsedPublication,
) -> tuple[str, bool]:
    occurrence_id = _occurrence_id(candidate)
    if any(
        occurrence["source_occurrence_id"] == occurrence_id
        for occurrence in document["source_occurrences"]
    ):
        return occurrence_id, False
    source_work_id = _source_work_id(candidate)
    occurrence = {
        "source_occurrence_id": occurrence_id,
        "final_work_id": work["final_work_id"],
        "source_work_id": source_work_id,
        "applicant_folder": work["applicant_folder"],
        "source_artifact": candidate.filename,
        "source_record_index": candidate.line_start,
        "source_record_position": candidate.page_start,
        "normalized_doi_candidates": [parsed.doi.casefold()] if parsed.doi else [],
        "normalized_raw_citation": candidate.raw_citation,
        "source_record": {
            "raw_citation": candidate.raw_citation,
            "source_page_start": candidate.page_start,
            "source_page_end": candidate.page_end,
            "source_line_start": candidate.line_start,
            "source_line_end": candidate.line_end,
            "section_label": candidate.section_label,
            "segmentation_method": candidate.segmentation_method,
            "parser_method": parsed.parser_method,
        },
    }
    document["source_occurrences"].append(occurrence)
    work["source_occurrence_ids"].append(occurrence_id)
    if source_work_id not in work["source_work_ids"]:
        work["source_work_ids"].append(source_work_id)
    return occurrence_id, True


def _reconcile_review(
    work: dict[str, Any],
    candidate: PublicationCandidate,
    parsed: ParsedPublication,
    classification: PublicationClassification,
) -> str:
    evidence = work["resolution"]["evidence"]
    current = evidence.get("review_disposition")
    if current and current != "PENDING_REVIEW":
        return "PRESERVED_EXPLICIT_REVIEW"
    if (
        current is None
        and work["resolution"]["status"] == "RESOLVED"
        and classification.disposition == "PENDING_REVIEW"
    ):
        return "PRESERVED_RESOLVED_PUBLICATION"
    classification = _classification_for_metadata(classification, work["canonical_metadata"])
    evidence.update(_review_values(candidate, parsed, classification))
    return "PROMOTED_PENDING" if current == "PENDING_REVIEW" else "ADDED_EXPLICIT_REVIEW"


def _citation_statuses(work_id: str) -> list[dict[str, Any]]:
    evidence = "Corpus-wide applicant PDF publication re-extraction, 2026-09-22."
    return [
        {
            "final_work_id": work_id,
            "source": "GOOGLE_SCHOLAR",
            "count": None,
            "status": "MANUAL_REQUIRED",
            "evidence": evidence,
        },
        {
            "final_work_id": work_id,
            "source": "BIORXIV",
            "count": None,
            "status": "NOT_AVAILABLE_FROM_SOURCE",
            "evidence": evidence,
        },
        {
            "final_work_id": work_id,
            "source": "MEDRXIV",
            "count": None,
            "status": "NOT_AVAILABLE_FROM_SOURCE",
            "evidence": evidence,
        },
    ]


def _update_summary(document: dict[str, Any], touched_folders: set[str]) -> None:
    works = document["works"]
    counts = Counter(work["applicant_folder"] for work in works)
    for applicant in document["applicants"]:
        count = counts[applicant["applicant_folder"]]
        applicant["source_preliminary_unique_work_count"] = count
        applicant["final_unique_work_count"] = count
        reported = applicant.get("workbook_reported_total")
        applicant["difference_unique_minus_reported"] = (
            count - reported if isinstance(reported, int) else None
        )
        if applicant["applicant_folder"] in touched_folders:
            applicant["status"] = "CORPUS_PDF_REEXTRACTION_REPAIRED"

    resolution_counts = Counter(work["resolution"]["status"] for work in works)
    completeness = {
        field: sum(work["canonical_metadata"].get(field) not in (None, "") for work in works)
        for field in ("doi", "doi_url", "authors_text", "title", "journal", "volume", "pages", "year")
    }
    completeness["fully_complete_canonical_records"] = sum(
        all(value not in (None, "") for value in work["canonical_metadata"].values())
        for work in works
    )
    summary = document["summary"]
    summary.update(
        {
            "source_preliminary_unique_work_total": len(works),
            "source_occurrence_total": len(document["source_occurrences"]),
            "final_unique_work_total": len(works),
            "pre_merge_resolved_source_work_total": resolution_counts["RESOLVED"],
            "resolved_doi_work_total": resolution_counts["RESOLVED"],
            "unresolved_work_total": resolution_counts["UNRESOLVED"],
            "ambiguous_work_total": resolution_counts["AMBIGUOUS"],
            "duplicate_merge_total": len(document["source_occurrences"]) - len(works),
            "metadata_completeness": completeness,
        }
    )


def _self_hash(document: Mapping[str, Any]) -> str:
    clone = json.loads(json.dumps(document, ensure_ascii=False))
    clone["hashes"]["manifest_sha256_excluding_hash"] = None
    payload = json.dumps(
        clone, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _finish(document: dict[str, Any], generated_at_utc: str, touched_folders: set[str]) -> None:
    document["generated_at_utc"] = generated_at_utc
    document["reconciliation_policy"]["conflicts"] = (
        "Corpus-wide PDF re-extraction fills missing canonical fields and promotes only missing or pending reviews; explicit nonpending reviews are preserved."
    )
    document["reconciliation_policy"]["deduplication"] = (
        "Applicant-scoped exact DOI, then normalized title with compatible publication year."
    )
    _update_summary(document, touched_folders)
    for name in document["validation"]:
        document["validation"][name] = True
    document["hashes"]["manifest_sha256_excluding_hash"] = None
    document["hashes"]["manifest_sha256_excluding_hash"] = _self_hash(document)


def reconcile_publication_manifest(
    base_document: Mapping[str, Any],
    candidates: Iterable[PublicationCandidate],
    *,
    citation_parser: Callable[[str], ParsedPublication] | None = None,
    bibliographic_resolver: Callable[
        [PublicationCandidate, ParsedPublication], ParsedPublication | None
    ]
    | None = None,
    generated_at_utc: str | None = None,
) -> ReconciliationResult:
    """Reconcile parsed candidates additively and return an import-ready manifest."""
    document: dict[str, Any] = copy.deepcopy(dict(base_document))
    repaired_folders = _quarantine_empty_legacy_works(document)
    repaired_folders.update(_deduplicate_exact_title_works(document))
    applicant_by_name = {
        applicant["workbook_applicant"]: applicant for applicant in document["applicants"]
    }
    audit_rows: list[dict[str, Any]] = []
    touched_folders: set[str] = set(repaired_folders)
    ordered = sorted(
        candidates,
        key=lambda item: (
            item.applicant_name.casefold(),
            item.filename.casefold(),
            item.page_start,
            item.line_start,
            item.normalized_citation,
        ),
    )
    for candidate in ordered:
        applicant = applicant_by_name.get(candidate.applicant_name)
        if applicant is None:
            raise ValueError(f"No manifest applicant mapping for {candidate.applicant_name!r}.")
        parsed = _parse_candidate(candidate, citation_parser)
        classification = classify_publication(parsed, section_status=candidate.status_hint)
        folder = applicant["applicant_folder"]
        work, match_action = _match_work(
            document["works"],
            applicant_folder=folder,
            parsed=parsed,
            raw_citation=candidate.raw_citation,
        )
        if match_action == "AMBIGUOUS_MULTIPLE_TITLES":
            audit_rows.append(
                {
                    "applicant": candidate.applicant_name,
                    "source_artifact": candidate.filename,
                    "page_start": candidate.page_start,
                    "page_end": candidate.page_end,
                    "raw_citation": candidate.raw_citation,
                    "parsed_title": parsed.title,
                    "parsed_journal": parsed.journal,
                    "parsed_year": parsed.year,
                    "parsed_doi": parsed.doi,
                    "classification": "PENDING_REVIEW",
                    "confidence": 0.0,
                    "final_work_id": None,
                    "source_occurrence_id": None,
                    "action": "SKIPPED_AMBIGUOUS_CITATION",
                    "decision_action": "SKIPPED_AMBIGUOUS_CITATION",
                }
            )
            continue
        if work is None and bibliographic_resolver is not None:
            try:
                resolved = bibliographic_resolver(candidate, parsed)
            except Exception:
                resolved = None
            if resolved is not None:
                parsed = resolved
                classification = classify_publication(
                    parsed, section_status=candidate.status_hint
                )
                work, match_action = _match_work(
                    document["works"],
                    applicant_folder=folder,
                    parsed=parsed,
                    raw_citation=candidate.raw_citation,
                )
        low_quality_pending = bool(
            classification.disposition == "PENDING_REVIEW"
            and (
                not parsed.title
                or classification.confidence <= 0.2
                or "credible title" in classification.reason
                or "non-narrative" in classification.reason
            )
        )
        if work is None and (
            classification.disposition == "NON_PUBLICATION" or low_quality_pending
        ):
            action = (
                "SKIPPED_NON_PUBLICATION"
                if classification.disposition == "NON_PUBLICATION"
                else "SKIPPED_UNPARSABLE_CITATION"
            )
            audit_rows.append(
                {
                    "applicant": candidate.applicant_name,
                    "source_artifact": candidate.filename,
                    "page_start": candidate.page_start,
                    "page_end": candidate.page_end,
                    "raw_citation": candidate.raw_citation,
                    "parsed_title": parsed.title,
                    "parsed_journal": parsed.journal,
                    "parsed_year": parsed.year,
                    "parsed_doi": parsed.doi,
                    "classification": classification.disposition,
                    "confidence": classification.confidence,
                    "final_work_id": None,
                    "source_occurrence_id": None,
                    "action": action,
                    "decision_action": action,
                }
            )
            continue
        if work is None:
            work_id = _final_work_id(candidate, parsed)
            metadata = _canonical_metadata(parsed)
            classification = _classification_for_metadata(classification, metadata)
            evidence = _review_values(candidate, parsed, classification)
            work = {
                "final_work_id": work_id,
                "applicant_folder": folder,
                "workbook_applicant": candidate.applicant_name,
                "source_work_ids": [],
                "representative_source_occurrence_id": _occurrence_id(candidate),
                "source_occurrence_ids": [],
                "canonical_metadata": metadata,
                "resolution": {
                    "status": "RESOLVED" if parsed.doi else "UNRESOLVED",
                    "method": "CORPUS_PDF_PARSER",
                    "evidence": evidence,
                },
            }
            document["works"].append(work)
            document["citation_source_statuses"].extend(_citation_statuses(work_id))
            action = "ADDED_WORK"
            decision_action = "ADDED_EXPLICIT_REVIEW"
        else:
            metadata = work["canonical_metadata"]
            for field, value in _canonical_metadata(parsed).items():
                if metadata.get(field) in (None, "") and value not in (None, ""):
                    metadata[field] = value
            if metadata.get("doi"):
                work["resolution"]["status"] = "RESOLVED"
            decision_action = _reconcile_review(
                work, candidate, parsed, classification
            )
            action = str(match_action)

        occurrence_id, added = _add_occurrence(document, work, candidate, parsed)
        if not added:
            action = "ALREADY_RECONCILED"
        touched_folders.add(folder)
        audit_rows.append(
            {
                "applicant": candidate.applicant_name,
                "source_artifact": candidate.filename,
                "page_start": candidate.page_start,
                "page_end": candidate.page_end,
                "raw_citation": candidate.raw_citation,
                "parsed_title": parsed.title,
                "parsed_journal": parsed.journal,
                "parsed_year": parsed.year,
                "parsed_doi": parsed.doi,
                "classification": classification.disposition,
                "confidence": classification.confidence,
                "final_work_id": work["final_work_id"],
                "source_occurrence_id": occurrence_id,
                "action": action,
                "decision_action": decision_action,
            }
        )

    timestamp = generated_at_utc or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    _finish(document, timestamp, touched_folders)
    return ReconciliationResult(document, tuple(audit_rows))


def write_reconciliation_artifacts(
    output_directory: Path,
    result: ReconciliationResult,
    document_audits: Sequence[DocumentExtractionAudit],
    *,
    stem: str = "p260922",
) -> dict[str, Path]:
    """Write an import manifest and document/candidate audit beside private inputs."""
    if not re.fullmatch(r"[a-z0-9-]+", stem):
        raise ValueError("Artifact stem must contain only lowercase letters, digits, and hyphens.")
    output_directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "manifest": output_directory / f"{stem}-manifest.json",
        "audit_json": output_directory / f"{stem}-audit.json",
        "audit_csv": output_directory / f"{stem}-audit.csv",
    }
    paths["manifest"].write_text(
        json.dumps(result.document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    documents = []
    for audit in document_audits:
        documents.append(
            {
                "source_path": audit.source_path,
                "source_sha256": audit.source_sha256,
                "page_count": audit.page_count,
                "pages_scanned": audit.pages_scanned,
                "extraction_modes": list(audit.extraction_modes),
                "issues": list(audit.issues),
                "candidate_count": len(audit.candidates),
                "candidates": [asdict(candidate) for candidate in audit.candidates],
            }
        )
    audit_document = {
        "summary": {
            "documents": len(document_audits),
            "pages": sum(audit.page_count for audit in document_audits),
            "candidates": sum(len(audit.candidates) for audit in document_audits),
            "documents_with_issues": sum(bool(audit.issues) for audit in document_audits),
        },
        "documents": documents,
        "reconciliation": list(result.audit_rows),
    }
    paths["audit_json"].write_text(
        json.dumps(audit_document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    reconciliation_by_source = {
        (
            row["source_artifact"],
            row["page_start"],
            row["page_end"],
            row["raw_citation"],
        ): row
        for row in result.audit_rows
    }
    fieldnames = [
        "source_path",
        "source_sha256",
        "pages_scanned",
        "document_issues",
        "applicant",
        "page_start",
        "page_end",
        "raw_citation",
        "parsed_title",
        "parsed_journal",
        "parsed_year",
        "parsed_doi",
        "classification",
        "confidence",
        "final_work_id",
        "action",
        "decision_action",
    ]
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for audit in document_audits:
        base = {
            "source_path": audit.source_path,
            "source_sha256": audit.source_sha256,
            "pages_scanned": audit.pages_scanned,
            "document_issues": ";".join(audit.issues),
        }
        if not audit.candidates:
            writer.writerow(base)
            continue
        for candidate in audit.candidates:
            row = reconciliation_by_source.get(
                (
                    candidate.filename,
                    candidate.page_start,
                    candidate.page_end,
                    candidate.raw_citation,
                ),
                {},
            )
            writer.writerow({**base, **{key: row.get(key) for key in fieldnames if key not in base}})
    paths["audit_csv"].write_text(stream.getvalue(), encoding="utf-8")
    return paths


def _manifest_counts(document: Mapping[str, Any]) -> ManifestCounts:
    return ManifestCounts(
        len(document["applicants"]),
        len(document["works"]),
        len(document["source_occurrences"]),
        len(document["citation_source_statuses"]),
    )


def _accepted_counts(document: Mapping[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for work in document["works"]:
        evidence = work["resolution"]["evidence"]
        disposition = evidence.get("review_disposition")
        if disposition is None and work["resolution"]["status"] == "RESOLVED":
            disposition = "PUBLISHED"
        if disposition in {"PUBLISHED", "ACCEPTED_PREPRINT", "UNDER_PREPARATION"}:
            counts[work["applicant_folder"]] += 1
    return dict(counts)


def run_corpus_reconciliation(
    base_manifest_path: Path,
    source_root: Path,
    output_directory: Path,
    *,
    grobid_url: str | None = None,
    resolve_public_bibliography: bool = False,
    stem: str = "p260922",
) -> CorpusRunResult:
    """Extract every mapped PDF, reconcile it, validate it, and write private artifacts."""
    base_document = json.loads(base_manifest_path.read_text(encoding="utf-8-sig"))
    base_counts = _manifest_counts(base_document)
    load_publication_manifest(
        json.dumps(base_document, ensure_ascii=False).encode("utf-8"), expected=base_counts
    )
    mapping = map_applicant_folders(source_root, base_document["applicants"])
    if len(mapping) != len(base_document["applicants"]):
        missing = sorted(
            set(applicant["workbook_applicant"] for applicant in base_document["applicants"])
            - set(mapping.values())
        )
        raise ValueError(f"Applicant source-folder mapping is incomplete: {missing}.")
    audits = extract_corpus(source_root, mapping)
    parser = GrobidCitationParser(grobid_url).parse if grobid_url else None
    public_resolver = (
        CrossrefBibliographicResolver(
            cache_path=output_directory / f"{stem}-crossref-cache.json"
        ).resolve
        if resolve_public_bibliography
        else None
    )
    result = reconcile_publication_manifest(
        base_document,
        iter_candidates(audits),
        citation_parser=parser,
        bibliographic_resolver=public_resolver,
    )
    final_counts = _manifest_counts(result.document)
    load_publication_manifest(
        json.dumps(result.document, ensure_ascii=False).encode("utf-8"),
        expected=final_counts,
    )
    before = _accepted_counts(base_document)
    after = _accepted_counts(result.document)
    decreased = {
        folder: (count, after.get(folder, 0))
        for folder, count in before.items()
        if after.get(folder, 0) < count
    }
    if decreased:
        raise ValueError(f"Accepted publication counts decreased: {decreased}.")
    paths = write_reconciliation_artifacts(
        output_directory, result, audits, stem=stem
    )
    return CorpusRunResult(paths, final_counts, before, after)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-extract and reconcile applicant publication PDFs into a private manifest."
    )
    parser.add_argument("--base-manifest", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--grobid-url")
    parser.add_argument("--resolve-public-bibliography", action="store_true")
    parser.add_argument("--stem", default="p260922")
    arguments = parser.parse_args(argv)
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    result = run_corpus_reconciliation(
        arguments.base_manifest,
        arguments.source_root,
        arguments.output_directory,
        grobid_url=arguments.grobid_url,
        resolve_public_bibliography=arguments.resolve_public_bibliography,
        stem=arguments.stem,
    )
    counts = result.manifest_counts
    print(
        json.dumps(
            {
                "paths": {name: str(path) for name, path in result.paths.items()},
                "counts": {
                    "applicants": counts.applicants,
                    "works": counts.works,
                    "source_occurrences": counts.source_occurrences,
                    "citation_statuses": counts.citation_statuses,
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
