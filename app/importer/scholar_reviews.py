"""Strict append-only import of manually reviewed Google Scholar evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from typing import Any, Protocol
from urllib.parse import urlparse

from app.importer.publications import (
    GOOGLE_SCHOLAR_QUEUE_FIELDS,
    ManifestCounts,
    PRODUCTION_COUNTS,
    PublicationManifest,
    load_publication_manifest,
    normalize_doi,
)
from app.importer.run import ImportMode


SCHOLAR_REVIEW_IMPORTER_VERSION = "2026.4-google-scholar-review"
SCHOLAR_QUEUE_FIELDS = GOOGLE_SCHOLAR_QUEUE_FIELDS


class ScholarReviewImportError(RuntimeError):
    """The reviewed queue or requested import operation is unsafe."""


@dataclass(frozen=True, slots=True)
class ScholarReview:
    applicant: str
    final_work_id: str
    citation_status: str
    citation_count: int | None
    result_url: str
    observed_at_utc: str
    reviewer: str
    raw: dict[str, str]


@dataclass(frozen=True, slots=True)
class ScholarReviewImportResult:
    mode: ImportMode
    fingerprint: str
    review_count: int
    observed_count: int
    not_found_count: int
    run_id: str | None
    reused_completed_run: bool


class ScholarReviewRepository(Protocol):
    def apply(
        self, reviews: Sequence[ScholarReview], fingerprint: str
    ) -> ScholarReviewImportResult: ...


def _utc_timestamp(value: str, label: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ScholarReviewImportError(
            f"{label} must be an ISO 8601 timestamp."
        ) from error
    if parsed.tzinfo is None or not 2000 <= parsed.year <= 2200:
        raise ScholarReviewImportError(
            f"{label} must include a UTC offset and have a year from 2000 through 2200."
        )
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _scholar_url(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {
        "scholar.google.com",
        "scholar.googleusercontent.com",
    }:
        raise ScholarReviewImportError(f"{label} must be a Google Scholar HTTPS URL.")
    return value


def _safe_text(value: str, label: str, maximum: int) -> str:
    if not value or value != value.strip() or len(value) > maximum:
        raise ScholarReviewImportError(f"{label} is missing or invalid.")
    if value[0] in "=+-@":
        raise ScholarReviewImportError(f"{label} contains an unsafe spreadsheet formula.")
    return value


def load_scholar_reviews(
    raw_bytes: bytes,
    manifest: PublicationManifest,
) -> tuple[ScholarReview, ...]:
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ScholarReviewImportError(
            "The Google Scholar review queue is not valid UTF-8 CSV."
        ) from error
    reader = csv.DictReader(StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != SCHOLAR_QUEUE_FIELDS:
        raise ScholarReviewImportError(
            "The Google Scholar review queue has an unexpected schema."
        )
    work_by_id = {work.final_work_id: work for work in manifest.works}
    reviews: list[ScholarReview] = []
    seen: set[str] = set()
    for row_number, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise ScholarReviewImportError(f"Review row {row_number} is malformed.")
        work_id = _safe_text(row["final_work_id"], "final_work_id", 80)
        if work_id in seen or work_id not in work_by_id:
            raise ScholarReviewImportError(
                "The queue must contain exactly one review for every manifest work."
            )
        seen.add(work_id)
        work = work_by_id[work_id]
        expected_doi = work.canonical_metadata.doi or ""
        row_doi = normalize_doi(row["doi"]) if row["doi"] else ""
        expected_year = "" if work.canonical_metadata.year is None else str(work.canonical_metadata.year)
        if (
            row["applicant"] != work.workbook_applicant
            or row_doi != expected_doi
            or row["title"] != (work.canonical_metadata.title or "")
            or row["year"] != expected_year
        ):
            raise ScholarReviewImportError(
                "A queue identity or bibliographic field disagrees with the reviewed manifest."
            )
        _scholar_url(row["google_scholar_search_url"], "google_scholar_search_url")
        status = row["citation_status"]
        if status not in {"OBSERVED", "NOT_FOUND"}:
            raise ScholarReviewImportError(
                "citation_status must be OBSERVED or NOT_FOUND."
            )
        count_text = row["citation_count"]
        try:
            count = None if count_text == "" else int(count_text)
        except ValueError as error:
            raise ScholarReviewImportError(
                "citation_count must be a nonnegative integer."
            ) from error
        if count is not None and count < 0:
            raise ScholarReviewImportError(
                "citation_count must be a nonnegative integer."
            )
        if status == "OBSERVED" and count is None:
            raise ScholarReviewImportError("OBSERVED reviews require citation_count.")
        if status == "NOT_FOUND" and count is not None:
            raise ScholarReviewImportError("NOT_FOUND reviews must not have citation_count.")
        result_url = _scholar_url(row["result_url"], "result_url")
        observed_at = _utc_timestamp(row["observed_at_utc"], "observed_at_utc")
        reviewer = _safe_text(row["reviewer"], "reviewer", 255)
        reviews.append(
            ScholarReview(
                work.workbook_applicant,
                work_id,
                status,
                count,
                result_url,
                observed_at,
                reviewer,
                dict(row),
            )
        )
    if seen != set(work_by_id):
        raise ScholarReviewImportError(
            "The queue must contain exactly one review for every manifest work."
        )
    return tuple(reviews)


def scholar_review_fingerprint(raw_bytes: bytes) -> str:
    return hashlib.sha256(
        raw_bytes + b"\0" + SCHOLAR_REVIEW_IMPORTER_VERSION.encode("ascii")
    ).hexdigest()


def run_scholar_review_import(
    manifest_bytes: bytes,
    queue_bytes: bytes,
    *,
    mode: ImportMode,
    repository_factory: Callable[[], ScholarReviewRepository],
    expected: ManifestCounts = PRODUCTION_COUNTS,
) -> ScholarReviewImportResult:
    manifest = load_publication_manifest(manifest_bytes, expected=expected)
    reviews = load_scholar_reviews(queue_bytes, manifest)
    fingerprint = scholar_review_fingerprint(queue_bytes)
    observed = sum(review.citation_status == "OBSERVED" for review in reviews)
    not_found = len(reviews) - observed
    if mode == ImportMode.PLAN_ONLY:
        return ScholarReviewImportResult(
            mode, fingerprint, len(reviews), observed, not_found, None, False
        )
    if mode != ImportMode.APPLY:
        raise ScholarReviewImportError("The Scholar review import mode is invalid.")
    return repository_factory().apply(reviews, fingerprint)


class SqlScholarReviewRepository:
    """Privileged writer for immutable reviewed Google Scholar observations."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def apply(
        self, reviews: Sequence[ScholarReview], fingerprint: str
    ) -> ScholarReviewImportResult:
        call_rows = self._connection.execute(
            "SELECT CONVERT(varchar(36), FellowshipCallId) "
            "FROM dbo.FellowshipCall WHERE CallCode = N'EHF-2026'"
        ).fetchall()
        if len(call_rows) != 1:
            raise ScholarReviewImportError("The EHF-2026 call cannot be resolved uniquely.")
        call_id = str(call_rows[0][0])
        completed = self._connection.execute(
            "SELECT TOP (1) CONVERT(varchar(36), ImportRunId) FROM dbo.ImportRun "
            "WHERE FellowshipCallId = ? "
            "AND ImportFingerprintSha256 = CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)) "
            "AND ImporterVersion = ? AND RunStatus = 'COMPLETED' "
            "ORDER BY CompletedAtUtc DESC",
            call_id,
            fingerprint,
            SCHOLAR_REVIEW_IMPORTER_VERSION,
        ).fetchone()
        observed = sum(review.citation_status == "OBSERVED" for review in reviews)
        not_found = len(reviews) - observed
        if completed is not None:
            return ScholarReviewImportResult(
                ImportMode.APPLY,
                fingerprint,
                len(reviews),
                observed,
                not_found,
                str(completed[0]),
                True,
            )

        publication_ids: dict[str, tuple[str, str]] = {}
        for review in reviews:
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
                raise ScholarReviewImportError(
                    "A reviewed work does not resolve to exactly one publication."
                )
            publication_ids[review.final_work_id] = (str(rows[0][0]), str(rows[0][1]))
        if len(publication_ids) != len(reviews):
            raise ScholarReviewImportError("Reviewed works do not map distinctly.")

        run_row = self._connection.execute(
            "INSERT dbo.ImportRun "
            "(FellowshipCallId, ImportFingerprintSha256, ImporterVersion, RunStatus, StartedByIdentity) "
            "OUTPUT CONVERT(varchar(36), inserted.ImportRunId) "
            "VALUES (?, CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), ?, 'RUNNING', "
            "'ISAB01_GOOGLE_SCHOLAR_REVIEW')",
            call_id,
            fingerprint,
            SCHOLAR_REVIEW_IMPORTER_VERSION,
        ).fetchone()
        if run_row is None:
            raise ScholarReviewImportError("The Scholar review run could not be created.")
        run_id = str(run_row[0])
        self._connection.commit()
        try:
            for row_number, review in enumerate(reviews, start=1):
                publication_id, application_id = publication_ids[review.final_work_id]
                evidence = json.dumps(
                    {
                        "result_url": review.result_url,
                        "reviewer": review.reviewer,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                payload = json.dumps(
                    review.raw,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                row_hash = hashlib.sha256(
                    f"{review.final_work_id}\0{payload_hash}".encode("utf-8")
                ).hexdigest()
                row = self._connection.execute(
                    "INSERT dbo.ImportRow "
                    "(ImportRunId, SourceRowNumber, ApplicationId, SourceRowSha256, MatchStatus) "
                    "OUTPUT CONVERT(varchar(36), inserted.ImportRowId) "
                    "VALUES (?, ?, ?, CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)), 'MATCHED')",
                    run_id,
                    row_number,
                    application_id,
                    row_hash,
                ).fetchone()
                if row is None:
                    raise ScholarReviewImportError("A Scholar review row could not be recorded.")
                self._connection.execute(
                    "INSERT dbo.PublicationCitationObservation "
                    "(ApplicationPublicationId, ImportRunId, SourceCode, CitationCount, "
                    "CitationStatus, EvidenceJson, ObservedAtUtc, PayloadSha256) "
                    "VALUES (?, ?, 'GOOGLE_SCHOLAR', ?, ?, ?, "
                    "CONVERT(datetime2(7), ?, 127), "
                    "CONVERT(binary(32), CONVERT(varbinary(32), ?, 2)) )",
                    publication_id,
                    run_id,
                    review.citation_count,
                    review.citation_status,
                    evidence,
                    review.observed_at_utc,
                    payload_hash,
                )
            self._connection.execute(
                "UPDATE dbo.ImportRun SET RunStatus = 'COMPLETED', "
                "CompletedAtUtc = SYSUTCDATETIME() WHERE ImportRunId = ? "
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
            if isinstance(error, ScholarReviewImportError):
                raise
            raise ScholarReviewImportError("The Scholar review import failed.") from error
        return ScholarReviewImportResult(
            ImportMode.APPLY,
            fingerprint,
            len(reviews),
            observed,
            not_found,
            run_id,
            False,
        )
