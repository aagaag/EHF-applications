"""Strict, additive publication-manifest import contracts."""

from __future__ import annotations

import csv
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app.importer.publications import (
    ManifestCounts,
    PublicationImportError,
    PublicationApplicant,
    load_publication_manifest,
    normalize_doi,
    publication_identity,
    reconcile_canonical_values,
    run_publication_import,
    write_google_scholar_queue,
)
from app.importer.run import ImportMode


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "import" / "publications-minimal.json"
FIXTURE_COUNTS = ManifestCounts(
    applicants=1,
    works=1,
    source_occurrences=2,
    citation_statuses=3,
)


def _fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


def _rewritten(**changes: object) -> bytes:
    document = json.loads(_fixture_bytes())
    document.update(changes)
    document["hashes"]["manifest_sha256_excluding_hash"] = None
    canonical = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    import hashlib

    document["hashes"]["manifest_sha256_excluding_hash"] = hashlib.sha256(
        canonical
    ).hexdigest()
    return json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")


def test_fixture_is_strictly_valid_and_preserves_all_relationships() -> None:
    manifest = load_publication_manifest(_fixture_bytes(), expected=FIXTURE_COUNTS)

    assert len(manifest.applicants) == 1
    assert len(manifest.works) == 1
    assert len(manifest.source_occurrences) == 2
    assert len(manifest.citation_statuses) == 3
    assert manifest.works[0].source_occurrence_ids == ("occ-001", "occ-002")
    assert manifest.works[0].resolution.evidence["doi"] == "10.1000/example"
    assert manifest.citation_statuses[0].count is None


def test_generated_timestamp_is_strictly_validated_and_normalized_to_utc() -> None:
    manifest = load_publication_manifest(
        _rewritten(generated_at_utc="2026-08-23T12:34:56+02:00"),
        expected=FIXTURE_COUNTS,
    )
    assert manifest.generated_at_utc == "2026-08-23T10:34:56.000000Z"
    assert datetime.fromisoformat(
        manifest.generated_at_utc.replace("Z", "+00:00")
    ).tzinfo == timezone.utc

    for invalid in ("not-a-date", "2026-08-23T12:34:56", "1500-01-01T00:00:00Z"):
        with pytest.raises(PublicationImportError, match="generated_at_utc"):
            load_publication_manifest(
                _rewritten(generated_at_utc=invalid), expected=FIXTURE_COUNTS
            )


def test_binary_workbook_input_may_have_no_schema_version() -> None:
    document = json.loads(_fixture_bytes())
    document["inputs"][0]["schema_version"] = None

    manifest = load_publication_manifest(
        _rewritten(inputs=document["inputs"]), expected=FIXTURE_COUNTS
    )

    assert manifest.schema_version == "publication-import-manifest-v1"


def test_missing_workbook_total_has_null_raw_total_and_difference() -> None:
    document = json.loads(_fixture_bytes())
    applicant = document["applicants"][0]
    applicant["workbook_reported_total_raw"] = None
    applicant["workbook_reported_total"] = None
    applicant["difference_unique_minus_reported"] = None

    manifest = load_publication_manifest(
        _rewritten(applicants=document["applicants"]), expected=FIXTURE_COUNTS
    )

    assert manifest.applicants[0].raw["workbook_reported_total"] is None


def test_unknown_contract_fields_and_bad_self_hash_fail_closed() -> None:
    with pytest.raises(PublicationImportError, match="unknown field"):
        load_publication_manifest(
            _rewritten(unexpected="must fail"), expected=FIXTURE_COUNTS
        )

    document = json.loads(_fixture_bytes())
    document["works"][0]["canonical_metadata"]["title"] = "tampered"
    with pytest.raises(PublicationImportError, match="self-hash"):
        load_publication_manifest(
            json.dumps(document).encode("utf-8"), expected=FIXTURE_COUNTS
        )


def test_counts_relationships_doi_uniqueness_and_null_initial_counts_are_enforced() -> None:
    with pytest.raises(PublicationImportError, match="expected 2 works"):
        load_publication_manifest(
            _fixture_bytes(),
            expected=ManifestCounts(1, 2, 2, 3),
        )

    document = json.loads(_fixture_bytes())
    document["citation_source_statuses"][0]["status"] = "NOT_FOUND"
    with pytest.raises(PublicationImportError, match="Google Scholar.*MANUAL_REQUIRED"):
        load_publication_manifest(
            _rewritten(citation_source_statuses=document["citation_source_statuses"]),
            expected=FIXTURE_COUNTS,
        )

    document = json.loads(_fixture_bytes())
    document["citation_source_statuses"][0]["status"] = "OBSERVED"
    with pytest.raises(PublicationImportError, match="initial citation status"):
        load_publication_manifest(
            _rewritten(citation_source_statuses=document["citation_source_statuses"]),
            expected=FIXTURE_COUNTS,
        )


def test_sql_bounds_declared_counts_and_source_work_relationships_fail_in_plan() -> None:
    document = json.loads(_fixture_bytes())
    document["works"][0]["final_work_id"] = "w" * 81
    document["source_occurrences"][0]["final_work_id"] = "w" * 81
    document["source_occurrences"][1]["final_work_id"] = "w" * 81
    document["citation_source_statuses"][0]["final_work_id"] = "w" * 81
    document["citation_source_statuses"][1]["final_work_id"] = "w" * 81
    document["citation_source_statuses"][2]["final_work_id"] = "w" * 81
    with pytest.raises(PublicationImportError, match="final_work_id.*80"):
        load_publication_manifest(
            _rewritten(
                works=document["works"],
                source_occurrences=document["source_occurrences"],
                citation_source_statuses=document["citation_source_statuses"],
            ),
            expected=FIXTURE_COUNTS,
        )

    document = json.loads(_fixture_bytes())
    document["applicants"][0]["final_unique_work_count"] = 2
    with pytest.raises(PublicationImportError, match="declared work count"):
        load_publication_manifest(
            _rewritten(applicants=document["applicants"]), expected=FIXTURE_COUNTS
        )

    document = json.loads(_fixture_bytes())
    document["works"][0]["source_work_ids"] = ["wrong-source-work"]
    with pytest.raises(PublicationImportError, match="source-work relationship"):
        load_publication_manifest(
            _rewritten(works=document["works"]), expected=FIXTURE_COUNTS
        )

    document = json.loads(_fixture_bytes())
    document["citation_source_statuses"][0]["count"] = 4
    document["citation_source_statuses"][0]["status"] = "OBSERVED"
    with pytest.raises(PublicationImportError, match="initial citation counts"):
        load_publication_manifest(
            _rewritten(
                citation_source_statuses=document["citation_source_statuses"]
            ),
            expected=FIXTURE_COUNTS,
        )


def test_doi_normalization_and_per_application_identity_are_deterministic() -> None:
    manifest = load_publication_manifest(_fixture_bytes(), expected=FIXTURE_COUNTS)
    work = manifest.works[0]

    assert normalize_doi(" HTTPS://DOI.ORG/10.1000/Example ") == "10.1000/example"
    assert normalize_doi("doi:10.1000/Example") == "10.1000/example"
    assert publication_identity(work, manifest.source_occurrences) == publication_identity(
        work, tuple(reversed(manifest.source_occurrences))
    )
    assert len(publication_identity(work, manifest.source_occurrences)) == 64


def test_plan_only_never_constructs_a_database_repository() -> None:
    calls = 0

    def forbidden_repository():
        nonlocal calls
        calls += 1
        raise AssertionError("plan-only connected to the database")

    result = run_publication_import(
        _fixture_bytes(),
        mode=ImportMode.PLAN_ONLY,
        expected=FIXTURE_COUNTS,
        repository_factory=forbidden_repository,
    )

    assert calls == 0
    assert result.application_count == 1
    assert result.publication_count == 1
    assert result.source_occurrence_count == 2
    assert result.citation_observation_count == 3
    assert result.run_id is None


def test_manual_google_scholar_queue_is_one_row_per_work_and_has_blank_review_fields(
    tmp_path: Path,
) -> None:
    manifest = load_publication_manifest(_fixture_bytes(), expected=FIXTURE_COUNTS)
    output = tmp_path / "scholar.csv"

    write_google_scholar_queue(manifest, output)

    with output.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["applicant"] == "Alex Example"
    assert rows[0]["final_work_id"] == "work-001"
    assert rows[0]["doi"] == "10.1000/example"
    assert rows[0]["title"] == "A fixture publication"
    assert rows[0]["google_scholar_search_url"].startswith(
        "https://scholar.google.com/scholar?q="
    )
    for field in (
        "citation_status",
        "citation_count",
        "result_url",
        "observed_at_utc",
        "reviewer",
    ):
        assert rows[0][field] == ""


def test_scholar_queue_neutralizes_formulas_and_preserves_completed_review_fields(
    tmp_path: Path,
) -> None:
    document = json.loads(_fixture_bytes())
    document["applicants"][0]["workbook_applicant"] = "=HOSTILE()"
    document["works"][0]["workbook_applicant"] = "=HOSTILE()"
    document["works"][0]["canonical_metadata"]["title"] = "+SUM(1,1)"
    manifest = load_publication_manifest(
        _rewritten(applicants=document["applicants"], works=document["works"]),
        expected=FIXTURE_COUNTS,
    )
    output = tmp_path / "scholar.csv"
    write_google_scholar_queue(manifest, output)
    with output.open(newline="", encoding="utf-8-sig") as handle:
        row = next(csv.DictReader(handle))
    assert row["applicant"].startswith("'")
    assert row["title"].startswith("'")

    row["citation_count"] = "17"
    row["citation_status"] = "OBSERVED"
    row["result_url"] = "https://scholar.google.com/example"
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=row.keys())
        writer.writeheader()
        writer.writerow(row)
    write_google_scholar_queue(manifest, output)
    with output.open(newline="", encoding="utf-8-sig") as handle:
        preserved = next(csv.DictReader(handle))
    assert preserved["citation_count"] == "17"
    assert preserved["citation_status"] == "OBSERVED"
    assert preserved["result_url"] == "https://scholar.google.com/example"
    assert list(tmp_path.glob("*.tmp")) == []


def test_legacy_scholar_queue_is_upgraded_without_losing_review_data(
    tmp_path: Path,
) -> None:
    manifest = load_publication_manifest(_fixture_bytes(), expected=FIXTURE_COUNTS)
    output = tmp_path / "scholar.csv"
    write_google_scholar_queue(manifest, output)
    with output.open(newline="", encoding="utf-8-sig") as handle:
        row = next(csv.DictReader(handle))
    row.pop("citation_status")
    row["citation_count"] = "9"
    row["result_url"] = "https://scholar.google.com/scholar?cluster=9"
    row["observed_at_utc"] = "2026-08-23T15:00:00Z"
    row["reviewer"] = "Adriano Aguzzi"
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=row.keys())
        writer.writeheader()
        writer.writerow(row)

    write_google_scholar_queue(manifest, output)

    with output.open(newline="", encoding="utf-8-sig") as handle:
        upgraded = next(csv.DictReader(handle))
    assert upgraded["citation_status"] == "OBSERVED"
    assert upgraded["citation_count"] == "9"
    assert upgraded["reviewer"] == "Adriano Aguzzi"


def test_reconciliation_fills_only_blanks_and_reports_every_discrepancy() -> None:
    existing = {
        "doi": "10.1000/example",
        "http_link": None,
        "authors_text": "Existing Author",
        "title": "Existing title",
        "journal_text": None,
        "volume_text": "12",
        "pages_text": None,
        "publication_year": 2024,
    }
    incoming = {
        "doi": "10.1000/example",
        "http_link": "https://doi.org/10.1000/example",
        "authors_text": "Different Author",
        "title": "Different title",
        "journal_text": "Fixture Journal",
        "volume_text": "12",
        "pages_text": "10-20",
        "publication_year": 2025,
    }

    fills, conflicts = reconcile_canonical_values(existing, incoming)

    assert fills == {
        "http_link": "https://doi.org/10.1000/example",
        "journal_text": "Fixture Journal",
        "pages_text": "10-20",
    }
    assert set(conflicts) == {"authors_text", "title", "publication_year"}
    assert existing["title"] == "Existing title"


class _Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _PublicationConnection:
    def __init__(
        self,
        *,
        existing_publication=None,
        existing_manifest_publication=None,
        completed_run=None,
        applications=None,
    ):
        self.existing_publication = existing_publication
        self.existing_manifest_publication = existing_manifest_publication
        self.completed_run = completed_run
        self.applications = applications or {"Alex Example": [("application-id",)]}
        self.executed = []
        self.commit_count = 0
        self.rollback_count = 0

    def execute(self, statement, *parameters):
        normalized = " ".join(statement.split())
        self.executed.append((normalized, parameters))
        if "FROM dbo.FellowshipCall WHERE CallCode" in normalized:
            return _Cursor([("call-id",)])
        if "FROM dbo.ImportRun" in normalized and "RunStatus = 'COMPLETED'" in normalized:
            return _Cursor([] if self.completed_run is None else [(self.completed_run,)])
        if "INSERT dbo.ImportRun" in normalized and "OUTPUT" in normalized:
            return _Cursor([("run-id",)])
        if "CONCAT(applicant_row.LegalGivenNames" in normalized:
            return _Cursor(self.applications.get(parameters[1], []))
        if "INSERT dbo.ImportRow" in normalized and "OUTPUT" in normalized:
            return _Cursor([("row-id",)])
        if (
            "FROM dbo.ApplicationPublication" in normalized
            and "ManifestWorkKey = ?" in normalized
        ):
            return _Cursor(
                []
                if self.existing_manifest_publication is None
                else [self.existing_manifest_publication]
            )
        if "FROM dbo.ApplicationPublication" in normalized and "SELECT TOP (1)" in normalized:
            return _Cursor([] if self.existing_publication is None else [self.existing_publication])
        if "INSERT dbo.ApplicationPublication" in normalized and "OUTPUT" in normalized:
            return _Cursor([("publication-id",)])
        return _Cursor()

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


def test_sql_repository_inserts_canonical_and_all_evidence_then_completes() -> None:
    from app.importer.publications import SqlPublicationRepository

    manifest = load_publication_manifest(_fixture_bytes(), expected=FIXTURE_COUNTS)
    connection = _PublicationConnection()

    result = SqlPublicationRepository(connection).apply(manifest, "d" * 64)

    statements = "\n".join(statement for statement, _ in connection.executed)
    assert "INSERT dbo.ApplicationPublication " in statements
    assert "INSERT dbo.ApplicationPublicationSourceOccurrence" in statements
    assert "INSERT dbo.PublicationMetadataObservation" in statements
    assert statements.count("INSERT dbo.PublicationCitationObservation") == 3
    assert "SET RunStatus = 'COMPLETED'" in statements
    assert result.run_id == "run-id"
    assert result.conflict_count == 0
    assert connection.rollback_count == 0


def test_sql_repository_preserves_existing_values_and_records_hashed_conflicts() -> None:
    from app.importer.publications import SqlPublicationRepository

    manifest = load_publication_manifest(_fixture_bytes(), expected=FIXTURE_COUNTS)
    existing = (
        "publication-id",
        "10.1000/example",
        None,
        "Existing Author",
        "Existing title",
        None,
        "12",
        None,
        2024,
    )
    connection = _PublicationConnection(existing_publication=existing)

    result = SqlPublicationRepository(connection).apply(manifest, "e" * 64)

    exception_calls = [
        parameters
        for statement, parameters in connection.executed
        if "INSERT dbo.ImportException" in statement
    ]
    assert result.conflict_count == 3
    assert {parameters[2] for parameters in exception_calls} == {
        "PUBLICATION_CONFLICT_AUTHORS_TEXT",
        "PUBLICATION_CONFLICT_TITLE",
        "PUBLICATION_CONFLICT_PUBLICATION_YEAR",
    }
    assert all(len(parameters[3]) == 64 for parameters in exception_calls)


def test_sql_repository_fills_a_previously_unresolved_work_by_manifest_key() -> None:
    manifest = load_publication_manifest(_fixture_bytes(), expected=FIXTURE_COUNTS)
    existing = (
        "publication-id",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    connection = _PublicationConnection(existing_manifest_publication=existing)

    from app.importer.publications import SqlPublicationRepository

    SqlPublicationRepository(connection).apply(manifest, "1" * 64)

    statements = "\n".join(statement for statement, _ in connection.executed)
    assert "ManifestWorkKey = ?" in statements
    assert "UPDATE dbo.ApplicationPublication SET" in statements
    assert "INSERT dbo.ApplicationPublication (" not in statements


def test_completed_identical_sql_import_is_reused_without_new_writes() -> None:
    from app.importer.publications import SqlPublicationRepository

    manifest = load_publication_manifest(_fixture_bytes(), expected=FIXTURE_COUNTS)
    connection = _PublicationConnection(completed_run="completed-run")

    result = SqlPublicationRepository(connection).apply(manifest, "f" * 64)

    assert result.reused_completed_run is True
    assert result.run_id == "completed-run"
    assert not any(
        statement.startswith("INSERT") or statement.startswith("UPDATE")
        for statement, _ in connection.executed
    )


def test_all_applicants_are_resolved_uniquely_before_the_first_write() -> None:
    from app.importer.publications import SqlPublicationRepository

    manifest = load_publication_manifest(_fixture_bytes(), expected=FIXTURE_COUNTS)
    second = PublicationApplicant("Second Folder", "Second Example", {})
    manifest = replace(manifest, applicants=(manifest.applicants[0], second))
    connection = _PublicationConnection(
        applications={
            "Alex Example": [("application-id",)],
            "Second Example": [],
        }
    )

    with pytest.raises(PublicationImportError, match="exactly one"):
        SqlPublicationRepository(connection).apply(manifest, "a" * 64)

    assert not any(
        statement.startswith("INSERT") or statement.startswith("UPDATE")
        for statement, _ in connection.executed
    )
    assert connection.commit_count == 0


def test_applicant_failure_rolls_back_marks_run_failed_and_can_be_retried() -> None:
    from app.importer.publications import SqlPublicationRepository

    class FailingConnection(_PublicationConnection):
        def execute(self, statement, *parameters):
            if "INSERT dbo.PublicationMetadataObservation" in statement:
                raise RuntimeError("synthetic evidence failure")
            return super().execute(statement, *parameters)

    manifest = load_publication_manifest(_fixture_bytes(), expected=FIXTURE_COUNTS)
    connection = FailingConnection()

    with pytest.raises(PublicationImportError, match="publication import failed"):
        SqlPublicationRepository(connection).apply(manifest, "b" * 64)

    assert connection.rollback_count == 1
    assert any(
        "SET RunStatus = 'FAILED'" in statement
        for statement, _ in connection.executed
    )
    assert connection.commit_count == 2

    retry = _PublicationConnection(existing_publication=(
        "publication-id", "10.1000/example", "https://doi.org/10.1000/example",
        "A. Example; B. Researcher", "A fixture publication", "Fixture Journal",
        "12", "10-20", 2025,
    ))
    result = SqlPublicationRepository(retry).apply(manifest, "b" * 64)
    assert result.reused_completed_run is False
    assert result.conflict_count == 0
    assert "IF NOT EXISTS" in "\n".join(statement for statement, _ in retry.executed)
