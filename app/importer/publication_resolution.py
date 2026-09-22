"""Public bibliographic validation for locally extracted citation candidates."""

from __future__ import annotations

import hashlib
import html
import json
import unicodedata
from pathlib import Path
from typing import Any

import httpx

from app.importer.publication_extraction import ParsedPublication, PublicationCandidate


def _normalize(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", (value or "").casefold())
    return "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character) and character.isalnum()
    )


def _first_year(item: dict[str, Any]) -> int | None:
    for name in ("published-print", "published-online", "published", "issued"):
        parts = (item.get(name) or {}).get("date-parts") or []
        if parts and parts[0] and isinstance(parts[0][0], int):
            return parts[0][0]
    return None


class CrossrefBibliographicResolver:
    """Resolve only results whose canonical title occurs in the submitted citation."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        cache_path: Path | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": "EHF-publication-audit/1.0 (https://isab.science)"
            },
        )
        self._cache_path = cache_path
        self._cache: dict[str, list[dict[str, Any]]] = {}
        if cache_path is not None and cache_path.exists():
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self._cache = loaded

    def _items(self, raw_citation: str) -> list[dict[str, Any]]:
        key = hashlib.sha256(raw_citation.encode("utf-8")).hexdigest()
        if key in self._cache:
            return self._cache[key]
        response = self._client.get(
            "https://api.crossref.org/works",
            params={
                "query.bibliographic": raw_citation[:2000],
                "rows": "5",
                "select": (
                    "DOI,title,author,container-title,published,published-print,"
                    "published-online,issued,volume,page,URL,score"
                ),
            },
        )
        response.raise_for_status()
        items = (response.json().get("message") or {}).get("items") or []
        self._cache[key] = items
        if self._cache_path is not None:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self._cache_path)
        return items

    def resolve(
        self,
        candidate: PublicationCandidate,
        fallback: ParsedPublication,
    ) -> ParsedPublication | None:
        items = self._items(candidate.raw_citation)
        raw_key = _normalize(candidate.raw_citation)
        matches: list[tuple[float, dict[str, Any], str, int | None]] = []
        for item in items:
            titles = item.get("title") or []
            title = html.unescape(str(titles[0])).strip() if titles else ""
            title_key = _normalize(title)
            year = _first_year(item)
            year_compatible = (
                fallback.year is None
                or fallback.year < 2000
                or year is None
                or abs(fallback.year - year) <= 2
            )
            if len(title_key) >= 16 and title_key in raw_key and year_compatible:
                matches.append((float(item.get("score") or 0.0), item, title, year))
        unique_titles = {_normalize(title) for _score, _item, title, _year in matches}
        if len(unique_titles) != 1:
            return None
        matches.sort(key=lambda value: value[0], reverse=True)
        _score, item, title, year = matches[0]
        doi = str(item.get("DOI") or "").strip().casefold()
        if not doi:
            return None
        authors = []
        for author in item.get("author") or []:
            name = " ".join(
                part.strip()
                for part in (str(author.get("given") or ""), str(author.get("family") or ""))
                if part.strip()
            )
            if name:
                authors.append(name)
        containers = item.get("container-title") or []
        journal = html.unescape(str(containers[0])).strip() if containers else None
        return ParsedPublication(
            authors=tuple(authors) or fallback.authors,
            title=title,
            journal=journal or fallback.journal,
            volume=str(item["volume"]) if item.get("volume") else fallback.volume,
            issue=fallback.issue,
            pages=str(item["page"]) if item.get("page") else fallback.pages,
            year=year or fallback.year,
            doi=doi,
            url=str(item.get("URL") or f"https://doi.org/{doi}"),
            raw_citation=candidate.raw_citation,
            parser_method="crossref-bibliographic",
            field_evidence=("authors", "title", "journal", "year", "doi"),
        )
