"""Official open-citation API collection and matching contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.importer.open_citation_collector import (
    OfficialCitationApiClient,
    OpenCitationCollectionError,
    build_openalex_doi_batch_urls,
    collect_open_citation_rows,
    match_openalex_candidate,
    match_semantic_scholar_candidate,
)
from app.importer.publications import ManifestCounts, load_publication_manifest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "import" / "publications-minimal.json"
FIXTURE_COUNTS = ManifestCounts(1, 1, 2, 3)


def test_collection_uses_semantic_scholar_without_calling_openalex(monkeypatch) -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)

    class SemanticOnlyClient:
        def get_json(self, url: str, *, allow_not_found: bool = False):
            if "api.openalex.org" in url:
                raise AssertionError("OpenAlex must be optional and unqueried")
            raise AssertionError("a DOI-bearing work must use the batch endpoint")

        def post_json(self, url: str, payload: dict):
            assert "api.semanticscholar.org" in url
            assert payload == {"ids": ["DOI:10.1000/example"]}
            return [{
                "paperId": "0123456789abcdef0123456789abcdef01234567",
                "title": "A fixture publication",
                "year": 2025,
                "citationCount": 17,
                "url": "https://www.semanticscholar.org/paper/0123456789abcdef0123456789abcdef01234567",
                "externalIds": {"DOI": "10.1000/example"},
                "authors": [{"name": "Alex Example"}],
            }]

    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "app.importer.open_citation_collector._utc_now",
        lambda: "2026-08-23T15:00:00Z",
    )

    rows = collect_open_citation_rows(manifest, SemanticOnlyClient())

    assert len(rows) == 1
    assert rows[0]["source_code"] == "SEMANTIC_SCHOLAR"
    assert rows[0]["citation_count"] == "17"


def test_rate_limit_failure_identifies_the_official_api_host(monkeypatch) -> None:
    class Response:
        status_code = 429
        headers: dict[str, str] = {}

    class RateLimitedClient:
        def request(self, *args, **kwargs):
            return Response()

        def close(self) -> None:
            pass

    client = OfficialCitationApiClient(user_agent="fixture")
    client._client.close()
    client._client = RateLimitedClient()
    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)

    with pytest.raises(
        OpenCitationCollectionError,
        match=r"api\.openalex\.org.*429",
    ):
        client.get_json("https://api.openalex.org/works/W123")


def test_http_404_is_absence_only_for_direct_paper_lookup() -> None:
    class Response:
        status_code = 404
        headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            raise AssertionError("404 handling must occur before raise_for_status")

    class NotFoundClient:
        def request(self, *args, **kwargs):
            return Response()

        def close(self) -> None:
            pass

    client = OfficialCitationApiClient(user_agent="fixture")
    client._client.close()
    client._client = NotFoundClient()

    assert client.get_json(
        "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1000%2Fmissing",
        allow_not_found=True,
    ) is None
    with pytest.raises(OpenCitationCollectionError, match=r"404"):
        client.get_json(
            "https://api.semanticscholar.org/graph/v1/paper/search?query=missing"
        )


def test_retry_window_survives_a_longer_shared_pool_throttle(monkeypatch) -> None:
    class Response:
        headers: dict[str, str] = {}

        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"status": "available"}

    class RecoveringClient:
        def __init__(self) -> None:
            self.calls = 0

        def request(self, *args, **kwargs):
            self.calls += 1
            return Response(429 if self.calls <= 6 else 200)

        def close(self) -> None:
            pass

    transport = RecoveringClient()
    client = OfficialCitationApiClient(user_agent="fixture")
    client._client.close()
    client._client = transport
    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)

    assert client.get_json("https://api.semanticscholar.org/graph/v1/paper/search/bulk") == {
        "status": "available"
    }
    assert transport.calls == 7


def test_openalex_doi_requests_are_batched_at_the_documented_limit() -> None:
    batches = build_openalex_doi_batch_urls(
        tuple(f"10.1000/example-{index}" for index in range(205))
    )

    assert len(batches) == 3
    assert [len(dois) for dois, _url in batches] == [100, 100, 5]
    assert all("filter=doi%3A" in url for _dois, url in batches)
    assert all("per_page=100" in url for _dois, url in batches)
    assert all("select=id%2Cdoi%2Ctitle%2Cpublication_year%2Ccited_by_count%2Cauthorships" in url for _dois, url in batches)


def test_semantic_scholar_batches_doi_requests_at_the_documented_limit(
    monkeypatch,
) -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)

    class FakeClient:
        def __init__(self) -> None:
            self.urls: list[str] = []
            self.payloads: list[dict] = []

        def get_json(self, url: str, *, allow_not_found: bool = False):
            self.urls.append(url)
            raise AssertionError("a DOI-bearing work must not use a GET request")

        def post_json(self, url: str, payload: dict):
            self.urls.append(url)
            self.payloads.append(payload)
            return {
                "unexpected": "shape"
            } if not payload.get("ids") else [{
                "paperId": "paper-1",
                "title": "A fixture publication",
                "year": 2025,
                "citationCount": 17,
                "url": "https://www.semanticscholar.org/paper/paper-1",
                "externalIds": {"DOI": "10.1000/example"},
                "authors": [{"name": "Alex Example"}],
            }]

    client = FakeClient()
    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)
    observed_times = iter(("2026-08-23T15:00:00Z",))
    monkeypatch.setattr(
        "app.importer.open_citation_collector._utc_now",
        lambda: next(observed_times),
    )

    rows = collect_open_citation_rows(manifest, client)

    assert [row["citation_count"] for row in rows] == ["17"]
    assert [row["observed_at_utc"] for row in rows] == [
        "2026-08-23T15:00:00Z",
    ]
    assert any("/paper/batch?" in url for url in client.urls)
    assert client.payloads == [{"ids": ["DOI:10.1000/example"]}]


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

        def get_json(self, url: str, *, allow_not_found: bool = False):
            self.urls.append(url)
            if "api.openalex.org" in url:
                return {"results": []}
            return {"data": []}

    client = EmptyClient()
    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)

    rows = collect_open_citation_rows(manifest, client)

    assert rows[0]["citation_status"] == "NOT_FOUND"
    semantic_urls = [
        url for url in client.urls if "api.semanticscholar.org" in url
    ]
    assert len(semantic_urls) == 1
    assert "paper/search/bulk?" in semantic_urls[0]
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
