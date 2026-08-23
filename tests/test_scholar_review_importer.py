"""Reviewed Google Scholar queue import contracts."""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

import pytest

from app.importer.publications import ManifestCounts, load_publication_manifest
from app.importer.run import ImportMode
from app.importer.scholar_reviews import (
    ScholarReviewImportError,
    SqlScholarReviewRepository,
    load_scholar_reviews,
    run_scholar_review_import,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "import" / "publications-minimal.json"
FIXTURE_COUNTS = ManifestCounts(1, 1, 2, 3)
FIELDS = (
    "applicant",
    "final_work_id",
    "doi",
    "title",
    "year",
    "google_scholar_search_url",
    "citation_status",
    "citation_count",
    "result_url",
    "observed_at_utc",
    "reviewer",
)


def _manifest():
    return load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)


def _queue_bytes(**changes: str) -> bytes:
    row = {
        "applicant": "Alex Example",
        "final_work_id": "work-001",
        "doi": "10.1000/example",
        "title": "A fixture publication",
        "year": "2025",
        "google_scholar_search_url": "https://scholar.google.com/scholar?q=10.1000%2Fexample",
        "citation_status": "OBSERVED",
        "citation_count": "17",
        "result_url": "https://scholar.google.com/scholar?cluster=123",
        "observed_at_utc": "2026-08-23T15:00:00Z",
        "reviewer": "Adriano Aguzzi",
    }
    row.update(changes)
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerow(row)
    return output.getvalue().encode("utf-8-sig")


def test_reviewed_queue_accepts_observed_and_not_found_evidence() -> None:
    observed = load_scholar_reviews(_queue_bytes(), _manifest())
    assert observed[0].citation_count == 17
    assert observed[0].citation_status == "OBSERVED"
    assert observed[0].observed_at_utc == "2026-08-23T15:00:00.000000Z"

    not_found = load_scholar_reviews(
        _queue_bytes(citation_status="NOT_FOUND", citation_count=""), _manifest()
    )
    assert not_found[0].citation_count is None
    assert not_found[0].citation_status == "NOT_FOUND"


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"citation_status": "MANUAL_REQUIRED"}, "citation_status"),
        ({"citation_count": "-1"}, "citation_count"),
        ({"citation_count": ""}, "OBSERVED"),
        ({"citation_status": "NOT_FOUND", "citation_count": "2"}, "NOT_FOUND"),
        ({"result_url": "https://example.test/result"}, "Google Scholar"),
        ({"observed_at_utc": "2026-08-23 15:00"}, "observed_at_utc"),
        ({"reviewer": ""}, "reviewer"),
        ({"final_work_id": "wrong-work"}, "exactly one review"),
    ),
)
def test_reviewed_queue_fails_closed_on_incomplete_or_untrusted_rows(
    changes: dict[str, str], message: str
) -> None:
    with pytest.raises(ScholarReviewImportError, match=message):
        load_scholar_reviews(_queue_bytes(**changes), _manifest())


def test_review_plan_never_constructs_database_repository() -> None:
    calls = 0

    def forbidden_repository():
        nonlocal calls
        calls += 1
        raise AssertionError("plan-only connected to the database")

    result = run_scholar_review_import(
        FIXTURE.read_bytes(),
        _queue_bytes(),
        mode=ImportMode.PLAN_ONLY,
        expected=FIXTURE_COUNTS,
        repository_factory=forbidden_repository,
    )

    assert calls == 0
    assert result.review_count == 1
    assert result.observed_count == 1
    assert result.not_found_count == 0
    assert result.run_id is None


class _Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _Connection:
    def __init__(self, *, completed_run: str | None = None, publications=None):
        self.completed_run = completed_run
        self.publications = publications or {"work-001": [("publication-id", "application-id")]}
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.commit_count = 0
        self.rollback_count = 0

    def execute(self, statement, *parameters):
        normalized = " ".join(statement.split())
        self.executed.append((normalized, parameters))
        if "FROM dbo.FellowshipCall WHERE CallCode" in normalized:
            return _Cursor([("call-id",)])
        if "FROM dbo.ImportRun" in normalized and "RunStatus = 'COMPLETED'" in normalized:
            return _Cursor([] if self.completed_run is None else [(self.completed_run,)])
        if "JOIN dbo.Application AS application_row" in normalized and "ManifestWorkKey" in normalized:
            return _Cursor(self.publications.get(str(parameters[1]), []))
        if "INSERT dbo.ImportRun" in normalized and "OUTPUT" in normalized:
            return _Cursor([("review-run-id",)])
        if "INSERT dbo.ImportRow" in normalized and "OUTPUT" in normalized:
            return _Cursor([("review-row-id",)])
        return _Cursor()

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


def test_sql_review_repository_appends_observation_and_completes_audited_run() -> None:
    reviews = load_scholar_reviews(_queue_bytes(), _manifest())
    connection = _Connection()

    result = SqlScholarReviewRepository(connection).apply(reviews, "a" * 64)

    statements = "\n".join(statement for statement, _ in connection.executed)
    citation_call = next(
        parameters
        for statement, parameters in connection.executed
        if "INSERT dbo.PublicationCitationObservation" in statement
    )
    assert "ISAB01_GOOGLE_SCHOLAR_REVIEW" in statements
    assert "INSERT dbo.ImportRow" in statements
    assert citation_call[2:4] == (17, "OBSERVED")
    assert "SET RunStatus = 'COMPLETED'" in statements
    assert result.run_id == "review-run-id"
    assert result.reused_completed_run is False
    assert connection.rollback_count == 0


def test_sql_review_repository_resolves_every_work_before_writing_and_reuses_completed_run() -> None:
    reviews = load_scholar_reviews(_queue_bytes(), _manifest())
    missing = _Connection(publications={"work-001": []})
    with pytest.raises(ScholarReviewImportError, match="exactly one publication"):
        SqlScholarReviewRepository(missing).apply(reviews, "b" * 64)
    assert not any(statement.startswith("INSERT") for statement, _ in missing.executed)

    completed = _Connection(completed_run="completed-review-run")
    result = SqlScholarReviewRepository(completed).apply(reviews, "c" * 64)
    assert result.reused_completed_run is True
    assert result.run_id == "completed-review-run"
    assert not any(statement.startswith("INSERT") for statement, _ in completed.executed)
