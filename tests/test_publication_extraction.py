"""Layout-aware, privacy-preserving applicant publication extraction."""

from __future__ import annotations

import httpx
import pytest
from pypdf import PdfWriter

from app.importer.publication_extraction import (
    GrobidCitationParser,
    ParsedPublication,
    PdfPageText,
    classify_publication,
    choose_page_text,
    extract_candidates_from_pages,
    extract_document,
    fallback_parse_candidate,
    parse_grobid_tei,
)


def _page(number: int, plain: str, layout: str | None = None) -> PdfPageText:
    return PdfPageText(number, plain, plain if layout is None else layout, "fixture")


def test_page_text_selection_prefers_restored_lines_without_accepting_smashed_words() -> None:
    plain_one_line = (
        "Publication list Example E, Other A. First reliable paper. Journal 2: 1-9, 2025. "
        "Other A, Example E. Second reliable paper. Journal 3: 10-19, 2024."
    )
    layout_lines = """Publication list

Example E, Other A. First reliable paper. Journal 2: 1-9, 2025.

Other A, Example E. Second reliable paper. Journal 3: 10-19, 2024.
"""
    selected, mode = choose_page_text(plain_one_line, layout_lines)
    assert mode == "layout"
    assert len(selected.splitlines()) > 3

    plain_words = "Example E, Other A. A readable title. Example Journal. 2025."
    smashed_layout = "ExampleE,OtherA.Areadabletitle.ExampleJournal.2025."
    selected, mode = choose_page_text(plain_words, smashed_layout)
    assert mode == "plain"
    assert selected == plain_words


def test_segments_year_column_entries_and_joins_wrapped_lines() -> None:
    pages = (
        _page(
            1,
            "",
            """PUBLICATIONS

202 6    Example E, Alpha A, Beta B,
         Gamma G, Delta D. A first reliable paper about cells and tissues.
         Journal One. 14: 101-109, 2026.

2025     Beta B, Example E. A second reliable paper. Journal Two.
         2025;9:e1042.
""",
        ),
    )

    candidates = extract_candidates_from_pages(
        pages, applicant_name="Erika Example", filename="combined-application.pdf"
    )

    assert [candidate.year for candidate in candidates] == [2026, 2025]
    assert candidates[0].raw_citation.startswith("2026 ")
    assert "cells and tissues" in candidates[0].raw_citation
    assert all(candidate.section_label == "PUBLICATIONS" for candidate in candidates)


def test_keeps_unpublished_section_entries_without_year_and_ignores_year_like_title_tokens() -> None:
    pages = (
        _page(
            1,
            """List of Publications
Submitted manuscripts
• Alpha A, Example E. A submitted paper. Available at SSRN: https://ssrn.test/5953245
Manuscripts in preparation
• Example E, Beta B. Colonization by Example strain 1917. In preparation.
""",
        ),
    )

    candidates = extract_candidates_from_pages(
        pages, applicant_name="Erika Example", filename="publication-list.pdf"
    )

    assert len(candidates) == 2
    assert candidates[0].status_hint == "ACCEPTED_PREPRINT"
    assert candidates[0].year is None
    assert candidates[1].status_hint == "UNDER_PREPARATION"
    assert candidates[1].year is None


def test_segments_blank_terminal_year_bullet_and_numbered_layouts() -> None:
    layouts = (
        (
            "publication-list.pdf",
            """Publication list

Example E, Alpha A: A blank separated paper. Journal One 4: 1-8, 2025.

Beta B, Example E: Another blank separated paper. Journal Two 8: e22, 2024.
""",
            2,
        ),
        (
            "curriculum.pdf",
            """PUBLICATIONS
Example E, Alpha A. A terminal year paper. Journal One. 2025.
Beta B, Example E. A second terminal year paper. Journal Two. 2024.
CONFERENCE WORKSHOP PAPERS
Example E, Gamma G. A workshop paper. Proceedings of ExampleConf. 2023.
""",
            3,
        ),
        (
            "publication-list.pdf",
            """Publication List
• Alpha A, Example E, et al. A bullet paper. Journal One. 2025.
• Example E, Beta B. Another bullet paper. Journal Two. 2024.
Review
• Example E, Gamma G. A review paper. Review Journal. 2023.
""",
            3,
        ),
        (
            "publication-list.pdf",
            """List of Publications
Peer-reviewed publications
1. Alpha A, Example E. A numbered paper. Journal One. 2025.
2. Example E, Beta B. Another numbered paper. Journal Two. 2024.
Submitted manuscripts
• Example E, Gamma G. A submitted paper. Submitted to Journal Three. 2026.
Manuscripts in preparation
• Delta D, Example E. An unfinished paper. In preparation. 2026.
""",
            4,
        ),
    )

    for filename, text, expected_count in layouts:
        candidates = extract_candidates_from_pages(
            (_page(1, text),), applicant_name="Erika Example", filename=filename
        )
        assert len(candidates) == expected_count, filename


def test_carries_an_unfinished_entry_across_pages_and_removes_repeated_furniture() -> None:
    pages = (
        _page(
            1,
            """Publication list                                      Erika Example
Publication list

Alpha A, Example E, Beta B. A paper whose citation continues
onto the next page without its venue
1
""",
        ),
        _page(
            2,
            """Publication list                                      Erika Example
in Journal One 12: 44-51, 2024.

Example E, Gamma G. A complete second paper. Journal Two. 2023.
2
""",
        ),
    )

    candidates = extract_candidates_from_pages(
        pages, applicant_name="Erika Example", filename="publication-list.pdf"
    )

    assert len(candidates) == 2
    assert candidates[0].page_start == 1
    assert candidates[0].page_end == 2
    assert "Publication list" not in candidates[0].raw_citation
    assert "continues onto the next page" in candidates[0].raw_citation


def test_excludes_contacts_narrative_and_research_plan_references() -> None:
    pages = (
        _page(
            1,
            """Erika Example, PhD
Zurich | erika@example.test | +41 00 000 00 00
PUBLICATIONS
Conference papers in this field are peer-reviewed and usually non-archival.
Example E, Alpha A. A genuine paper. Journal One. 2025.
PRESENTATIONS
Example E. An invited lecture. Example University. 2025.
REFERENCES
Other O, Example E. A paper cited in the research plan. Journal X. 2024.
""",
        ),
    )

    candidates = extract_candidates_from_pages(
        pages, applicant_name="Erika Example", filename="curriculum.pdf"
    )

    assert len(candidates) == 1
    assert "genuine paper" in candidates[0].raw_citation


def test_empty_pdf_is_audited_without_inventing_candidates(tmp_path) -> None:
    path = tmp_path / "empty-publication-list.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)

    audit = extract_document(path, "Erika Example")

    assert audit.page_count == 1
    assert audit.candidates == ()
    assert audit.issues == ("NO_EXTRACTABLE_TEXT",)
    assert len(audit.source_sha256) == 64


def test_parses_structured_grobid_citation_fields_independent_of_xml_order() -> None:
    """Break caught: reordered TEI fields or truncated authors erased citation metadata."""
    tei = """<?xml version="1.0" encoding="UTF-8"?>
<biblStruct xmlns="http://www.tei-c.org/ns/1.0">
  <monogr>
    <imprint>
      <biblScope unit="page" from="44" to="51" />
      <date type="published" when="2024" />
      <biblScope unit="volume">12</biblScope>
    </imprint>
    <title level="j">Journal of Reliable Results</title>
  </monogr>
  <analytic>
    <author><persName><forename type="first">Erika</forename><surname>Example</surname></persName></author>
    <author><persName><forename type="first">Alex</forename><surname>Alpha</surname></persName></author>
    <author><persName><surname>et al.</surname></persName></author>
    <title level="a">A robust citation parser</title>
  </analytic>
  <idno type="DOI">10.1234/example.2024.9</idno>
</biblStruct>"""

    parsed = parse_grobid_tei(tei, raw_citation="Example E, et al. Citation")

    assert parsed.authors == ("Erika Example", "Alex Alpha", "et al.")
    assert parsed.title == "A robust citation parser"
    assert parsed.journal == "Journal of Reliable Results"
    assert parsed.volume == "12"
    assert parsed.pages == "44-51"
    assert parsed.year == 2024
    assert parsed.doi == "10.1234/example.2024.9"
    assert parsed.parser_method == "grobid"


def test_fallback_parser_recovers_fields_when_grobid_is_unavailable() -> None:
    """Break caught: a local parser outage forced otherwise clear citations to pending."""
    candidate = extract_candidates_from_pages(
        (
            _page(
                1,
                """PUBLICATIONS
Example E, Alpha A, Beta B. A deterministic fallback paper. Journal One. 2025; 14(2): 101-109. doi:10.1234/fallback.1
""",
            ),
        ),
        applicant_name="Erika Example",
        filename="cv.pdf",
    )[0]

    parsed = fallback_parse_candidate(candidate)

    assert parsed.authors == ("Example E", "Alpha A", "Beta B")
    assert parsed.title == "A deterministic fallback paper"
    assert parsed.journal == "Journal One"
    assert parsed.volume == "14"
    assert parsed.issue == "2"
    assert parsed.pages == "101-109"
    assert parsed.year == 2025
    assert parsed.doi == "10.1234/fallback.1"
    assert parsed.parser_method == "deterministic"


def test_classification_uses_bibliographic_evidence_not_doi_resolution() -> None:
    """Break caught: DOI-less papers and proceedings were downgraded to pending."""
    cases = (
        (
            ParsedPublication(
                authors=("Example E", "Alpha A"),
                title="A DOI-less journal article",
                journal="Journal One",
                year=2025,
                raw_citation="Example E, Alpha A. A DOI-less journal article. Journal One. 2025.",
                parser_method="deterministic",
            ),
            "PUBLISHED",
        ),
        (
            ParsedPublication(
                authors=("Example E", "Alpha A"),
                title="A proceedings paper",
                journal="Proceedings of ExampleConf",
                year=2024,
                raw_citation="Example E, Alpha A. A proceedings paper. Proceedings of ExampleConf. 2024.",
                parser_method="grobid",
            ),
            "PUBLISHED",
        ),
    )

    for parsed, expected in cases:
        classification = classify_publication(parsed, section_status="PUBLISHED")
        assert classification.disposition == expected
        assert classification.confidence >= 0.9


def test_inline_status_signals_override_publication_section_heading() -> None:
    """Break caught: an item inherited PUBLISHED despite explicit manuscript wording."""
    cases = (
        (
            "Example E, Alpha A. A future paper. In preparation.",
            ParsedPublication(
                authors=("Example E", "Alpha A"),
                title="A future paper",
                journal=None,
                year=None,
                raw_citation="Example E, Alpha A. A future paper. In preparation.",
                parser_method="deterministic",
            ),
            "UNDER_PREPARATION",
        ),
        (
            "Example E, Alpha A. A revision. bioRxiv. 2025. In revision.",
            ParsedPublication(
                authors=("Example E", "Alpha A"),
                title="A revision",
                journal="bioRxiv",
                year=2025,
                raw_citation="Example E, Alpha A. A revision. bioRxiv. 2025. In revision.",
                parser_method="deterministic",
            ),
            "ACCEPTED_PREPRINT",
        ),
        (
            "Example E. Doctoral thesis. Example University. 2023.",
            ParsedPublication(
                authors=("Example E",),
                title="Doctoral thesis",
                journal="Example University",
                year=2023,
                raw_citation="Example E. Doctoral thesis. Example University. 2023.",
                parser_method="deterministic",
            ),
            "NON_PUBLICATION",
        ),
    )

    for raw, parsed, expected in cases:
        assert parsed.raw_citation == raw
        classification = classify_publication(parsed, section_status="PUBLISHED")
        assert classification.disposition == expected


def test_ambiguous_incomplete_candidate_stays_pending_review() -> None:
    """Break caught: incomplete narrative text was accepted as a paper."""
    parsed = ParsedPublication(
        authors=("Example E",),
        title="An ambiguous item",
        journal=None,
        year=None,
        raw_citation="Example E. An ambiguous item.",
        parser_method="deterministic",
    )

    classification = classify_publication(parsed, section_status="PUBLISHED")

    assert classification.disposition == "PENDING_REVIEW"
    assert "missing journal" in classification.reason
    assert "missing year" in classification.reason


def test_local_grobid_client_converts_service_response_to_parsed_publication() -> None:
    """Break caught: the local GROBID adapter sent the wrong API payload or ignored TEI."""
    tei = """<biblStruct xmlns="http://www.tei-c.org/ns/1.0">
      <analytic><author><persName><forename>Erika</forename><surname>Example</surname></persName></author>
      <title level="a">A parsed paper</title></analytic>
      <monogr><title level="j">Journal One</title><imprint><date when="2025"/></imprint></monogr>
    </biblStruct>"""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/processCitation"
        assert b"citations=Example+E" in request.content
        return httpx.Response(200, text=tei)

    client = httpx.Client(transport=httpx.MockTransport(handle))
    parser = GrobidCitationParser("http://127.0.0.1:8070", client=client)

    parsed = parser.parse("Example E. A parsed paper. Journal One. 2025.")

    assert parsed.title == "A parsed paper"
    assert parsed.journal == "Journal One"
    assert parsed.raw_citation == "Example E. A parsed paper. Journal One. 2025."


def test_grobid_client_refuses_non_loopback_endpoints() -> None:
    """Break caught: private applicant citations could be sent to a remote parser."""
    with pytest.raises(ValueError, match="loopback"):
        GrobidCitationParser("https://parser.example.test")


def test_segments_colon_style_entries_after_under_revision_and_stops_at_decorated_heading() -> None:
    """Break caught: consecutive revision items and later talks collapsed into one paper."""
    pages = (
        _page(
            1,
            """JOURNAL AND CONFERENCE PUBLICATIONS
* authors contributed equally
Example E, Alpha A: A first colon-style paper. Nat Protocols. Under revision
Beta B, Example E: A second colon-style paper. Nat Commun 12: 3827, 2021.
SELECTED CONFERENCE PRESENTATIONS
Example E. A conference talk. Example University. 2025.
""",
        ),
    )

    candidates = extract_candidates_from_pages(
        pages, applicant_name="Erika Example", filename="cv.pdf"
    )

    assert len(candidates) == 2
    assert candidates[0].raw_citation.startswith("Example E")
    assert candidates[0].raw_citation.endswith("Under revision")
    assert "authors contributed equally" not in candidates[0].raw_citation
    assert "conference talk" not in candidates[1].raw_citation


def test_fallback_parser_handles_author_title_colon_and_compact_venue_metadata() -> None:
    """Break caught: colon-formatted papers lost title and journal and stayed pending."""
    candidate = extract_candidates_from_pages(
        (
            _page(
                1,
                """PUBLICATIONS
Example E, Alpha A and Beta B: Phase separation properties of proteins. Nat Struct Mol Biol 30: 451–462, 2023.
""",
            ),
        ),
        applicant_name="Erika Example",
        filename="cv.pdf",
    )[0]

    parsed = fallback_parse_candidate(candidate)
    classification = classify_publication(parsed, section_status=candidate.status_hint)

    assert parsed.authors == ("Example E", "Alpha A", "Beta B")
    assert parsed.title == "Phase separation properties of proteins"
    assert parsed.journal == "Nat Struct Mol Biol"
    assert parsed.volume == "30"
    assert parsed.pages == "451-462"
    assert classification.disposition == "PUBLISHED"


def test_accepted_and_under_revision_manuscripts_are_preprints_not_published() -> None:
    """Break caught: accepted but not yet published manuscripts inflated published totals."""
    for wording in ("Accepted in Nature", "Under revision"):
        parsed = ParsedPublication(
            authors=("Example E", "Alpha A"),
            title="A manuscript",
            journal="Nature",
            year=2026,
            raw_citation=f"Example E, Alpha A. A manuscript. Nature. {wording}.",
            parser_method="deterministic",
        )
        assert (
            classify_publication(parsed, section_status="PUBLISHED").disposition
            == "ACCEPTED_PREPRINT"
        )
