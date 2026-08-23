"""Strict append-only import of reviewed Semantic Scholar citation counts."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import unicodedata
from collections.abc import Sequence
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from typing import Any
from urllib.parse import urlparse

from app.importer.publications import (
    ManifestCounts,
    PRODUCTION_COUNTS,
    PublicationManifest,
    load_publication_manifest,
    normalize_doi,
)
from app.importer.run import ImportMode


OPEN_CITATION_IMPORTER_VERSION = "2026.4-open-citations"
OPEN_CITATION_SOURCES = ("SEMANTIC_SCHOLAR",)
OPEN_CITATION_FIELDS = (
    "applicant",
    "final_work_id",
    "doi",
    "title",
    "year",
    "source_code",
    "citation_status",
    "citation_count",
    "source_identifier",
    "result_url",
    "matched_doi",
    "matched_title",
    "matched_authors",
    "observed_at_utc",
    "reviewer",
    "match_method",
)
_RESULT_HOSTS = {
    "OPENALEX": {"openalex.org", "api.openalex.org", "www.openalex.org"},
    "SEMANTIC_SCHOLAR": {
        "semanticscholar.org",
        "www.semanticscholar.org",
        "api.semanticscholar.org",
    },
}
_MATCH_METHODS = {
    "DOI_EXACT",
    "TITLE_EXACT",
    "RAW_CITATION_EXACT",
    "NO_CONFIDENT_MATCH",
}
_OPENALEX_ID_RE = re.compile(r"https://openalex\.org/W[0-9]+\Z")
_SEMANTIC_SCHOLAR_ID_RE = re.compile(r"[0-9a-f]{40}\Z")
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


class OpenCitationImportError(RuntimeError):
    """The citation snapshot or requested write is unsafe."""


@dataclass(frozen=True, slots=True)
class OpenCitationReview:
    applicant: str
    final_work_id: str
    source_code: str
    citation_status: str
    citation_count: int | None
    source_identifier: str
    result_url: str
    matched_doi: str
    matched_title: str
    matched_authors: str
    observed_at_utc: str
    reviewer: str
    match_method: str
    raw: dict[str, str]


@dataclass(frozen=True, slots=True)
class OpenCitationImportResult:
    fingerprint: str
    review_count: int
    observed_count: int
    not_found_count: int
    run_id: str | None
    reused_completed_run: bool


def _safe_text(value: str, label: str, maximum: int, *, required: bool = True) -> str:
    if value != value.strip() or len(value) > maximum or (required and not value):
        raise OpenCitationImportError(f"{label} is missing or invalid.")
    if value and value[0] in "=+-@":
        raise OpenCitationImportError(f"{label} contains an unsafe spreadsheet formula.")
    return value


def _utc_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise OpenCitationImportError(
            "observed_at_utc must be an ISO 8601 timestamp."
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise OpenCitationImportError("observed_at_utc must include the UTC offset.")
    if not 2000 <= parsed.year <= 2200:
        raise OpenCitationImportError("observed_at_utc has an invalid year.")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _result_url(value: str, source_code: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in _RESULT_HOSTS[source_code]:
        raise OpenCitationImportError(
            f"result_url must be an official {source_code} HTTPS URL."
        )
    return value


def _normalized_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", html.unescape(value))
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(_NON_WORD_RE.sub(" ", value.lower()).split())


def _validated_match_evidence(
    *,
    source: str,
    status: str,
    source_identifier: str,
    result_url: str,
    matched_doi: str,
    matched_title: str,
    matched_authors: str,
    match_method: str,
    work: Any,
    raw_citation: str,
) -> None:
    if status == "NOT_FOUND":
        if any((source_identifier, matched_doi, matched_title, matched_authors)):
            raise OpenCitationImportError(
                "NOT_FOUND rows must not retain matched publication evidence."
            )
        return
    if source == "OPENALEX":
        valid_identifier = bool(_OPENALEX_ID_RE.fullmatch(source_identifier))
        valid_url = result_url == source_identifier
    else:
        valid_identifier = bool(_SEMANTIC_SCHOLAR_ID_RE.fullmatch(source_identifier))
        valid_url = urlparse(result_url).path.endswith("/" + source_identifier)
    if not valid_identifier or not valid_url:
        raise OpenCitationImportError(
            f"source_identifier is invalid for {source}."
        )
    if not matched_title or not matched_authors:
        raise OpenCitationImportError(
            "OBSERVED rows require matched title and authors evidence."
        )
    expected_doi = work.canonical_metadata.doi or ""
    if match_method == "DOI_EXACT":
        if not expected_doi or matched_doi != expected_doi:
            raise OpenCitationImportError(
                "DOI_EXACT evidence must equal the manifest DOI."
            )
        return
    family_token = _normalized_text(work.workbook_applicant).split()[-1]
    if family_token not in _normalized_text(matched_authors).split():
        raise OpenCitationImportError(
            "Non-DOI matches must include the applicant author."
        )
    normalized_title = _normalized_text(matched_title)
    if match_method == "TITLE_EXACT":
        expected_title = _normalized_text(work.canonical_metadata.title or "")
        if not expected_title or normalized_title != expected_title:
            raise OpenCitationImportError(
                "TITLE_EXACT evidence must equal the manifest title."
            )
    elif (
        match_method == "RAW_CITATION_EXACT"
        and (len(normalized_title) < 20 or normalized_title not in _normalized_text(raw_citation))
    ):
        raise OpenCitationImportError(
            "RAW_CITATION_EXACT evidence must occur in the applicant citation."
        )


def load_open_citation_reviews(
    raw_bytes: bytes,
    manifest: PublicationManifest,
) -> tuple[OpenCitationReview, ...]:
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise OpenCitationImportError(
            "The open citation snapshot is not valid UTF-8 CSV."
        ) from error
    reader = csv.DictReader(StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != OPEN_CITATION_FIELDS:
        raise OpenCitationImportError("The open citation snapshot has an unexpected schema.")
    work_by_id = {work.final_work_id: work for work in manifest.works}
    raw_by_work: dict[str, list[str]] = {}
    for occurrence in manifest.source_occurrences:
        raw_by_work.setdefault(occurrence.final_work_id, []).append(
            occurrence.normalized_raw_citation
        )
    seen: set[tuple[str, str]] = set()
    reviews: list[OpenCitationReview] = []
    for row_number, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise OpenCitationImportError(f"Snapshot row {row_number} is malformed.")
        work_id = _safe_text(row["final_work_id"], "final_work_id", 80)
        source = row["source_code"]
        key = (work_id, source)
        if work_id not in work_by_id or source not in OPEN_CITATION_SOURCES or key in seen:
            raise OpenCitationImportError(
                "source_code must occur exactly once for every manifest work."
            )
        seen.add(key)
        work = work_by_id[work_id]
        expected_doi = work.canonical_metadata.doi or ""
        row_doi = normalize_doi(row["doi"]) if row["doi"] else ""
        expected_year = (
            "" if work.canonical_metadata.year is None else str(work.canonical_metadata.year)
        )
        if (
            row["applicant"] != work.workbook_applicant
            or row_doi != expected_doi
            or row["title"] != (work.canonical_metadata.title or "")
            or row["year"] != expected_year
        ):
            raise OpenCitationImportError(
                "A snapshot identity or bibliographic field disagrees with the reviewed manifest."
            )
        status = row["citation_status"]
        if status not in {"OBSERVED", "NOT_FOUND"}:
            raise OpenCitationImportError("citation_status must be OBSERVED or NOT_FOUND.")
        try:
            count = None if row["citation_count"] == "" else int(row["citation_count"])
        except ValueError as error:
            raise OpenCitationImportError(
                "citation_count must be a nonnegative integer."
            ) from error
        if count is not None and count < 0:
            raise OpenCitationImportError("citation_count must be a nonnegative integer.")
        if status == "OBSERVED" and count is None:
            raise OpenCitationImportError("OBSERVED reviews require citation_count.")
        if status == "NOT_FOUND" and count is not None:
            raise OpenCitationImportError("NOT_FOUND reviews must not have citation_count.")
        source_identifier = _safe_text(
            row["source_identifier"],
            "source_identifier",
            2048,
            required=status == "OBSERVED",
        )
        matched_title = _safe_text(
            row["matched_title"],
            "matched_title",
            2000,
            required=status == "OBSERVED",
        )
        matched_authors = _safe_text(
            row["matched_authors"],
            "matched_authors",
            8000,
            required=status == "OBSERVED",
        )
        matched_doi = normalize_doi(row["matched_doi"]) if row["matched_doi"] else ""
        match_method = row["match_method"]
        if match_method not in _MATCH_METHODS:
            raise OpenCitationImportError("match_method is invalid.")
        if status == "NOT_FOUND" and match_method != "NO_CONFIDENT_MATCH":
            raise OpenCitationImportError(
                "NOT_FOUND reviews require match_method NO_CONFIDENT_MATCH."
            )
        if status == "OBSERVED" and match_method == "NO_CONFIDENT_MATCH":
            raise OpenCitationImportError("OBSERVED reviews require a positive match_method.")
        result_url = _result_url(row["result_url"], source)
        _validated_match_evidence(
            source=source,
            status=status,
            source_identifier=source_identifier,
            result_url=result_url,
            matched_doi=matched_doi,
            matched_title=matched_title,
            matched_authors=matched_authors,
            match_method=match_method,
            work=work,
            raw_citation=" ".join(raw_by_work.get(work_id, ())),
        )
        reviews.append(
            OpenCitationReview(
                work.workbook_applicant,
                work_id,
                source,
                status,
                count,
                source_identifier,
                result_url,
                matched_doi,
                matched_title,
                matched_authors,
                _utc_timestamp(row["observed_at_utc"]),
                _safe_text(row["reviewer"], "reviewer", 255),
                match_method,
                dict(row),
            )
        )
    expected = {
        (work_id, source)
        for work_id in work_by_id
        for source in OPEN_CITATION_SOURCES
    }
    if seen != expected:
        raise OpenCitationImportError(
            "The snapshot must contain Semantic Scholar for every manifest work."
        )
    return tuple(reviews)


def open_citation_fingerprint(raw_bytes: bytes) -> str:
    return hashlib.sha256(
        raw_bytes + b"\0" + OPEN_CITATION_IMPORTER_VERSION.encode("ascii")
    ).hexdigest()


def run_open_citation_import(
    manifest_bytes: bytes,
    snapshot_bytes: bytes,
    *,
    mode: ImportMode,
    repository_factory: Callable[[], "SqlOpenCitationRepository"],
    expected: ManifestCounts = PRODUCTION_COUNTS,
) -> OpenCitationImportResult:
    manifest = load_publication_manifest(manifest_bytes, expected=expected)
    reviews = load_open_citation_reviews(snapshot_bytes, manifest)
    fingerprint = open_citation_fingerprint(snapshot_bytes)
    observed = sum(review.citation_status == "OBSERVED" for review in reviews)
    not_found = len(reviews) - observed
    if mode == ImportMode.PLAN_ONLY:
        return OpenCitationImportResult(
            fingerprint, len(reviews), observed, not_found, None, False
        )
    if mode != ImportMode.APPLY:
        raise OpenCitationImportError("The open citation import mode is invalid.")
    return repository_factory().apply(reviews, fingerprint)


class SqlOpenCitationRepository:
    """Privileged writer for immutable source-specific citation observations."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def apply(
        self, reviews: Sequence[OpenCitationReview], fingerprint: str
    ) -> OpenCitationImportResult:
        calls = self._connection.execute(
            "SELECT CONVERT(varchar(36), FellowshipCallId) "
            "FROM dbo.FellowshipCall WHERE CallCode = N'EHF-2026'"
        ).fetchall()
        if len(calls) != 1:
            raise OpenCitationImportError("The EHF-2026 call cannot be resolved uniquely.")
        call_id = str(calls[0][0])
        completed = self._connection.execute(
            "SELECT TOP (1) CONVERT(varchar(36), ImportRunId) FROM dbo.ImportRun "
            "WHERE FellowshipCallId = ? "
            "AND ImportFingerprintSha256 = CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)) "
            "AND ImporterVersion = ? AND RunStatus = 'COMPLETED' "
            "ORDER BY CompletedAtUtc DESC",
            call_id,
            fingerprint,
            OPEN_CITATION_IMPORTER_VERSION,
        ).fetchone()
        observed = sum(review.citation_status == "OBSERVED" for review in reviews)
        not_found = len(reviews) - observed
        if completed is not None:
            return OpenCitationImportResult(
                fingerprint, len(reviews), observed, not_found, str(completed[0]), True
            )

        publication_ids: dict[str, tuple[str, str]] = {}
        for review in reviews:
            if review.final_work_id in publication_ids:
                continue
            rows = self._connection.execute(
                "SELECT CONVERT(varchar(36), publication_row.ApplicationPublicationId), "
                "CONVERT(varchar(36), publication_row.ApplicationId) "
                "FROM dbo.ApplicationPublication AS publication_row "
                "JOIN dbo.Application AS application_row "
                "ON application_row.ApplicationId = publication_row.ApplicationId "
                "WHERE application_row.FellowshipCallId = ? "
                "AND publication_row.ManifestWorkKey = ?",
                call_id,
                review.final_work_id,
            ).fetchall()
            if len(rows) != 1:
                raise OpenCitationImportError(
                    "A reviewed work does not resolve to exactly one publication."
                )
            publication_ids[review.final_work_id] = (str(rows[0][0]), str(rows[0][1]))

        run = self._connection.execute(
            "INSERT dbo.ImportRun "
            "(FellowshipCallId, ImportFingerprintSha256, ImporterVersion, RunStatus, StartedByIdentity) "
            "OUTPUT CONVERT(varchar(36), inserted.ImportRunId) "
            "VALUES (?, CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), ?, 'RUNNING', "
            "'ISAB01_OPEN_CITATION_IMPORT')",
            call_id,
            fingerprint,
            OPEN_CITATION_IMPORTER_VERSION,
        ).fetchone()
        if run is None:
            raise OpenCitationImportError("The open citation run could not be created.")
        run_id = str(run[0])
        self._connection.commit()
        try:
            for row_number, review in enumerate(reviews, start=1):
                publication_id, application_id = publication_ids[review.final_work_id]
                payload = json.dumps(
                    review.raw,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                row_hash = hashlib.sha256(
                    f"{review.final_work_id}\0{review.source_code}\0{payload_hash}".encode(
                        "utf-8"
                    )
                ).hexdigest()
                imported = self._connection.execute(
                    "INSERT dbo.ImportRow "
                    "(ImportRunId, SourceRowNumber, ApplicationId, SourceRowSha256, MatchStatus) "
                    "OUTPUT CONVERT(varchar(36), inserted.ImportRowId) "
                    "VALUES (?, ?, ?, CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), 'MATCHED')",
                    run_id,
                    row_number,
                    application_id,
                    row_hash,
                ).fetchone()
                if imported is None:
                    raise OpenCitationImportError("An open citation row could not be recorded.")
                evidence = json.dumps(
                    {
                        "match_method": review.match_method,
                        "matched_doi": review.matched_doi or None,
                        "matched_title": review.matched_title or None,
                        "matched_authors": review.matched_authors or None,
                        "result_url": review.result_url,
                        "reviewer": review.reviewer,
                        "source_identifier": review.source_identifier or None,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                self._connection.execute(
                    "INSERT dbo.PublicationCitationObservation "
                    "(ApplicationPublicationId, ImportRunId, SourceCode, CitationCount, "
                    "CitationStatus, EvidenceJson, ObservedAtUtc, PayloadSha256) "
                    "VALUES (?, ?, ?, ?, ?, ?, CONVERT(datetime2(7), ?, 127), "
                    "CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)))",
                    publication_id,
                    run_id,
                    review.source_code,
                    review.citation_count,
                    review.citation_status,
                    evidence,
                    review.observed_at_utc,
                    payload_hash,
                )
            self._connection.execute(
                "UPDATE dbo.ImportRun SET RunStatus = 'COMPLETED', "
                "CompletedAtUtc = SYSUTCDATETIME() WHERE ImportRunId = ? "
                "AND RunStatus = 'RUNNING'",
                run_id,
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
            if isinstance(error, OpenCitationImportError):
                raise
            raise OpenCitationImportError("The open citation import failed.") from error
        return OpenCitationImportResult(
            fingerprint, len(reviews), observed, not_found, run_id, False
        )
