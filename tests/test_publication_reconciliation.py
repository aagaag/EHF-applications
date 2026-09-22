"""Additive reconciliation of the corpus parser into a reviewed manifest."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

from pypdf import PdfWriter

from app.importer.publication_extraction import (
    DocumentExtractionAudit,
    ParsedPublication,
    PublicationCandidate,
)
from app.importer.publication_reconciliation import (
    main,
    map_applicant_folders,
    reconcile_publication_manifest,
    run_corpus_reconciliation,
    write_reconciliation_artifacts,
)
from app.importer.publications import ManifestCounts, load_publication_manifest


FIXTURE = Path("tests/fixtures/import/publications-minimal.json")


def _candidate(raw: str, *, year: int | None = 2025, page: int = 3) -> PublicationCandidate:
    return PublicationCandidate(
        applicant_name="Alex Example",
        filename="alex-cv.pdf",
        page_start=page,
        page_end=page,
        line_start=10,
        line_end=12,
        section_label="PUBLICATIONS",
        status_hint="PUBLISHED",
        raw_citation=raw,
        normalized_citation=" ".join(raw.casefold().split()),
        year=year,
        segmentation_method="test",
    )


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _assert_loads(document: dict) -> None:
    expected = ManifestCounts(
        len(document["applicants"]),
        len(document["works"]),
        len(document["source_occurrences"]),
        len(document["citation_source_statuses"]),
    )
    load_publication_manifest(
        json.dumps(document, ensure_ascii=False).encode("utf-8"), expected=expected
    )


def test_matching_pending_work_is_promoted_without_requiring_a_doi() -> None:
    """Break caught: a clear DOI-less journal paper remained hidden as pending."""
    document = _load_fixture()
    work = document["works"][0]
    work["canonical_metadata"]["doi"] = None
    work["canonical_metadata"]["doi_url"] = None
    work["resolution"] = {
        "status": "UNRESOLVED",
        "method": "HISTORICAL_IMPORT",
        "evidence": {
            "review_disposition": "PENDING_REVIEW",
            "review_reason": "Previously incomplete.",
            "review_evidence": {"source": "fixture"},
        },
    }

    result = reconcile_publication_manifest(
        document,
        [_candidate("Example A, Researcher B. A fixture publication. Fixture Journal. 2025.")],
        generated_at_utc="2026-09-22T12:00:00Z",
    )

    revised = result.document["works"][0]
    assert revised["final_work_id"] == "work-001"
    assert revised["resolution"]["status"] == "UNRESOLVED"
    assert revised["resolution"]["evidence"]["review_disposition"] == "PUBLISHED"
    assert result.audit_rows[0]["action"] == "MATCHED_TITLE"
    _assert_loads(result.document)


def test_title_matching_ignores_safe_html_markup_in_existing_metadata() -> None:
    """Break caught: formatted Crossref titles duplicated the same plain-text PDF paper."""
    document = _load_fixture()
    work = document["works"][0]
    work["canonical_metadata"]["title"] = (
        "A fixture <i>publication</i> with formatted metadata"
    )
    candidate = _candidate(
        "Example A, Researcher B. A fixture publication with formatted metadata. "
        "Fixture Journal. 2025."
    )

    result = reconcile_publication_manifest(
        document, [candidate], generated_at_utc="2026-09-22T12:00:00Z"
    )

    assert len(result.document["works"]) == 1
    assert result.audit_rows[0]["action"] == "MATCHED_TITLE"
    _assert_loads(result.document)


def test_exact_preexisting_title_duplicates_are_quarantined_before_reconciliation() -> None:
    """Break caught: a DOI-less copy and a DOI copy counted the same paper twice."""
    document = _load_fixture()
    duplicate = copy.deepcopy(document["works"][0])
    duplicate["final_work_id"] = "work-duplicate"
    duplicate["canonical_metadata"]["doi"] = None
    duplicate["canonical_metadata"]["doi_url"] = None
    duplicate["resolution"]["status"] = "UNRESOLVED"
    duplicate["source_occurrence_ids"] = ["occ-duplicate"]
    duplicate["source_work_ids"] = ["source-duplicate"]
    duplicate["representative_source_occurrence_id"] = "occ-duplicate"
    document["works"].append(duplicate)
    occurrence = copy.deepcopy(document["source_occurrences"][0])
    occurrence["source_occurrence_id"] = "occ-duplicate"
    occurrence["source_work_id"] = "source-duplicate"
    occurrence["final_work_id"] = "work-duplicate"
    document["source_occurrences"].append(occurrence)
    duplicate_statuses = []
    for row in document["citation_source_statuses"]:
        copied = copy.deepcopy(row)
        copied["final_work_id"] = "work-duplicate"
        duplicate_statuses.append(copied)
    document["citation_source_statuses"].extend(duplicate_statuses)

    result = reconcile_publication_manifest(
        document,
        [_candidate("Example A, Researcher B. A fixture publication. Fixture Journal. 2025.")],
        generated_at_utc="2026-09-22T12:00:00Z",
    )

    assert len(result.document["works"]) == 2
    assert len(result.document["source_occurrences"]) == 4
    assert len(result.document["citation_source_statuses"]) == 6
    duplicate_after = next(
        work for work in result.document["works"] if work["final_work_id"] == "work-duplicate"
    )
    assert duplicate_after["resolution"]["evidence"]["review_disposition"] == "NON_PUBLICATION"
    assert result.audit_rows[0]["final_work_id"] == "work-001"
    assert result.audit_rows[0]["action"] == "MATCHED_TITLE"
    _assert_loads(result.document)


def test_empty_pending_legacy_record_is_quarantined_as_non_publication() -> None:
    """Break caught: titleless parser artifacts clogged the pending-paper review page."""
    document = _load_fixture()
    work = document["works"][0]
    work["canonical_metadata"] = {
        name: None
        for name in ("doi", "doi_url", "authors_text", "title", "journal", "volume", "pages", "year")
    }
    work["resolution"] = {
        "status": "UNRESOLVED",
        "method": "LEGACY_PARSER",
        "evidence": {
            "review_disposition": "PENDING_REVIEW",
            "review_reason": "No fields were parsed.",
            "review_evidence": {"source": "legacy"},
        },
    }

    result = reconcile_publication_manifest(
        document, [], generated_at_utc="2026-09-22T12:00:00Z"
    )

    evidence = result.document["works"][0]["resolution"]["evidence"]
    assert evidence["review_disposition"] == "NON_PUBLICATION"
    assert "empty legacy parser artifact" in evidence["review_reason"].casefold()
    _assert_loads(result.document)


def test_unmatched_unparsable_fragment_is_audited_without_creating_a_work() -> None:
    """Break caught: impact-factor and header fragments clogged pending-paper review."""
    document = _load_fixture()
    result = reconcile_publication_manifest(
        document,
        [_candidate("Example A. IF 7.749. Preprint header. 2025.")],
        generated_at_utc="2026-09-22T12:00:00Z",
    )

    assert len(result.document["works"]) == 1
    assert result.audit_rows[0]["action"] == "SKIPPED_UNPARSABLE_CITATION"
    assert result.audit_rows[0]["final_work_id"] is None
    _assert_loads(result.document)


def test_reconciliation_cli_runs_private_corpus_with_explicit_public_resolution(
    monkeypatch, tmp_path, capsys
) -> None:
    """Break caught: the audited parser existed only as an ad-hoc Python invocation."""
    captured = {}

    def fake_run(base, source, output, **options):
        captured.update(base=base, source=source, output=output, **options)
        return SimpleNamespace(
            paths={"manifest": output / "run-manifest.json"},
            manifest_counts=ManifestCounts(36, 10, 20, 30),
        )

    monkeypatch.setattr(
        "app.importer.publication_reconciliation.run_corpus_reconciliation", fake_run
    )
    base = tmp_path / "base.json"
    source = tmp_path / "source"
    output = tmp_path / "output"

    exit_code = main(
        [
            "--base-manifest",
            str(base),
            "--source-root",
            str(source),
            "--output-directory",
            str(output),
            "--resolve-public-bibliography",
            "--stem",
            "run",
        ]
    )

    assert exit_code == 0
    assert captured["base"] == base
    assert captured["source"] == source
    assert captured["output"] == output
    assert captured["resolve_public_bibliography"] is True
    assert captured["stem"] == "run"
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"] == {
        "applicants": 36,
        "works": 10,
        "source_occurrences": 20,
        "citation_statuses": 30,
    }


def test_reconciliation_is_idempotent_for_the_same_document_occurrence() -> None:
    """Break caught: every parser run duplicated the same source occurrence."""
    candidate = _candidate(
        "Example A, Researcher B. A fixture publication. Fixture Journal. 2025."
    )
    first = reconcile_publication_manifest(
        _load_fixture(), [candidate], generated_at_utc="2026-09-22T12:00:00Z"
    )
    second = reconcile_publication_manifest(
        first.document, [candidate], generated_at_utc="2026-09-22T12:00:00Z"
    )

    assert len(second.document["works"]) == 1
    assert len(second.document["source_occurrences"]) == 3
    assert second.audit_rows[0]["action"] == "ALREADY_RECONCILED"
    _assert_loads(second.document)


def test_unmatched_complete_paper_adds_stable_work_provenance_and_three_statuses() -> None:
    """Break caught: newly discovered papers lacked importable provenance or citation rows."""
    raw = "Example A, Researcher B. A newly recovered paper. Recovery Journal. 2024; 8: 11-19."
    result = reconcile_publication_manifest(
        _load_fixture(),
        [_candidate(raw, year=2024, page=9)],
        generated_at_utc="2026-09-22T12:00:00Z",
    )

    assert len(result.document["works"]) == 2
    added = result.document["works"][-1]
    assert added["final_work_id"].startswith("parser-")
    assert added["canonical_metadata"]["title"] == "A newly recovered paper"
    assert added["resolution"]["evidence"]["review_disposition"] == "PUBLISHED"
    statuses = [
        row for row in result.document["citation_source_statuses"]
        if row["final_work_id"] == added["final_work_id"]
    ]
    assert {row["source"] for row in statuses} == {
        "GOOGLE_SCHOLAR", "BIORXIV", "MEDRXIV"
    }
    assert result.audit_rows[0]["action"] == "ADDED_WORK"
    _assert_loads(result.document)


def test_confirmed_nonpending_manual_disposition_is_preserved() -> None:
    """Break caught: automation overwrote an explicit human preprint decision."""
    document = _load_fixture()
    document["works"][0]["resolution"]["evidence"].update(
        {
            "review_disposition": "ACCEPTED_PREPRINT",
            "review_reason": "Human-reviewed preprint.",
            "review_evidence": {"source": "manual"},
        }
    )

    result = reconcile_publication_manifest(
        document,
        [_candidate("Example A, Researcher B. A fixture publication. Fixture Journal. 2025.")],
        generated_at_utc="2026-09-22T12:00:00Z",
    )

    evidence = result.document["works"][0]["resolution"]["evidence"]
    assert evidence["review_disposition"] == "ACCEPTED_PREPRINT"
    assert result.audit_rows[0]["decision_action"] == "PRESERVED_EXPLICIT_REVIEW"
    _assert_loads(result.document)


def test_same_title_with_incompatible_year_is_not_merged() -> None:
    """Break caught: distinct editions with the same title were silently collapsed."""
    result = reconcile_publication_manifest(
        _load_fixture(),
        [_candidate("Example A, Researcher B. A fixture publication. Fixture Journal. 2015.", year=2015)],
        generated_at_utc="2026-09-22T12:00:00Z",
    )

    assert len(result.document["works"]) == 2
    assert result.audit_rows[0]["action"] == "ADDED_WORK"
    assert result.document["works"][-1]["canonical_metadata"]["year"] == 2015
    _assert_loads(result.document)


def test_reconciliation_does_not_mutate_the_input_document() -> None:
    """Break caught: a failed reconciliation could corrupt the caller's baseline manifest."""
    document = _load_fixture()
    before = copy.deepcopy(document)

    reconcile_publication_manifest(
        document,
        [_candidate("Example A, Researcher B. A new paper. New Journal. 2025.")],
        generated_at_utc="2026-09-22T12:00:00Z",
    )

    assert document == before


def test_local_structured_parser_is_augmented_by_deterministic_fallback() -> None:
    """Break caught: partial GROBID output discarded reliable year and venue evidence."""
    candidate = _candidate(
        "Example A, Researcher B. A structured paper. Structured Journal. 2025."
    )

    def partial_parser(raw: str) -> ParsedPublication:
        return ParsedPublication(
            authors=("Alex Example", "Bea Researcher"),
            title="A structured paper",
            raw_citation=raw,
            parser_method="grobid",
            field_evidence=("authors", "title"),
        )

    result = reconcile_publication_manifest(
        _load_fixture(),
        [candidate],
        citation_parser=partial_parser,
        generated_at_utc="2026-09-22T12:00:00Z",
    )

    added = result.document["works"][-1]
    assert added["canonical_metadata"]["authors_text"] == "Alex Example; Bea Researcher"
    assert added["canonical_metadata"]["journal"] == "Structured Journal"
    assert added["canonical_metadata"]["year"] == 2025
    assert (
        added["resolution"]["evidence"]["review_evidence"]["parser_method"]
        == "grobid+deterministic"
    )
    _assert_loads(result.document)


def test_maps_each_applicant_directory_by_unicode_folded_name(tmp_path) -> None:
    """Break caught: accents and surname-only folders caused applicants to be skipped."""
    for name in ("Blaz", "Chopard", "Xuan", "Selection Committee"):
        (tmp_path / name).mkdir()
    applicants = [
        {"workbook_applicant": "Blaž Burja"},
        {"workbook_applicant": "Daphné Chopard"},
        {"workbook_applicant": "Hung Ho-Xuan"},
    ]

    mapping = map_applicant_folders(tmp_path, applicants)

    assert mapping == {
        "Blaz": "Blaž Burja",
        "Chopard": "Daphné Chopard",
        "Xuan": "Hung Ho-Xuan",
    }


def test_writes_private_manifest_and_complete_json_csv_audits(tmp_path) -> None:
    """Break caught: corpus processing emitted a manifest without document-level audit evidence."""
    candidate = _candidate(
        "Example A, Researcher B. A fixture publication. Fixture Journal. 2025."
    )
    result = reconcile_publication_manifest(
        _load_fixture(), [candidate], generated_at_utc="2026-09-22T12:00:00Z"
    )
    audits = (
        DocumentExtractionAudit(
            source_path="C:/private/alex-cv.pdf",
            source_sha256="a" * 64,
            page_count=2,
            pages_scanned=2,
            candidates=(candidate,),
            extraction_modes=("plain", "layout"),
            issues=(),
        ),
        DocumentExtractionAudit(
            source_path="C:/private/empty.pdf",
            source_sha256="b" * 64,
            page_count=1,
            pages_scanned=1,
            candidates=(),
            extraction_modes=("plain",),
            issues=("NO_EXTRACTABLE_TEXT",),
        ),
    )

    paths = write_reconciliation_artifacts(tmp_path, result, audits, stem="p-test")

    assert set(paths) == {"manifest", "audit_json", "audit_csv"}
    assert json.loads(paths["manifest"].read_text(encoding="utf-8"))["works"]
    audit = json.loads(paths["audit_json"].read_text(encoding="utf-8"))
    assert audit["summary"] == {
        "documents": 2,
        "pages": 3,
        "candidates": 1,
        "documents_with_issues": 1,
    }
    assert len(audit["documents"]) == 2
    assert "NO_EXTRACTABLE_TEXT" in paths["audit_csv"].read_text(encoding="utf-8")


def test_corpus_runner_audits_every_mapped_pdf_and_validates_output(tmp_path) -> None:
    """Break caught: the operator path skipped empty PDFs or emitted an invalid manifest."""
    source_root = tmp_path / "source"
    applicant_dir = source_root / "Example"
    applicant_dir.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with (applicant_dir / "application.pdf").open("wb") as handle:
        writer.write(handle)
    base_path = tmp_path / "base.json"
    base_path.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    output_dir = tmp_path / "output"

    run = run_corpus_reconciliation(
        base_path, source_root, output_dir, stem="p-run"
    )

    audit = json.loads(run.paths["audit_json"].read_text(encoding="utf-8"))
    assert audit["summary"] == {
        "documents": 1,
        "pages": 1,
        "candidates": 0,
        "documents_with_issues": 1,
    }
    assert run.manifest_counts == ManifestCounts(1, 1, 2, 3)
    assert run.accepted_counts_before == run.accepted_counts_after
    _assert_loads(json.loads(run.paths["manifest"].read_text(encoding="utf-8")))


def test_reconciliation_normalizes_doi_and_url_to_the_same_lowercase_value() -> None:
    """Break caught: uppercase source DOIs made the generated manifest fail strict validation."""
    result = reconcile_publication_manifest(
        _load_fixture(),
        [
            _candidate(
                "Example A, Researcher B. A DOI case paper. Case Journal. 2025. doi:10.1234/UPPER.ABC"
            )
        ],
        generated_at_utc="2026-09-22T12:00:00Z",
    )

    metadata = result.document["works"][-1]["canonical_metadata"]
    assert metadata["doi"] == "10.1234/upper.abc"
    assert metadata["doi_url"] == "https://doi.org/10.1234/upper.abc"
    _assert_loads(result.document)


def test_new_doi_promotes_matched_unresolved_work_to_resolved() -> None:
    """Break caught: filling a DOI left resolution status inconsistent with canonical metadata."""
    document = _load_fixture()
    work = document["works"][0]
    work["canonical_metadata"]["doi"] = None
    work["canonical_metadata"]["doi_url"] = None
    work["resolution"]["status"] = "UNRESOLVED"

    result = reconcile_publication_manifest(
        document,
        [
            _candidate(
                "Example A, Researcher B. A fixture publication. Fixture Journal. 2025. doi:10.1000/EXAMPLE"
            )
        ],
        generated_at_utc="2026-09-22T12:00:00Z",
    )

    revised = result.document["works"][0]
    assert revised["canonical_metadata"]["doi"] == "10.1000/example"
    assert revised["resolution"]["status"] == "RESOLVED"
    _assert_loads(result.document)


def test_existing_canonical_title_inside_citation_prevents_parser_drift_duplicate() -> None:
    """Break caught: APA-style author/year order created a duplicate of an existing work."""
    candidate = _candidate(
        "Example A, Researcher B. (2025). A fixture publication. Fixture Journal 12: 10-20."
    )

    result = reconcile_publication_manifest(
        _load_fixture(), [candidate], generated_at_utc="2026-09-22T12:00:00Z"
    )

    assert len(result.document["works"]) == 1
    assert result.audit_rows[0]["action"] == "MATCHED_TITLE"
    _assert_loads(result.document)


def test_ambiguous_parser_result_does_not_downgrade_implicitly_published_doi_work() -> None:
    """Break caught: parser uncertainty hid an already DOI-resolved publication."""
    candidate = _candidate(
        "Example A, Researcher B — A fixture publication (2025)"
    )

    result = reconcile_publication_manifest(
        _load_fixture(), [candidate], generated_at_utc="2026-09-22T12:00:00Z"
    )

    evidence = result.document["works"][0]["resolution"]["evidence"]
    assert "review_disposition" not in evidence
    assert result.audit_rows[0]["decision_action"] == "PRESERVED_RESOLVED_PUBLICATION"
    _assert_loads(result.document)


def test_public_bibliographic_resolution_runs_only_after_local_matching_misses() -> None:
    """Break caught: parser drift created a duplicate before canonical public validation."""
    candidate = _candidate(
        "Example A, Researcher B. (2025). A fixtur publication with formatting drift."
    )
    calls = []

    def resolve_public(item: PublicationCandidate, fallback: ParsedPublication) -> ParsedPublication:
        calls.append((item, fallback))
        return ParsedPublication(
            authors=("Alex Example", "Bea Researcher"),
            title="A fixture publication",
            journal="Fixture Journal",
            volume="12",
            pages="10-20",
            year=2025,
            doi="10.1000/example",
            raw_citation=item.raw_citation,
            parser_method="crossref-bibliographic",
        )

    result = reconcile_publication_manifest(
        _load_fixture(),
        [candidate],
        bibliographic_resolver=resolve_public,
        generated_at_utc="2026-09-22T12:00:00Z",
    )

    assert len(calls) == 1
    assert len(result.document["works"]) == 1
    assert result.audit_rows[0]["action"] == "MATCHED_DOI"
    _assert_loads(result.document)


def test_candidate_containing_multiple_existing_titles_is_audited_not_added() -> None:
    """Break caught: a merged PDF block became a third, bogus publication record."""
    first = reconcile_publication_manifest(
        _load_fixture(),
        [
            _candidate(
                "Example A, Researcher B. A second genuinely distinct publication. Second Journal. 2024.",
                year=2024,
                page=4,
            )
        ],
        generated_at_utc="2026-09-22T12:00:00Z",
    )
    merged = _candidate(
        "Example A. A fixture publication. Fixture Journal. 2025. "
        "Example A. A second genuinely distinct publication. Second Journal. 2024.",
        year=2024,
        page=8,
    )

    second = reconcile_publication_manifest(
        first.document, [merged], generated_at_utc="2026-09-22T12:00:00Z"
    )

    assert len(second.document["works"]) == 2
    assert second.audit_rows[0]["action"] == "SKIPPED_AMBIGUOUS_CITATION"
    assert second.audit_rows[0]["final_work_id"] is None
    _assert_loads(second.document)


def test_long_exact_title_wins_over_existing_title_nested_inside_it() -> None:
    """Break caught: a paper title containing a shorter title was falsely treated as two citations."""
    long_title = "Towards Scalable Screening: A fixture publication"
    first = reconcile_publication_manifest(
        _load_fixture(),
        [
            _candidate(
                "Example A, Researcher B. An unrelated second long title. Long Journal. 2025.",
                page=4,
            )
        ],
        generated_at_utc="2026-09-22T12:00:00Z",
    )
    first.document["works"][-1]["canonical_metadata"]["title"] = long_title

    second = reconcile_publication_manifest(
        first.document,
        [
            _candidate(
                f"Example A, Researcher B. {long_title}. Long Journal. 2025.",
                page=8,
            )
        ],
        generated_at_utc="2026-09-22T12:00:00Z",
    )

    assert len(second.document["works"]) == 2
    assert second.audit_rows[0]["action"] == "MATCHED_TITLE"
    _assert_loads(second.document)
