"""Official open-citation API collection and matching contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.importer.open_citation_collector import (
    OfficialCitationApiClient,
    OpenCitationCollectionError,
    _openalex_query,
    build_openalex_doi_batch_urls,
    collect_open_citation_rows,
    match_openalex_candidate,
    match_semantic_scholar_candidate,
)
from app.importer.publications import ManifestCounts, load_publication_manifest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "import" / "publications-minimal.json"
FIXTURE_COUNTS = ManifestCounts(1, 1, 2, 3)


def test_openalex_fallback_search_removes_query_syntax_and_bounds_length() -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)
    work = replace(
        manifest.works[0],
        canonical_metadata=replace(
            manifest.works[0].canonical_metadata,
            doi=None,
            doi_url=None,
            title=None,
        ),
    )

    url = _openalex_query(work, "Author, F.* " + "Population genetics — study " * 30)
    query = parse_qs(urlparse(url).query)["search"][0]

    assert "*" not in query
    assert "—" not in query
    assert len(query) <= 300


def test_openalex_skips_ineligible_doi_less_works(monkeypatch) -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)
    work = replace(
        manifest.works[0],
        canonical_metadata=replace(
            manifest.works[0].canonical_metadata,
            doi=None,
            doi_url=None,
        ),
    )
    manifest = replace(manifest, works=(work,))

    class NoRequestClient:
        def get_json(self, *_args, **_kwargs):
            raise AssertionError("DOI-less works are outside the agreed metric eligibility.")

    monkeypatch.setattr(
        "app.importer.open_citation_collector._utc_now",
        lambda: "2026-09-20T10:00:00Z",
    )

    rows = collect_open_citation_rows(manifest, NoRequestClient())

    assert rows[0]["citation_status"] == "NOT_FOUND"
    assert rows[0]["citation_count"] == ""


def test_collection_uses_openalex_for_the_common_cutoff(monkeypatch) -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)

    class OpenAlexClient:
        def get_json(self, url: str, *, allow_not_found: bool = False):
            assert "api.openalex.org" in url
            return {
                "results": [{
                    "id": "https://openalex.org/W123",
                    "title": "A fixture publication",
                    "publication_year": 2025, "cited_by_count": 17,
                    "doi": "https://doi.org/10.1000/example",
                    "authorships": [{"author": {"display_name": "Alex Example"}}],
                    "counts_by_year": [{"year": 2025, "cited_by_count": 17}],
                }],
            }

    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "app.importer.open_citation_collector._utc_now",
        lambda: "2026-08-23T15:00:00Z",
    )

    rows = collect_open_citation_rows(manifest, OpenAlexClient())

    assert len(rows) == 1
    assert rows[0]["source_code"] == "OPENALEX"
    assert rows[0]["citation_count"] == "17"


def test_official_client_uses_the_protected_openalex_api_key(monkeypatch) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "fixture-key")

    client = OfficialCitationApiClient(user_agent="fixture")
    try:
        assert client._client.headers["Authorization"] == "Bearer fixture-key"
    finally:
        client.close()


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


def test_openalex_doi_requests_use_a_batched_lookup_and_one_cutoff_timestamp(
    monkeypatch,
) -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)

    class FakeClient:
        def __init__(self) -> None:
            self.urls: list[str] = []
            self.payloads: list[dict] = []

        def get_json(self, url: str, *, allow_not_found: bool = False):
            self.urls.append(url)
            assert "api.openalex.org" in url
            assert "filter=doi%3A10.1000%2Fexample" in url or "/works/https%3A%2F%2Fdoi.org%2F10.1000%2Fexample" in url
            return {
                "results": [{
                    "id": "https://openalex.org/W123",
                    "title": "A fixture publication",
                    "publication_year": 2025,
                    "cited_by_count": 17,
                    "doi": "https://doi.org/10.1000/example",
                    "authorships": [{"author": {"display_name": "Alex Example"}}],
                    "counts_by_year": [{"year": 2025, "cited_by_count": 17}],
                }],
            }

        def post_json(self, url: str, payload: dict):
            raise AssertionError("OpenAlex collection must not use POST requests")

    client = FakeClient()
    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)
    observed_times = iter(("2026-08-23T15:00:00Z",))
    monkeypatch.setattr(
        "app.importer.open_citation_collector._utc_now",
        lambda: next(observed_times),
    )

    rows = collect_open_citation_rows(manifest, client)

    assert [row["citation_count"] for row in rows] == ["17"]
    assert rows[0]["annual_citation_counts"] == '{"2025":17}'
    assert [row["observed_at_utc"] for row in rows] == [
        "2026-08-23T15:00:00Z",
    ]
    assert len(client.urls) == 1
    assert client.payloads == []


def test_openalex_fetches_full_history_when_ten_year_counts_are_incomplete(
    monkeypatch,
) -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)

    class FakeClient:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get_json(self, url: str, *, allow_not_found: bool = False):
            self.urls.append(url)
            if "group_by=publication_year" in url:
                return {
                    "meta": {"count": 19},
                    "group_by": [
                        {"key": "2010", "count": 3},
                        {"key": "2025", "count": 16},
                    ],
                }
            return {
                "results": [{
                    "id": "https://openalex.org/W123",
                    "title": "A fixture publication",
                    "publication_year": 2010,
                    "cited_by_count": 19,
                    "doi": "https://doi.org/10.1000/example",
                    "authorships": [{"author": {"display_name": "Alex Example"}}],
                    "counts_by_year": [{"year": 2025, "cited_by_count": 16}],
                }],
            }

    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)
    rows = collect_open_citation_rows(manifest, FakeClient())

    assert rows[0]["annual_citation_counts"] == '{"2010":3,"2025":16}'


def test_openalex_does_not_spend_search_credits_on_unresolved_metadata(
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
    openalex_urls = [url for url in client.urls if "api.openalex.org" in url]
    assert openalex_urls == []
    assert rows[0]["result_url"] == "https://api.openalex.org/works"


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
    assert match.annual_citation_counts == {}


def test_openalex_match_preserves_valid_annual_counts_and_discards_invalid_entries() -> None:
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
            "counts_by_year": [
                {"year": 2024, "cited_by_count": 3},
                {"year": 2025, "cited_by_count": 16},
                {"year": 2026, "cited_by_count": -1},
                {"year": "2023", "cited_by_count": 99},
            ],
        },
    )

    assert match is not None
    assert match.annual_citation_counts == {"2024": 3, "2025": 16}


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


def test_semantic_scholar_doi_match_requires_author_evidence() -> None:
    work, raw = _work()

    match = match_semantic_scholar_candidate(
        work,
        raw,
        {
            "paperId": "paper-without-authors",
            "title": "A fixture publication",
            "year": 2025,
            "citationCount": 17,
            "url": "https://www.semanticscholar.org/paper/paper-without-authors",
            "externalIds": {"DOI": "10.1000/example"},
            "authors": [],
        },
    )

    assert match is None


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
