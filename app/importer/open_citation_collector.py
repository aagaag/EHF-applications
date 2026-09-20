"""Collect citation counts from the official Semantic Scholar API."""

from __future__ import annotations

import html
import csv
import json
import os
import re
import tempfile
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx

from app.importer.open_citations import OPEN_CITATION_FIELDS
from app.importer.publications import PublicationManifest
from app.importer.publications import PublicationWork, normalize_doi


_TAG_RE = re.compile(r"<[^>]+>")
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")
_MAX_REQUEST_ATTEMPTS = 20
_REQUEST_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class CitationApiMatch:
    source_identifier: str
    result_url: str
    matched_doi: str
    matched_title: str
    matched_authors: str
    matched_year: int | None
    citation_count: int
    match_method: str
    annual_citation_counts: dict[str, int]


class OpenCitationCollectionError(RuntimeError):
    """An official API could not be queried or returned an unsafe response."""


class OfficialCitationApiClient:
    """Small retrying client for official citation APIs."""

    def __init__(self, *, user_agent: str, timeout_seconds: float = 30.0) -> None:
        headers = {"User-Agent": user_agent, "Accept": "application/json"}
        api_key = os.environ.get("OPENALEX_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers=headers,
        )

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        url: str,
        *,
        allow_not_found: bool = False,
        **kwargs: Any,
    ) -> Any | None:
        for attempt in range(_MAX_REQUEST_ATTEMPTS):
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.HTTPError as error:
                if attempt == _MAX_REQUEST_ATTEMPTS - 1:
                    raise OpenCitationCollectionError(
                        "An official citation API request failed."
                    ) from error
                time.sleep(min(2**attempt, 20))
                continue
            if response.status_code == 404:
                if allow_not_found:
                    return None
                host = urlparse(url).hostname or "unknown host"
                raise OpenCitationCollectionError(
                    f"The official API at {host} returned unexpected HTTP 404."
                )
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt == _MAX_REQUEST_ATTEMPTS - 1:
                    host = urlparse(url).hostname or "unknown host"
                    raise OpenCitationCollectionError(
                        f"The official API at {host} remained unavailable with "
                        f"HTTP {response.status_code}."
                    )
                retry_after = response.headers.get("Retry-After", "")
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = float(2**attempt)
                time.sleep(min(max(delay, 1.0), 30.0))
                continue
            try:
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as error:
                host = urlparse(url).hostname or "unknown host"
                raise OpenCitationCollectionError(
                    f"The official API at {host} returned invalid HTTP/JSON "
                    f"response status {response.status_code}."
                ) from error
        raise AssertionError("unreachable")

    def get_json(self, url: str, *, allow_not_found: bool = False) -> Any | None:
        return self._request("GET", url, allow_not_found=allow_not_found)

    def post_json(self, url: str, payload: dict[str, Any]) -> Any | None:
        return self._request("POST", url, json=payload)


def _normalized_text(value: str) -> str:
    value = _TAG_RE.sub(" ", html.unescape(value))
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(_NON_WORD_RE.sub(" ", value.lower()).split())


def _applicant_family_token(work: PublicationWork) -> str:
    normalized = _normalized_text(work.workbook_applicant)
    return normalized.split()[-1] if normalized else ""


def _match_method(
    work: PublicationWork,
    raw_citation: str,
    *,
    candidate_doi: str,
    candidate_title: str,
    candidate_year: int | None,
    candidate_authors: list[str],
) -> str | None:
    expected_doi = work.canonical_metadata.doi or ""
    if expected_doi and candidate_doi == expected_doi:
        return "DOI_EXACT"
    normalized_title = _normalized_text(candidate_title)
    expected_title = _normalized_text(work.canonical_metadata.title or "")
    compatible_year = (
        work.canonical_metadata.year is None
        or candidate_year is None
        or work.canonical_metadata.year == candidate_year
    )
    author_tokens = {
        token
        for author in candidate_authors
        for token in _normalized_text(author).split()
    }
    family_token = _applicant_family_token(work)
    applicant_is_author = bool(family_token and family_token in author_tokens)
    if (
        expected_title
        and normalized_title == expected_title
        and compatible_year
        and applicant_is_author
    ):
        return "TITLE_EXACT"
    normalized_raw = _normalized_text(raw_citation)
    if (
        len(normalized_title) >= 20
        and normalized_title in normalized_raw
        and applicant_is_author
    ):
        return "RAW_CITATION_EXACT"
    return None


def _count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _annual_citation_counts(candidate: dict[str, Any]) -> dict[str, int]:
    """Extract OpenAlex counts_by_year, failing closed on malformed values."""

    values = candidate.get("counts_by_year") or ()
    if not isinstance(values, list):
        return {}
    counts: dict[str, int] = {}
    for item in values:
        if not isinstance(item, dict):
            continue
        year = item.get("year")
        count = _count(item.get("cited_by_count"))
        if isinstance(year, int) and 1900 <= year <= 2200 and count is not None:
            counts[str(year)] = count
    return dict(sorted(counts.items()))


def match_openalex_candidate(
    work: PublicationWork,
    raw_citation: str,
    candidate: dict[str, Any],
) -> CitationApiMatch | None:
    title = str(candidate.get("title") or "").strip()
    identifier = str(candidate.get("id") or "").strip()
    doi_value = str(candidate.get("doi") or "").strip()
    doi = normalize_doi(doi_value) if doi_value else ""
    year_value = candidate.get("publication_year")
    year = int(year_value) if isinstance(year_value, int) else None
    authors = [
        str((item.get("author") or {}).get("display_name") or "")
        for item in candidate.get("authorships") or []
        if isinstance(item, dict)
    ]
    count = _count(candidate.get("cited_by_count"))
    method = _match_method(
        work,
        raw_citation,
        candidate_doi=doi,
        candidate_title=title,
        candidate_year=year,
        candidate_authors=authors,
    )
    if (
        method is None
        or count is None
        or not identifier.startswith("https://openalex.org/")
        or not title
    ):
        return None
    return CitationApiMatch(
        identifier,
        identifier,
        doi,
        title,
        "; ".join(author for author in authors if author),
        year,
        count,
        method,
        _annual_citation_counts(candidate),
    )


def match_semantic_scholar_candidate(
    work: PublicationWork,
    raw_citation: str,
    candidate: dict[str, Any],
) -> CitationApiMatch | None:
    identifier = str(candidate.get("paperId") or "").strip()
    title = str(candidate.get("title") or "").strip()
    url = str(candidate.get("url") or "").strip()
    external_ids = candidate.get("externalIds") or {}
    doi_value = str(external_ids.get("DOI") or "") if isinstance(external_ids, dict) else ""
    doi = normalize_doi(doi_value) if doi_value else ""
    year_value = candidate.get("year")
    year = int(year_value) if isinstance(year_value, int) else None
    authors = [
        str(item.get("name") or "").strip()
        for item in candidate.get("authors") or []
        if isinstance(item, dict)
    ]
    authors = [author for author in authors if author]
    count = _count(candidate.get("citationCount"))
    method = _match_method(
        work,
        raw_citation,
        candidate_doi=doi,
        candidate_title=title,
        candidate_year=year,
        candidate_authors=authors,
    )
    if (
        method is None
        or count is None
        or not identifier
        or not url.startswith("https://www.semanticscholar.org/")
        or not title
        or not authors
    ):
        return None
    return CitationApiMatch(
        identifier,
        url,
        doi,
        title,
        "; ".join(authors),
        year,
        count,
        method,
        {},
    )


def _raw_citations(manifest: PublicationManifest) -> dict[str, str]:
    values: dict[str, list[str]] = {}
    for occurrence in manifest.source_occurrences:
        values.setdefault(occurrence.final_work_id, []).append(
            occurrence.normalized_raw_citation
        )
    return {work_id: " ".join(parts) for work_id, parts in values.items()}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _openalex_query(work: PublicationWork, raw_citation: str) -> str:
    doi = work.canonical_metadata.doi
    if doi:
        return "https://api.openalex.org/works/" + quote(
            f"https://doi.org/{doi}", safe=""
        )
    query = _normalized_text(work.canonical_metadata.title or raw_citation)[:300]
    if not query:
        query = "publication"
    return "https://api.openalex.org/works?" + urlencode(
        {"search": query, "per_page": 5}
    )


def _openalex_full_history_url(source_identifier: str) -> str:
    work_id = source_identifier.rsplit("/", 1)[-1]
    return "https://api.openalex.org/works?" + urlencode(
        {
            "filter": f"cites:{work_id}",
            "group_by": "publication_year",
            "per_page": 200,
        }
    )


def _full_citation_history(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("group_by"), list):
        raise OpenCitationCollectionError(
            "OpenAlex returned an unexpected citation-history response shape."
        )
    counts: dict[str, int] = {}
    for group in payload["group_by"]:
        if not isinstance(group, dict):
            continue
        key = str(group.get("key") or "")
        count = _count(group.get("count"))
        if key.isdigit() and 1600 <= int(key) <= 2200 and count is not None:
            counts[key] = count
    return dict(sorted(counts.items()))


def build_openalex_doi_batch_urls(
    dois: Sequence[str],
) -> tuple[tuple[tuple[str, ...], str], ...]:
    """Build OpenAlex OR-filter batches at its documented 100-value limit."""

    unique_dois = tuple(dict.fromkeys(normalize_doi(doi) for doi in dois))
    batches: list[tuple[tuple[str, ...], str]] = []
    for start in range(0, len(unique_dois), 100):
        batch = unique_dois[start : start + 100]
        url = "https://api.openalex.org/works?" + urlencode(
            {
                "filter": "doi:" + "|".join(batch),
                "per_page": 100,
                "select": (
                    "id,doi,title,publication_year,cited_by_count,authorships"
                    ",counts_by_year"
                ),
            }
        )
        batches.append((batch, url))
    return tuple(batches)


def _semantic_search_url(title: str) -> str:
    return "https://api.semanticscholar.org/graph/v1/paper/search/bulk?" + urlencode(
        {
            "query": title,
            "fields": "paperId,title,year,citationCount,url,externalIds,authors",
        }
    )


def _row(
    work: PublicationWork,
    source_code: str,
    observed_at_utc: str,
    reviewer: str,
    query_url: str,
    match: CitationApiMatch | None,
) -> dict[str, str]:
    metadata = work.canonical_metadata
    return {
        "applicant": work.workbook_applicant,
        "final_work_id": work.final_work_id,
        "doi": metadata.doi or "",
        "title": metadata.title or "",
        "year": "" if metadata.year is None else str(metadata.year),
        "source_code": source_code,
        "citation_status": "NOT_FOUND" if match is None else "OBSERVED",
        "citation_count": "" if match is None else str(match.citation_count),
        "source_identifier": "" if match is None else match.source_identifier,
        "result_url": query_url if match is None else match.result_url,
        "matched_doi": "" if match is None else match.matched_doi,
        "matched_title": "" if match is None else match.matched_title,
        "matched_authors": "" if match is None else match.matched_authors,
        "observed_at_utc": observed_at_utc,
        "reviewer": reviewer,
        "match_method": "NO_CONFIDENT_MATCH" if match is None else match.match_method,
        "annual_citation_counts": "{}" if match is None else json.dumps(
            match.annual_citation_counts, separators=(",", ":"), sort_keys=True
        ),
    }


def collect_open_citation_rows(
    manifest: PublicationManifest,
    client: OfficialCitationApiClient,
    *,
    reviewer: str = "EHF OpenAlex cutoff collector 2026.6",
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[dict[str, str], ...]:
    """Collect OpenAlex rows, failing closed on API access errors."""

    raw_by_work = _raw_citations(manifest)
    total = len(manifest.works)
    rows: list[dict[str, str]] = []
    observed_at = _utc_now()
    batch_matches: dict[str, tuple[str, dict[str, Any]]] = {}
    doi_batches = build_openalex_doi_batch_urls(
        tuple(work.canonical_metadata.doi for work in manifest.works if work.canonical_metadata.doi)
    )
    for _dois, batch_url in doi_batches:
        payload = client.get_json(batch_url)
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise OpenCitationCollectionError(
                "OpenAlex returned an unexpected DOI batch response shape."
            )
        for candidate in payload["results"]:
            if not isinstance(candidate, dict):
                continue
            candidate_doi = normalize_doi(str(candidate.get("doi") or ""))
            if candidate_doi:
                batch_matches[candidate_doi] = (batch_url, candidate)
        time.sleep(_REQUEST_INTERVAL_SECONDS)
    for index, work in enumerate(manifest.works, start=1):
        raw_citation = raw_by_work.get(work.final_work_id, "")
        doi = work.canonical_metadata.doi or ""
        batch_match = batch_matches.get(doi) if doi else None
        query_url = batch_match[0] if batch_match else _openalex_query(work, raw_citation)
        candidate = batch_match[1] if batch_match else None
        match = (
            match_openalex_candidate(work, raw_citation, candidate)
            if candidate is not None
            else None
        )
        if match is None:
            payload = client.get_json(query_url if not batch_match else _openalex_query(work, raw_citation), allow_not_found=bool(doi))
            candidates = () if payload is None else (payload.get("results", ()) if isinstance(payload, dict) and "results" in payload else (payload,))
            match = next((matched for item in candidates if isinstance(item, dict) for matched in (match_openalex_candidate(work, raw_citation, item),) if matched is not None), None)
            if batch_match:
                query_url = _openalex_query(work, raw_citation)
            time.sleep(_REQUEST_INTERVAL_SECONDS)
        if (
            match is not None
            and sum(match.annual_citation_counts.values()) < match.citation_count
        ):
            history_url = _openalex_full_history_url(match.source_identifier)
            history = _full_citation_history(client.get_json(history_url))
            if not history and match.citation_count:
                raise OpenCitationCollectionError(
                    "OpenAlex omitted the full citation history for a cited work."
                )
            match = replace(match, annual_citation_counts=history)
            time.sleep(_REQUEST_INTERVAL_SECONDS)
        rows.append(_row(work, "OPENALEX", observed_at, reviewer, query_url, match))
        if progress is not None:
            progress(index, total, "OPENALEX")
    return tuple(rows)


def write_open_citation_snapshot(path: Path, rows: Sequence[dict[str, str]]) -> None:
    """Write a complete private snapshot atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=OPEN_CITATION_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    data = output.getvalue().encode("utf-8-sig")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()
