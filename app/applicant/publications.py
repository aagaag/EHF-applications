"""Bounded, fixed-host Crossref metadata lookup for applicant-entered DOIs."""

from __future__ import annotations

import json
import base64
import hmac
import re
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID


_DOI = re.compile(r"10\.\d{4,9}/\S+\Z", re.IGNORECASE)
_CROSSREF_BASE = "https://api.crossref.org/works/"
_CONTACT = "adriano.aguzzi@isab.science"
_USER_AGENT = "EHF-Applications/1.0 (mailto:adriano.aguzzi@isab.science)"
Transport = Callable[[Request, float, int], tuple[int, bytes]]


class PublicationLookup(Protocol):
    def lookup(self, raw_doi: object) -> dict[str, Any]: ...


class InvalidDoi(ValueError):
    """The applicant value is not a syntactically valid DOI."""


class PublicationNotFound(LookupError):
    """Crossref has no work for the requested DOI."""


class PublicationLookupUnavailable(RuntimeError):
    """Crossref could not provide safe, usable metadata."""


class PublicationLookupReceipts:
    """Issue unforgeable proof that Crossref resolved a DOI for one application."""

    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("publication lookup receipt secret is too short")
        self._key = hmac.digest(
            secret, b"EHF applicant publication lookup receipts v1", "sha256"
        )

    def issue(self, application_id: UUID, raw_doi: object) -> str:
        doi = normalize_doi(raw_doi)
        digest = hmac.digest(self._key, self._payload(application_id, doi), "sha256")
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def valid(self, application_id: UUID, raw_doi: object, receipt: object) -> bool:
        if not isinstance(receipt, str) or len(receipt) != 43:
            return False
        try:
            expected = self.issue(application_id, raw_doi)
        except InvalidDoi:
            return False
        return hmac.compare_digest(expected, receipt)

    @staticmethod
    def _payload(application_id: UUID, doi: str) -> bytes:
        return application_id.bytes + b"\x00" + doi.encode("utf-8")


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def normalize_doi(raw: object) -> str:
    if not isinstance(raw, str):
        raise InvalidDoi("Enter a valid DOI.")
    value = raw.strip()
    lowered = value.casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if lowered.startswith(prefix):
            value = value[len(prefix):].strip()
            break
    value = value.casefold()
    if len(value) > 255 or _DOI.fullmatch(value) is None:
        raise InvalidDoi("Enter a valid DOI.")
    return value


class CrossrefPublicationLookup:
    """Resolve canonical display metadata without trusting caller-supplied URLs."""

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        timeout_seconds: float = 5.0,
        maximum_response_bytes: int = 1_000_000,
        cache_size: int = 256,
    ) -> None:
        if not 0 < timeout_seconds <= 15:
            raise ValueError("lookup timeout must be between zero and fifteen seconds")
        if not 1 <= maximum_response_bytes <= 2_000_000:
            raise ValueError("lookup response bound is invalid")
        if not 1 <= cache_size <= 2_048:
            raise ValueError("lookup cache bound is invalid")
        self._transport = transport or _default_transport
        self._timeout = timeout_seconds
        self._maximum = maximum_response_bytes
        self._cache_size = cache_size
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._cache_lock = threading.Lock()

    def lookup(self, raw_doi: object) -> dict[str, Any]:
        doi = normalize_doi(raw_doi)
        with self._cache_lock:
            cached = self._cache.get(doi)
            if cached is not None:
                self._cache.move_to_end(doi)
                return _copy_metadata(cached)
        query = urlencode({"mailto": _CONTACT})
        request = Request(
            f"{_CROSSREF_BASE}{quote(doi, safe='')}?{query}",
            headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
        )
        try:
            status, payload = self._transport(request, self._timeout, self._maximum)
        except PublicationLookupUnavailable:
            raise
        except (OSError, TimeoutError, URLError):
            raise PublicationLookupUnavailable("Publication lookup is temporarily unavailable.") from None
        if status == 404:
            raise PublicationNotFound("No publication was found for this DOI.")
        if status != 200 or len(payload) > self._maximum:
            raise PublicationLookupUnavailable("Publication lookup is temporarily unavailable.")
        metadata = _metadata(payload, doi)
        with self._cache_lock:
            self._cache[doi] = metadata
            self._cache.move_to_end(doi)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return _copy_metadata(metadata)


def _default_transport(
    request: Request, timeout_seconds: float, maximum_response_bytes: int
) -> tuple[int, bytes]:
    try:
        with build_opener(_RejectRedirects()).open(
            request, timeout=timeout_seconds
        ) as response:
            return int(response.status), response.read(maximum_response_bytes + 1)
    except HTTPError as error:
        return int(error.code), error.read(maximum_response_bytes + 1)
    except (OSError, TimeoutError, URLError):
        raise PublicationLookupUnavailable("Publication lookup is temporarily unavailable.") from None


def _metadata(payload: bytes, requested_doi: str) -> dict[str, Any]:
    try:
        root = json.loads(payload.decode("utf-8"))
        message = root["message"]
        if not isinstance(message, dict):
            raise ValueError
        response_doi = normalize_doi(message["DOI"])
        titles = message["title"]
        if not isinstance(titles, list) or not titles:
            raise ValueError
        title = _bounded_text(titles[0], 1_000)
        if response_doi != requested_doi or not title:
            raise ValueError
        raw_authors = message.get("author", [])
        if not isinstance(raw_authors, list):
            raise ValueError
        authors = []
        for author in raw_authors[:100]:
            if not isinstance(author, dict):
                raise ValueError
            name = " ".join(
                part for part in (
                    _bounded_text(author.get("given", ""), 200),
                    _bounded_text(author.get("family", ""), 200),
                ) if part
            )
            if name:
                authors.append(name)
        containers = message.get("container-title") or []
        if not isinstance(containers, list):
            raise ValueError
        journal = _bounded_text(containers[0], 500) if containers else ""
        published = message.get("published")
        if not isinstance(published, dict):
            raise ValueError
        date_parts_rows = published.get("date-parts")
        if not isinstance(date_parts_rows, list) or not date_parts_rows:
            raise ValueError
        date_parts = date_parts_rows[0]
        publication_date = _publication_date(date_parts)
        work_type = _bounded_text(message.get("type", ""), 100)
    except (InvalidDoi, KeyError, TypeError, ValueError, IndexError, UnicodeError, json.JSONDecodeError):
        raise PublicationLookupUnavailable("Publication metadata is unavailable for this DOI.") from None
    return {
        "doi": requested_doi,
        "title": title,
        "authors": authors,
        "journal": journal,
        "publicationDate": publication_date,
        "type": work_type,
        "url": f"https://doi.org/{quote(requested_doi, safe='/')}",
    }


def _bounded_text(value: object, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError
    normalized = " ".join(value.split())
    if len(normalized) > maximum:
        raise ValueError
    return normalized


def _publication_date(parts: object) -> str:
    if not isinstance(parts, list) or not 1 <= len(parts) <= 3:
        return ""
    values = [int(part) for part in parts]
    if values[0] < 1000 or values[0] > 9999:
        raise ValueError
    if len(values) == 1:
        return f"{values[0]:04d}"
    if not 1 <= values[1] <= 12:
        raise ValueError
    if len(values) == 2:
        return f"{values[0]:04d}-{values[1]:02d}"
    if not 1 <= values[2] <= 31:
        raise ValueError
    date(values[0], values[1], values[2])
    return f"{values[0]:04d}-{values[1]:02d}-{values[2]:02d}"


def _copy_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {**metadata, "authors": list(metadata["authors"])}
