"""Official open-citation API collection and matching contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.importer import collect_open_citations as collector_command
from app.importer.open_citation_collector import (
    OfficialCitationApiClient,
    OpenCitationCollectionError,
    _openalex_query,
    build_openalex_doi_batch_urls,
    collect_open_citation_rows,
    collect_semantic_scholar_rows,
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


def test_semantic_scholar_collection_emits_an_observed_row_for_a_doi_work(
    monkeypatch,
) -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)

    class SemanticScholarClient:
        def post_json(self, url: str, payload: dict):
            assert url.startswith("https://api.semanticscholar.org/graph/v1/paper/batch?")
            assert payload == {"ids": ["DOI:10.1000/example"]}
            return [{
                "paperId": "a" * 40,
                "title": "A fixture publication",
                "year": 2025,
                "citationCount": 17,
                "url": "https://www.semanticscholar.org/paper/" + "a" * 40,
                "externalIds": {"DOI": "10.1000/example"},
                "authors": [{"name": "Alex Example"}],
            }]

        def get_json(self, *_args, **_kwargs):
            raise AssertionError("A DOI match must not use title search.")

    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "app.importer.open_citation_collector._utc_now",
        lambda: "2026-09-20T10:00:00Z",
    )

    rows = collect_semantic_scholar_rows(manifest, SemanticScholarClient())

    assert rows == ({
        "applicant": "Alex Example",
        "final_work_id": "work-001",
        "doi": "10.1000/example",
        "title": "A fixture publication",
        "year": "2025",
        "source_code": "SEMANTIC_SCHOLAR",
        "citation_status": "OBSERVED",
        "citation_count": "17",
        "source_identifier": "a" * 40,
        "result_url": "https://www.semanticscholar.org/paper/" + "a" * 40,
        "matched_doi": "10.1000/example",
        "matched_title": "A fixture publication",
        "matched_authors": "Alex Example",
        "observed_at_utc": "2026-09-20T10:00:00Z",
        "reviewer": "EHF Semantic Scholar cutoff collector 2026.7",
        "match_method": "DOI_EXACT",
        "annual_citation_counts": "{}",
        "journal_openalex_id": "",
        "journal_openalex_name": "",
        "journal_source_type": "",
        "journal_two_year_mean_citedness": "",
        "journal_source_updated_date": "",
        "journal_metric_observed_at_utc": "",
    },)


def test_semantic_scholar_falls_back_when_the_doi_batch_result_is_absent(
    monkeypatch,
) -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)

    class SemanticScholarClient:
        def post_json(self, _url: str, _payload: dict):
            return [None]

        def get_json(self, url: str, *, allow_not_found: bool = False):
            assert not allow_not_found
            assert parse_qs(urlparse(url).query)["query"] == ["A fixture publication"]
            return {"data": [{
                "paperId": "c" * 40,
                "title": "A fixture publication",
                "year": 2025,
                "citationCount": 9,
                "url": "https://www.semanticscholar.org/paper/" + "c" * 40,
                "externalIds": {},
                "authors": [{"name": "Alex Example"}],
            }]}

    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)

    rows = collect_semantic_scholar_rows(manifest, SemanticScholarClient())

    assert rows[0]["citation_status"] == "OBSERVED"
    assert rows[0]["citation_count"] == "9"
    assert rows[0]["match_method"] == "TITLE_EXACT"


def test_semantic_scholar_rate_limit_aborts_without_returning_rows() -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)

    class RateLimitedClient:
        def post_json(self, *_args, **_kwargs):
            raise OpenCitationCollectionError(
                "The official API at api.semanticscholar.org remained unavailable with HTTP 429."
            )

    with pytest.raises(OpenCitationCollectionError, match=r"api\.semanticscholar\.org.*429"):
        collect_semantic_scholar_rows(manifest, RateLimitedClient())


def test_semantic_scholar_title_search_requires_the_applicant_family_name(
    monkeypatch,
) -> None:
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

    class SemanticScholarClient:
        def get_json(self, url: str, *, allow_not_found: bool = False):
            assert "/paper/search?" in url
            assert parse_qs(urlparse(url).query)["query"] == ["A fixture publication"]
            return {"data": [{
                "paperId": "b" * 40,
                "title": "A fixture publication",
                "year": 2025,
                "citationCount": 23,
                "url": "https://www.semanticscholar.org/paper/" + "b" * 40,
                "externalIds": {},
                "authors": [{"name": "Different Applicant"}],
            }]}

        def post_json(self, *_args, **_kwargs):
            raise AssertionError("A DOI-less work must use a paced title search.")

    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)

    rows = collect_semantic_scholar_rows(manifest, SemanticScholarClient())

    assert rows[0]["citation_status"] == "NOT_FOUND"
    assert rows[0]["match_method"] == "NO_CONFIDENT_MATCH"


def test_semantic_client_uses_its_own_api_key_without_openalex_authorization(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "openalex-key")
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "semantic-key")

    client = OfficialCitationApiClient(
        user_agent="fixture",
        source_code="SEMANTIC_SCHOLAR",
    )
    try:
        assert client._client.headers["x-api-key"] == "semantic-key"
        assert "Authorization" not in client._client.headers
    finally:
        client.close()


def test_cli_source_selection_writes_a_semantic_scholar_snapshot(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(FIXTURE.read_bytes())
    output_path = tmp_path.parent / "semantic-snapshot.csv"
    rows = ({
        "source_code": "SEMANTIC_SCHOLAR",
        "citation_status": "OBSERVED",
    },)

    class FakeClient:
        def __init__(self, *, user_agent: str, source_code: str) -> None:
            assert source_code == "SEMANTIC_SCHOLAR"

        def close(self) -> None:
            pass

    captured: dict[str, object] = {}
    monkeypatch.setattr(collector_command, "OfficialCitationApiClient", FakeClient)
    monkeypatch.setattr(
        collector_command,
        "collect_semantic_scholar_rows",
        lambda manifest, client, progress: rows,
    )
    monkeypatch.setattr(
        collector_command,
        "write_open_citation_snapshot",
        lambda output, received_rows: captured.update(output=output, rows=received_rows),
    )

    assert collector_command.main([
        "--manifest", str(manifest_path),
        "--output", str(output_path),
        "--expected-applicants", "1",
        "--expected-works", "1",
        "--expected-occurrences", "2",
        "--expected-citation-statuses", "3",
        "--source", "SEMANTIC_SCHOLAR",
    ]) == 0
    assert captured["rows"] == rows


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


def test_openalex_doi_requests_use_free_singleton_lookups_and_one_cutoff_timestamp(
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
            assert "/works/https%3A%2F%2Fdoi.org%2F10.1000%2Fexample" in url
            assert "filter=doi%3A" not in url
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

    monkeypatch.setenv("OPENALEX_API_KEY", "fixture-key")
    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)
    rows = collect_open_citation_rows(manifest, FakeClient())

    assert rows[0]["annual_citation_counts"] == '{"2010":3,"2025":16}'


def test_keyless_openalex_collection_preserves_total_without_paid_history_query(
    monkeypatch,
) -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)

    class FakeClient:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get_json(self, url: str, *, allow_not_found: bool = False):
            self.urls.append(url)
            return {
                "id": "https://openalex.org/W123",
                "title": "A fixture publication",
                "publication_year": 2010,
                "cited_by_count": 19,
                "doi": "https://doi.org/10.1000/example",
                "authorships": [{"author": {"display_name": "Alex Example"}}],
                "counts_by_year": [{"year": 2025, "cited_by_count": 16}],
            }

    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)
    client = FakeClient()

    rows = collect_open_citation_rows(manifest, client)

    assert rows[0]["citation_count"] == "19"
    assert rows[0]["annual_citation_counts"] == "{}"
    assert len(client.urls) == 1
    assert "group_by=publication_year" not in client.urls[0]


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


def test_openalex_collects_a_shared_journal_source_once_per_snapshot(
    monkeypatch,
) -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)
    manifest = replace(
        manifest,
        works=(
            manifest.works[0],
            replace(manifest.works[0], final_work_id="work-shares-journal"),
        ),
    )

    class JournalClient:
        def __init__(self) -> None:
            self.source_requests: list[str] = []

        def get_json(self, url: str, *, allow_not_found: bool = False):
            if "/sources/" in url:
                self.source_requests.append(url)
                return {
                    "id": "https://openalex.org/S123",
                    "display_name": "Example Journal",
                    "type": "journal",
                    "summary_stats": {"2yr_mean_citedness": 4.25},
                    "updated_date": "2026-09-20",
                }
            return {
                "results": [{
                    "id": "https://openalex.org/W123",
                    "title": "A fixture publication",
                    "publication_year": 2025,
                    "cited_by_count": 17,
                    "doi": "https://doi.org/10.1000/example",
                    "authorships": [{"author": {"display_name": "Alex Example"}}],
                    "counts_by_year": [{"year": 2025, "cited_by_count": 17}],
                    "primary_location": {
                        "source": {"id": "https://openalex.org/S123"},
                    },
                }],
            }

    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)
    client = JournalClient()

    rows = collect_open_citation_rows(manifest, client)

    assert client.source_requests == [
        "https://api.openalex.org/sources/S123?select=id%2Cdisplay_name%2Ctype%2Csummary_stats%2Cupdated_date"
    ]
    assert [row["journal_openalex_id"] for row in rows] == [
        "https://openalex.org/S123",
        "https://openalex.org/S123",
    ]
    assert [row["journal_two_year_mean_citedness"] for row in rows] == ["4.25", "4.25"]


@pytest.mark.parametrize(
    ("source", "metric"),
    [
        ({"id": "https://openalex.org/S123", "type": "repository"}, 4.25),
        ({"id": "https://openalex.org/S123", "type": "journal"}, None),
        ({"id": "https://openalex.org/S123", "type": "journal"}, -1),
        ({"id": "https://openalex.org/S123", "type": "journal"}, "3.2"),
        ({"id": "https://openalex.org/S123", "type": "journal"}, float("nan")),
        ({"id": "https://openalex.org/S123", "type": "journal"}, float("inf")),
        (None, 4.25),
    ],
)
def test_openalex_keeps_matches_when_the_primary_source_cannot_supply_a_valid_journal_metric(
    monkeypatch,
    source,
    metric,
) -> None:
    manifest = load_publication_manifest(FIXTURE.read_bytes(), expected=FIXTURE_COUNTS)

    class JournalClient:
        def get_json(self, url: str, *, allow_not_found: bool = False):
            if "/sources/" in url:
                return {
                    "id": "https://openalex.org/S123",
                    "display_name": "Example source",
                    "type": source["type"] if source else "journal",
                    "summary_stats": {"2yr_mean_citedness": metric},
                    "updated_date": "2026-09-20",
                }
            candidate = {
                "id": "https://openalex.org/W123",
                "title": "A fixture publication",
                "publication_year": 2025,
                "cited_by_count": 17,
                "doi": "https://doi.org/10.1000/example",
                "authorships": [{"author": {"display_name": "Alex Example"}}],
                "counts_by_year": [{"year": 2025, "cited_by_count": 17}],
                "primary_location": {"source": source},
            }
            return {"results": [candidate]}

    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setattr("app.importer.open_citation_collector.time.sleep", lambda _: None)

    row = collect_open_citation_rows(manifest, JournalClient())[0]

    assert row["citation_status"] == "OBSERVED"
    assert row["journal_two_year_mean_citedness"] == ""


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


def test_openalex_rejects_an_exact_doi_when_the_authoritative_title_conflicts() -> None:
    """Break caught: a mistyped source DOI could attach another paper's citations."""
    work, raw = _work()

    match = match_openalex_candidate(
        work,
        raw,
        {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1000/example",
            "title": "A wholly unrelated publication",
            "publication_year": 2025,
            "cited_by_count": 19,
            "authorships": [{"author": {"display_name": "Alex Example"}}],
        },
    )

    assert match is None


@pytest.mark.parametrize(
    ("stored_title", "openalex_title"),
    (
        (
            "The secretome triggers intracellular Ca<sup>2+</sup> oscillations",
            "The secretome triggers intracellular Ca2+ oscillations",
        ),
        (
            "Interactions Using<i>In Vivo</i>Imaging Flow Cytometry",
            "Interactions UsingIn VivoImaging Flow Cytometry",
        ),
    ),
)
def test_openalex_exact_doi_accepts_equivalent_inline_markup_titles(
    stored_title: str, openalex_title: str
) -> None:
    """Break caught: publisher inline tags caused real DOI matches to fail closed."""
    work, raw = _work()
    work = replace(
        work,
        canonical_metadata=replace(work.canonical_metadata, title=stored_title),
    )

    match = match_openalex_candidate(
        work,
        raw,
        {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1000/example",
            "title": openalex_title,
            "publication_year": 2025,
            "cited_by_count": 19,
            "authorships": [{"author": {"display_name": "Alex Example"}}],
        },
    )

    assert match is not None
    assert match.match_method == "DOI_EXACT"


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
