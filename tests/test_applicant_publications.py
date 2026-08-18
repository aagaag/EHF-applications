from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request
from urllib.parse import unquote, urlparse
from uuid import UUID

import pytest

from app.applicant.publications import (
    CrossrefPublicationLookup,
    InvalidDoi,
    PublicationLookupReceipts,
    PublicationLookupUnavailable,
    PublicationNotFound,
    _default_transport,
    normalize_doi,
)


APPLICATION = UUID("72000000-0000-4000-8000-000000000001")


def _crossref_payload(doi: str = "10.1000/example") -> bytes:
    return json.dumps(
        {
            "status": "ok",
            "message": {
                "DOI": doi,
                "title": ["A synthetic publication"],
                "author": [
                    {"given": "Ada", "family": "Lovelace"},
                    {"family": "Curie"},
                ],
                "container-title": ["Synthetic Journal"],
                "published": {"date-parts": [[2025, 7, 4]]},
                "type": "journal-article",
                "URL": f"https://doi.org/{doi}",
            },
        }
    ).encode("utf-8")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.1000/ABC.123", "10.1000/abc.123"),
        (" https://doi.org/10.1000/ABC.123 ", "10.1000/abc.123"),
        ("doi:10.1000/ABC.123", "10.1000/abc.123"),
    ],
)
def test_normalize_doi_accepts_common_forms(raw: str, expected: str) -> None:
    assert normalize_doi(raw) == expected


@pytest.mark.parametrize("raw", ["", "not-a-doi", "10.1/x", "10.1000/white space"])
def test_normalize_doi_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(InvalidDoi):
        normalize_doi(raw)


def test_crossref_lookup_uses_fixed_host_and_maps_canonical_metadata() -> None:
    seen: list[tuple[Request, float, int]] = []

    def transport(request: Request, timeout: float, maximum: int) -> tuple[int, bytes]:
        seen.append((request, timeout, maximum))
        return 200, _crossref_payload()

    service = CrossrefPublicationLookup(transport=transport, timeout_seconds=3.0)

    result = service.lookup("https://doi.org/10.1000/EXAMPLE")

    assert result == {
        "doi": "10.1000/example",
        "title": "A synthetic publication",
        "authors": ["Ada Lovelace", "Curie"],
        "journal": "Synthetic Journal",
        "publicationDate": "2025-07-04",
        "type": "journal-article",
        "url": "https://doi.org/10.1000/example",
    }
    request, timeout, maximum = seen[0]
    assert request.full_url.startswith(
        "https://api.crossref.org/works/10.1000%2Fexample?mailto="
    )
    assert "adriano.aguzzi%40isab.science" in request.full_url
    assert request.host == "api.crossref.org"
    assert request.get_header("User-agent").startswith("EHF-Applications/")
    assert timeout == 3.0
    assert maximum == 1_000_000


def test_crossref_lookup_caches_success_without_an_unbounded_keyspace() -> None:
    calls: list[str] = []

    def transport(request: Request, _timeout: float, _maximum: int) -> tuple[int, bytes]:
        calls.append(request.full_url)
        doi = "10.1000/one" if "one" in request.full_url else "10.1000/two"
        return 200, _crossref_payload(doi)

    service = CrossrefPublicationLookup(transport=transport, cache_size=1)
    service.lookup("10.1000/one")
    service.lookup("10.1000/one")
    service.lookup("10.1000/two")
    service.lookup("10.1000/one")

    assert len(calls) == 3


def test_crossref_cache_is_safe_under_concurrent_lookup_and_eviction() -> None:
    def transport(request: Request, _timeout: float, _maximum: int) -> tuple[int, bytes]:
        doi = unquote(urlparse(request.full_url).path.rsplit("/", 1)[-1])
        return 200, _crossref_payload(doi)

    service = CrossrefPublicationLookup(transport=transport, cache_size=2)
    dois = [f"10.1000/concurrent-{index % 7}" for index in range(140)]

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(service.lookup, dois))

    assert [result["doi"] for result in results] == dois


@pytest.mark.parametrize(
    ("status", "payload", "exception"),
    [
        (404, b"{}", PublicationNotFound),
        (429, b"{}", PublicationLookupUnavailable),
        (500, b"{}", PublicationLookupUnavailable),
        (200, b"not json", PublicationLookupUnavailable),
        (200, b'{"status":"ok","message":{"DOI":"10.1000/example"}}', PublicationLookupUnavailable),
        (200, b'{"message":{"DOI":"10.1000/example","title":["Title"],"published":null}}', PublicationLookupUnavailable),
        (200, b'{"message":{"DOI":"10.1000/example","title":"Title","published":{"date-parts":[[2025]]}}}', PublicationLookupUnavailable),
        (200, b'{"message":{"DOI":"10.1000/example","title":["Title"],"container-title":"Journal","published":{"date-parts":[[2025]]}}}', PublicationLookupUnavailable),
        (200, b'{"message":{"DOI":"10.1000/example","title":["Title"],"published":{"date-parts":[[2025,2,31]]}}}', PublicationLookupUnavailable),
    ],
)
def test_crossref_lookup_sanitizes_provider_failures(
    status: int, payload: bytes, exception: type[Exception]
) -> None:
    service = CrossrefPublicationLookup(
        transport=lambda _request, _timeout, _maximum: (status, payload)
    )

    with pytest.raises(exception):
        service.lookup("10.1000/example")


def test_default_transport_does_not_follow_provider_redirects() -> None:
    visited: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - standard-library callback name
            visited.append(self.path)
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/target")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"followed")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _payload = _default_transport(
            Request(f"http://127.0.0.1:{server.server_port}/redirect"), 2.0, 1_000
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert status == 302
    assert visited == ["/redirect"]


def test_lookup_receipt_is_bound_to_the_application_and_normalized_doi() -> None:
    receipts = PublicationLookupReceipts(b"synthetic-publication-receipt-secret-at-least-32-bytes")

    receipt = receipts.issue(APPLICATION, "https://doi.org/10.1000/EXAMPLE")

    assert receipts.valid(APPLICATION, "10.1000/example", receipt) is True
    assert receipts.valid(
        UUID("72000000-0000-4000-8000-000000000002"),
        "10.1000/example",
        receipt,
    ) is False
    assert receipts.valid(APPLICATION, "10.1000/other", receipt) is False
    assert receipts.valid(APPLICATION, "10.1000/example", "not-a-receipt") is False
