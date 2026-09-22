"""Public bibliographic validation of locally extracted citation strings."""

from __future__ import annotations

import httpx

from app.importer.publication_extraction import ParsedPublication, PublicationCandidate
from app.importer.publication_resolution import CrossrefBibliographicResolver


def _candidate(raw: str, year: int | None = 2026) -> PublicationCandidate:
    return PublicationCandidate(
        applicant_name="Aritra Chowdhury",
        filename="publications.pdf",
        page_start=1,
        page_end=1,
        line_start=1,
        line_end=3,
        section_label="PUBLICATIONS",
        status_hint="PUBLISHED",
        raw_citation=raw,
        normalized_citation=" ".join(raw.casefold().split()),
        year=year,
        segmentation_method="test",
    )


def test_crossref_resolver_accepts_canonical_title_contained_in_raw_citation() -> None:
    """Break caught: initial-heavy author formatting prevented canonical field recovery."""
    raw = (
        "Linker histone H1.0 loads onto nucleosomes through multiple pathways that are "
        "facilitated by histone chaperones E. Akbari, N. L. Burge, A. Chowdhury, "
        "Mol Cell, accepted (2026)"
    )
    payload = {
        "message": {
            "items": [
                {
                    "DOI": "10.1016/J.MOLCEL.2025.01.001",
                    "title": [
                        "Linker histone H1.0 loads onto nucleosomes through multiple pathways that are facilitated by histone chaperones"
                    ],
                    "author": [
                        {"given": "Ehsan", "family": "Akbari"},
                        {"given": "Aritra", "family": "Chowdhury"},
                    ],
                    "container-title": ["Molecular Cell"],
                    "published-online": {"date-parts": [[2025, 2, 27]]},
                    "volume": "85",
                    "page": "100-110",
                    "score": 135.0,
                }
            ]
        }
    }

    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    resolver = CrossrefBibliographicResolver(
        client=httpx.Client(transport=httpx.MockTransport(handle))
    )
    fallback = ParsedPublication(
        authors=("Akbari, E",),
        title="Akbari, N",
        journal="L",
        year=2026,
        raw_citation=raw,
    )

    resolved = resolver.resolve(_candidate(raw), fallback)

    assert resolved is not None
    assert resolved.doi == "10.1016/j.molcel.2025.01.001"
    assert resolved.title.startswith("Linker histone H1.0")
    assert resolved.authors == ("Ehsan Akbari", "Aritra Chowdhury")
    assert resolved.journal == "Molecular Cell"
    assert resolved.year == 2025
    assert resolved.parser_method == "crossref-bibliographic"


def test_crossref_resolver_rejects_results_whose_title_is_not_in_source() -> None:
    """Break caught: a high-ranked unrelated search hit became an applicant publication."""
    payload = {
        "message": {
            "items": [
                {
                    "DOI": "10.1000/unrelated",
                    "title": ["An unrelated publication about another topic"],
                    "author": [{"given": "Other", "family": "Person"}],
                    "container-title": ["Other Journal"],
                    "published": {"date-parts": [[2026]]},
                    "score": 200.0,
                }
            ]
        }
    }

    resolver = CrossrefBibliographicResolver(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
        )
    )
    raw = "Aritra Chowdhury received a fellowship in 2026."

    assert resolver.resolve(_candidate(raw), ParsedPublication(raw_citation=raw)) is None


def test_crossref_resolver_rejects_ambiguous_multi_citation_candidates() -> None:
    """Break caught: a merged PDF block was silently assigned to only one of two papers."""
    first = "A first sufficiently long publication title"
    second = "A second sufficiently long publication title"
    payload = {
        "message": {
            "items": [
                {"DOI": "10.1000/first", "title": [first], "published": {"date-parts": [[2025]]}},
                {"DOI": "10.1000/second", "title": [second], "published": {"date-parts": [[2025]]}},
            ]
        }
    }
    resolver = CrossrefBibliographicResolver(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
        )
    )
    raw = f"Example E. {first}. Journal. 2025. Example E. {second}. Journal. 2025."

    assert resolver.resolve(_candidate(raw, 2025), ParsedPublication(raw_citation=raw)) is None


def test_crossref_resolver_reuses_private_response_cache(tmp_path) -> None:
    """Break caught: rerunning the corpus repeated every external bibliographic query."""
    raw = "Example E. A cacheable sufficiently long publication title. Journal. 2025."
    payload = {
        "message": {
            "items": [
                {
                    "DOI": "10.1000/cache",
                    "title": ["A cacheable sufficiently long publication title"],
                    "published": {"date-parts": [[2025]]},
                }
            ]
        }
    }
    cache = tmp_path / "crossref.json"
    first = CrossrefBibliographicResolver(
        cache_path=cache,
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
        ),
    )
    assert first.resolve(_candidate(raw, 2025), ParsedPublication(raw_citation=raw))

    def fail_if_called(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("cached citations must not hit Crossref again")

    second = CrossrefBibliographicResolver(
        cache_path=cache,
        client=httpx.Client(transport=httpx.MockTransport(fail_if_called)),
    )
    assert second.resolve(_candidate(raw, 2025), ParsedPublication(raw_citation=raw))


def test_crossref_resolver_decodes_html_entities_in_canonical_fields() -> None:
    """Break caught: Crossref HTML entities leaked into the displayed journal name."""
    title = "A sufficiently long medicinal chemistry publication title"
    raw = f"Example E. {title}. Bioorganic & Medicinal Chemistry. 2025."
    payload = {
        "message": {
            "items": [
                {
                    "DOI": "10.1000/entities",
                    "title": [title],
                    "container-title": ["Bioorganic &amp; Medicinal Chemistry"],
                    "published": {"date-parts": [[2025]]},
                }
            ]
        }
    }
    resolver = CrossrefBibliographicResolver(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
        )
    )

    resolved = resolver.resolve(_candidate(raw, 2025), ParsedPublication(raw_citation=raw))

    assert resolved is not None
    assert resolved.journal == "Bioorganic & Medicinal Chemistry"
