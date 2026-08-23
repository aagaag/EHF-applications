"""Official open-citation API collection and matching contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.importer.open_citation_collector import (
    build_openalex_doi_batch_urls,
    collect_open_citation_rows,
    match_openalex_candidate,
    match_semantic_scholar_candidate,
)
from app.importer.publications import ManifestCounts, load_publication_manifest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "import" / "publications-minimal.json"
FIXTURE_COUNTS = ManifestCounts(1, 1, 2, 3)


def test_openalex_doi_requests_are_batched_at_the_documented_limit() -> None:
    batches = build_openalex_doi_batch_urls(
        tuple(f"10.1000/example-{index}" for index in range(205))
    )

    assert len(batches) == 3
    assert [len(dois) for dois, _url in batches] == [100, 100, 5]
    assert all("filter=doi%3A" in url for _dois, url in batches)
    assert all("per_page=100" in url for _dois, url in batches)
    assert all("select=id%2Cdoi%2Ctitle%2Cpublication_year%2Ccited_by_count%2Cauthorships" in url for _dois, url in batches)


def test_semantic_scholar_uses_rate_paced_direct_doi_requests(
    monkeypatch,
) -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)

    class FakeClient:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get_json(self, url: str):
            self.urls.append(url)
            if "api.openalex.org" in url:
                return {
                    "results": [
                        {
                            "id": "https://openalex.org/W123",
                            "doi": "https://doi.org/10.1000/example",
                            "title": "A fixture publication",
                            "publication_year": 2025,
                            "cited_by_count": 19,
                            "authorships": [
                                {"author": {"display_name": "Alex Example"}}
                            ],
                        }
                    ]
                }
            return {
                "paperId": "paper-1",
                "title": "A fixture publication",
                "year": 2025,
                "citationCount": 17,
                "url": "https://www.semanticscholar.org/paper/paper-1",
                "externalIds": {"DOI": "10.1000/example"},
                "authors": [{"name": "Alex Example"}],
            }

        def post_json(self, url: str, payload: dict):
            raise AssertionError("the unauthenticated batch endpoint must not be used")

    client = FakeClient()
    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)
    observed_times = iter(("2026-08-23T15:00:00Z", "2026-08-23T15:00:01Z"))
    monkeypatch.setattr(
        "app.importer.open_citation_collector._utc_now",
        lambda: next(observed_times),
    )

    rows = collect_open_citation_rows(manifest, client)

    assert [row["citation_count"] for row in rows] == ["19", "17"]
    assert [row["observed_at_utc"] for row in rows] == [
        "2026-08-23T15:00:00Z",
        "2026-08-23T15:00:01Z",
    ]
    assert any("/paper/DOI:10.1000%2Fexample" in url for url in client.urls)


def test_semantic_scholar_queries_raw_citation_when_metadata_is_unresolved(
    monkeypatch,
) -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)
    work = manifest.works[0]
    unresolved = replace(
        work,
        canonical_metadata=replace(work.canonical_metadata, doi=None, title=None),
    )
    manifest = replace(manifest, works=(unresolved,))

    class EmptyClient:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get_json(self, url: str):
            self.urls.append(url)
            if "api.openalex.org" in url:
                return {"results": []}
            return {"data": []}

    client = EmptyClient()
    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)

    rows = collect_open_citation_rows(manifest, client)

    assert rows[1]["citation_status"] == "NOT_FOUND"
    semantic_urls = [
        url for url in client.urls if "api.semanticscholar.org" in url
    ]
    assert len(semantic_urls) == 1
    assert "paper/search?" in semantic_urls[0]
    assert "fixture+publication" in semantic_urls[0]


def _work():
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)
    raw = " ".join(
        occurrence.normalized_raw_citation
        for occurrence in manifest.source_occurrences
        if occurrence.final_work_id == manifest.works[0].final_work_id
    )
    return manifest.works[0], raw


def test_openalex_match_prefers_exact_doi_and_preserves_source_count() -> None:
    work, raw = _work()
    match = match_openalex_candidate(
        work,
        raw,
        {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1000/example",
            "title": "A fixture publication",
            "publication_year": 2025,
            "cited_by_count": 19,
            "authorships": [{"author": {"display_name": "Alex Example"}}],
        },
    )

    assert match is not None
    assert match.match_method == "DOI_EXACT"
    assert match.citation_count == 19
    assert match.matched_doi == "10.1000/example"


def test_title_and_raw_citation_matching_rejects_ranked_but_unrelated_results() -> None:
    work, raw = _work()
    related = match_semantic_scholar_candidate(
        work,
        raw,
        {
            "paperId": "paper-1",
            "title": "A fixture publication",
            "year": 2025,
            "citationCount": 17,
            "url": "https://www.semanticscholar.org/paper/paper-1",
            "externalIds": {},
            "authors": [{"name": "Alex Example"}],
        },
    )
    unrelated = match_semantic_scholar_candidate(
        work,
        raw,
        {
            "paperId": "paper-2",
            "title": "A highly cited but unrelated publication",
            "year": 2025,
            "citationCount": 9999,
            "url": "https://www.semanticscholar.org/paper/paper-2",
            "externalIds": {},
            "authors": [{"name": "Someone Else"}],
        },
    )
    wrong_author_collision = match_semantic_scholar_candidate(
        work,
        raw,
        {
            "paperId": "paper-3",
            "title": "A fixture publication",
            "year": 2025,
            "citationCount": 888,
            "url": "https://www.semanticscholar.org/paper/paper-3",
            "externalIds": {},
            "authors": [{"name": "Someone Else"}],
        },
    )

    assert related is not None and related.match_method == "TITLE_EXACT"
    assert unrelated is None
    assert wrong_author_collision is None


def test_raw_citation_match_requires_title_in_source_and_applicant_author() -> None:
    work, _ = _work()
    candidate = {
        "id": "https://openalex.org/W456",
        "doi": None,
        "title": "A newly resolved publication from the dossier",
        "publication_year": 2024,
        "cited_by_count": 7,
        "authorships": [{"author": {"display_name": "Alex Example"}}],
    }

    accepted = match_openalex_candidate(
        work,
        "alex example a newly resolved publication from the dossier journal 2024",
        candidate,
    )
    rejected = match_openalex_candidate(
        work,
        "alex example a different dossier entry journal 2024",
        candidate,
    )

    assert accepted is not None and accepted.match_method == "RAW_CITATION_EXACT"
    assert rejected is None
