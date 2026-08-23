"""Semantic Scholar reviewed snapshot import contracts."""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

import pytest

from app.importer.open_citations import (
    OpenCitationImportError,
    SqlOpenCitationRepository,
    load_open_citation_reviews,
    run_open_citation_import,
)
from app.importer.publications import ManifestCounts, load_publication_manifest
from app.importer.run import ImportMode


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "import" / "publications-minimal.json"
FIXTURE_COUNTS = ManifestCounts(1, 1, 2, 3)
FIELDS = (
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


def _manifest():
    return load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)


def _snapshot_bytes(**changes: str) -> bytes:
    rows = [
        {
            "applicant": "Alex Example",
            "final_work_id": "work-001",
            "doi": "10.1000/example",
            "title": "A fixture publication",
            "year": "2025",
            "source_code": "SEMANTIC_SCHOLAR",
            "citation_status": "OBSERVED",
            "citation_count": "17",
            "source_identifier": "0123456789abcdef0123456789abcdef01234567",
            "result_url": "https://www.semanticscholar.org/paper/0123456789abcdef0123456789abcdef01234567",
            "matched_doi": "10.1000/example",
            "matched_title": "A fixture publication",
            "matched_authors": "Alex Example; B. Researcher",
            "observed_at_utc": "2026-08-23T15:00:01Z",
            "reviewer": "EHF open citation collector",
            "match_method": "DOI_EXACT",
        },
    ]
    if "source_code" in changes:
        rows[0].update(changes)
    else:
        for row in rows:
            row.update(changes)
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def test_snapshot_requires_one_semantic_scholar_observation_per_work() -> None:
    reviews = load_open_citation_reviews(_snapshot_bytes(), _manifest())

    assert [(row.source_code, row.citation_count) for row in reviews] == [
        ("SEMANTIC_SCHOLAR", 17),
    ]
    assert all(row.citation_status == "OBSERVED" for row in reviews)


def test_snapshot_plan_validates_every_work_without_constructing_a_repository() -> None:
    result = run_open_citation_import(
        FIXTURE.read_bytes(),
        _snapshot_bytes(),
        mode=ImportMode.PLAN_ONLY,
        expected=FIXTURE_COUNTS,
        repository_factory=lambda: (_ for _ in ()).throw(
            AssertionError("plan-only connected to the database")
        ),
    )

    assert result.review_count == 1
    assert result.observed_count == 1
    assert result.run_id is None


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"source_code": "GOOGLE_SCHOLAR"}, "source_code"),
        ({"citation_count": "-1"}, "citation_count"),
        ({"citation_count": ""}, "OBSERVED"),
        ({"citation_status": "MANUAL_REQUIRED"}, "citation_status"),
        ({"result_url": "https://example.test/result"}, "result_url"),
        ({"observed_at_utc": "2026-08-23 15:00"}, "observed_at_utc"),
        ({"match_method": "GUESS"}, "match_method"),
        ({"source_identifier": "not-a-source-id"}, "source_identifier"),
        ({"matched_doi": "10.1000/unrelated"}, "DOI_EXACT"),
        (
            {
                "match_method": "TITLE_EXACT",
                "matched_doi": "",
                "matched_authors": "Someone Else",
            },
            "applicant author",
        ),
        (
            {
                "citation_status": "NOT_FOUND",
                "citation_count": "",
                "match_method": "NO_CONFIDENT_MATCH",
            },
            "NOT_FOUND",
        ),
        ({"final_work_id": "wrong-work"}, "every manifest work"),
    ),
)
def test_snapshot_fails_closed_on_untrusted_or_incomplete_rows(
    changes: dict[str, str], message: str
) -> None:
    with pytest.raises(OpenCitationImportError, match=message):
        load_open_citation_reviews(_snapshot_bytes(**changes), _manifest())


class _Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _Connection:
    def __init__(self):
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, *parameters):
        normalized = " ".join(statement.split())
        self.executed.append((normalized, parameters))
        if "FROM dbo.FellowshipCall" in normalized:
            return _Cursor([("call-id",)])
        if "FROM dbo.ImportRun" in normalized and "COMPLETED" in normalized:
            return _Cursor([])
        if "ManifestWorkKey" in normalized and "JOIN dbo.Application" in normalized:
            return _Cursor([("publication-id", "application-id")])
        if "INSERT dbo.ImportRun" in normalized and "OUTPUT" in normalized:
            return _Cursor([("run-id",)])
        if "INSERT dbo.ImportRow" in normalized and "OUTPUT" in normalized:
            return _Cursor([("row-id",)])
        return _Cursor()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_sql_repository_appends_semantic_scholar_observations_without_overwrite() -> None:
    connection = _Connection()
    reviews = load_open_citation_reviews(_snapshot_bytes(), _manifest())

    result = SqlOpenCitationRepository(connection).apply(reviews, "a" * 64)

    inserts = [
        parameters
        for statement, parameters in connection.executed
        if "INSERT dbo.PublicationCitationObservation" in statement
    ]
    statements = "\n".join(statement for statement, _ in connection.executed)
    assert len(inserts) == 1
    assert {parameters[2] for parameters in inserts} == {"SEMANTIC_SCHOLAR"}
    assert "UPDATE dbo.PublicationCitationObservation" not in statements
    assert "ISAB01_OPEN_CITATION_IMPORT" in statements
    assert result.review_count == 1
    assert result.run_id == "run-id"
