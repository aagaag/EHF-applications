"""Semantic Scholar reviewed snapshot import contracts."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from app.importer.open_citations import (
    OPEN_CITATION_FIELDS,
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
FIELDS = OPEN_CITATION_FIELDS


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
            "annual_citation_counts": "{}",
            "journal_openalex_id": "",
            "journal_openalex_name": "",
            "journal_source_type": "",
            "journal_two_year_mean_citedness": "",
            "journal_source_updated_date": "",
            "journal_metric_observed_at_utc": "",
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


def _openalex_journal_snapshot_bytes(**changes: str) -> bytes:
    values = {
        "source_code": "OPENALEX",
        "source_identifier": "https://openalex.org/W123456789",
        "result_url": "https://openalex.org/W123456789",
        "matched_authors": "",
        "journal_openalex_id": "https://openalex.org/S123",
        "journal_openalex_name": "Example Journal",
        "journal_source_type": "journal",
        "journal_two_year_mean_citedness": "4.25",
        "journal_source_updated_date": "2026-08-20",
        "journal_metric_observed_at_utc": "2026-08-23T15:00:00Z",
    }
    values.update(changes)
    return _snapshot_bytes(**values)


def test_snapshot_requires_one_semantic_scholar_observation_per_work() -> None:
    reviews = load_open_citation_reviews(_snapshot_bytes(), _manifest())

    assert [(row.source_code, row.citation_count) for row in reviews] == [
        ("SEMANTIC_SCHOLAR", 17),
    ]
    assert all(row.citation_status == "OBSERVED" for row in reviews)


def test_snapshot_rejects_mixed_openalex_and_semantic_scholar_rows() -> None:
    source = StringIO(_snapshot_bytes().decode("utf-8-sig"), newline="")
    reader = csv.DictReader(source)
    rows = list(reader)
    mixed_row = dict(rows[0])
    mixed_row.update(
        source_code="OPENALEX",
        citation_status="NOT_FOUND",
        citation_count="",
        source_identifier="",
        result_url="https://api.openalex.org/works",
        matched_doi="",
        matched_title="",
        matched_authors="",
        match_method="NO_CONFIDENT_MATCH",
    )
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows([*rows, mixed_row])

    with pytest.raises(OpenCitationImportError, match="exactly one source"):
        load_open_citation_reviews(output.getvalue().encode("utf-8-sig"), _manifest())


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
    assert result.source_code == "SEMANTIC_SCHOLAR"
    assert result.eligible_count == 1
    assert result.run_id is None


def test_openalex_doi_exact_observation_does_not_require_authors() -> None:
    reviews = load_open_citation_reviews(
        _snapshot_bytes(
            source_code="OPENALEX",
            source_identifier="https://openalex.org/W123456789",
            result_url="https://openalex.org/W123456789",
            matched_authors="",
        ),
        _manifest(),
    )

    assert reviews[0].match_method == "DOI_EXACT"
    assert reviews[0].matched_authors == ""


def test_openalex_journal_evidence_is_validated_and_persisted_as_a_numeric_value() -> None:
    review = load_open_citation_reviews(
        _openalex_journal_snapshot_bytes(), _manifest()
    )[0]

    assert review.journal_openalex_id == "https://openalex.org/S123"
    assert review.journal_two_year_mean_citedness == 4.25

    connection = _Connection()
    SqlOpenCitationRepository(connection).apply((review,), "e" * 64)
    evidence = next(
        json.loads(parameters[5])
        for statement, parameters in connection.executed
        if "INSERT dbo.PublicationCitationObservation" in statement
    )

    assert evidence == {
        "counts_by_year": {},
        "journal_openalex_id": "https://openalex.org/S123",
        "journal_openalex_name": "Example Journal",
        "journal_source_type": "journal",
        "journal_two_year_mean_citedness": 4.25,
        "journal_source_updated_date": "2026-08-20",
        "journal_metric_observed_at_utc": "2026-08-23T15:00:00.000000Z",
        "match_method": "DOI_EXACT",
        "matched_authors": None,
        "matched_doi": "10.1000/example",
        "matched_title": "A fixture publication",
        "result_url": "https://openalex.org/W123456789",
        "reviewer": "EHF open citation collector",
        "source_identifier": "https://openalex.org/W123456789",
    }


def test_openalex_journal_source_timestamp_is_normalized_to_a_date() -> None:
    review = load_open_citation_reviews(
        _openalex_journal_snapshot_bytes(
            journal_source_updated_date="2026-08-20T10:03:11"
        ),
        _manifest(),
    )[0]

    assert review.journal_source_updated_date == "2026-08-20"


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"journal_openalex_id": "https://openalex.org/W999"}, "journal"),
        ({"journal_openalex_id": "http://openalex.org/S123"}, "journal"),
        ({"journal_source_type": "repository"}, "journal"),
        ({"journal_two_year_mean_citedness": "-1"}, "journal"),
        ({"journal_two_year_mean_citedness": "NaN"}, "journal"),
        ({"journal_two_year_mean_citedness": "Infinity"}, "journal"),
        ({"journal_source_updated_date": "not-a-date"}, "journal"),
        ({"journal_metric_observed_at_utc": "2200-01-01T00:00:00Z"}, "journal"),
    ),
)
def test_openalex_journal_evidence_fails_closed_on_invalid_fields(
    changes: dict[str, str], message: str
) -> None:
    with pytest.raises(OpenCitationImportError, match=message):
        load_open_citation_reviews(_openalex_journal_snapshot_bytes(**changes), _manifest())


def test_not_found_openalex_rows_cannot_carry_journal_evidence() -> None:
    with pytest.raises(OpenCitationImportError, match="journal"):
        load_open_citation_reviews(
            _openalex_journal_snapshot_bytes(
                citation_status="NOT_FOUND",
                citation_count="",
                source_identifier="",
                result_url="https://api.openalex.org/works",
                matched_doi="",
                matched_title="",
                matched_authors="",
                match_method="NO_CONFIDENT_MATCH",
            ),
            _manifest(),
        )


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
    def __init__(self, *, eligible_work_ids: set[str] | None = None):
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0
        self.eligible_work_ids = eligible_work_ids or {"work-001"}

    def execute(self, statement, *parameters):
        normalized = " ".join(statement.split())
        self.executed.append((normalized, parameters))
        if "FROM dbo.FellowshipCall" in normalized:
            return _Cursor([("call-id",)])
        if "FROM dbo.ImportRun" in normalized and "COMPLETED" in normalized:
            return _Cursor([])
        if "ManifestWorkKey" in normalized and "JOIN dbo.Application" in normalized:
            work_id = str(parameters[1])
            return _Cursor(
                [
                    (
                        f"publication-{work_id}",
                        "application-id",
                        int(work_id in self.eligible_work_ids),
                    )
                ]
            )
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


def test_complete_semantic_snapshot_activates_its_import_run() -> None:
    connection = _Connection()
    reviews = load_open_citation_reviews(_snapshot_bytes(), _manifest())

    result = SqlOpenCitationRepository(connection).apply(reviews, "b" * 64)

    statements = "\n".join(statement for statement, _ in connection.executed)
    assert "ActivateCitationMetricCutoffRun" in statements
    assert result.source_code == "SEMANTIC_SCHOLAR"
    assert result.eligible_count == result.observed_count == 1


def test_incomplete_semantic_snapshot_is_audited_without_activation() -> None:
    connection = _Connection()
    reviews = load_open_citation_reviews(
        _snapshot_bytes(
            citation_status="NOT_FOUND",
            citation_count="",
            source_identifier="",
            result_url="https://api.semanticscholar.org/graph/v1/paper/search",
            matched_doi="",
            matched_title="",
            matched_authors="",
            match_method="NO_CONFIDENT_MATCH",
        ),
        _manifest(),
    )

    result = SqlOpenCitationRepository(connection).apply(reviews, "c" * 64)

    statements = "\n".join(statement for statement, _ in connection.executed)
    assert result.not_found_count == 1
    assert "ActivateCitationMetricCutoffRun" not in statements


def test_noneligible_not_found_rows_do_not_block_complete_cutoff_activation() -> None:
    connection = _Connection(eligible_work_ids={"work-001"})
    observed = load_open_citation_reviews(_snapshot_bytes(), _manifest())[0]
    missing = replace(
        observed,
        final_work_id="work-002",
        citation_status="NOT_FOUND",
        citation_count=None,
        source_identifier="",
        matched_doi="",
        matched_title="",
        matched_authors="",
        match_method="NO_CONFIDENT_MATCH",
    )

    result = SqlOpenCitationRepository(connection).apply(
        (observed, missing), "d" * 64
    )

    statements = "\n".join(statement for statement, _ in connection.executed)
    assert result.eligible_count == 1
    assert result.not_found_count == 1
    assert "ActivateCitationMetricCutoffRun" in statements
