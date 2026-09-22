"""Layout-aware, privacy-preserving applicant publication extraction."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
from pypdf import PdfWriter

from app.importer.publication_extraction import (
    GrobidCitationParser,
    ParsedPublication,
    PdfPageText,
    PublicationCandidate,
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


def test_stops_publication_capture_before_support_and_recommendation_letters() -> None:
    """Break caught: later support-letter prose was parsed as applicant publications."""
    pages = (
        _page(
            1,
            """PUBLICATIONS
Example E, Alpha A. A genuine paper. Journal One. 2025.
LETTER OF SUPPORT
Dear Members of the Selection Committee, Example E is an outstanding candidate in 2026.
""",
        ),
        _page(
            2,
            """RECOMMENDATION LETTER
Example E has a strong publication record and is preparing a manuscript in 2026.
""",
        ),
    )

    candidates = extract_candidates_from_pages(
        pages, applicant_name="Erika Example", filename="application.pdf"
    )

    assert len(candidates) == 1
    assert candidates[0].raw_citation.endswith("2025.")


def test_inline_heading_switches_from_in_preparation_to_published_entries() -> None:
    """Break caught: an inline section heading mislabeled all later published papers."""
    pages = (
        _page(
            1,
            """Manuscripts in preparation
Example E, Alpha A. A future paper. In preparation. Additional publications in peer-reviewed scientific journals:
Example E, Beta B. A completed later paper. Journal Two. 2021.
Peer-reviewed books:
Example E. A doctoral thesis. Example University. 2019.
""",
        ),
    )

    candidates = extract_candidates_from_pages(
        pages, applicant_name="Erika Example", filename="publication-list.pdf"
    )

    assert len(candidates) == 2
    assert candidates[0].status_hint == "UNDER_PREPARATION"
    assert candidates[0].raw_citation.endswith("In preparation.")
    assert candidates[1].status_hint == "PUBLISHED"
    assert "completed later paper" in candidates[1].raw_citation


def test_book_chapter_section_does_not_count_as_published_papers() -> None:
    """Break caught: book chapters inflated the published-paper total."""
    candidates = extract_candidates_from_pages(
        (
            _page(
                1,
                """PUBLICATIONS
Example E, Alpha A. A journal paper. Journal One. 2025.
BOOK CHAPTERS
Example E. A chapter. In: Example Handbook. Publisher. 2024.
""",
            ),
        ),
        applicant_name="Erika Example",
        filename="publication-list.pdf",
    )

    assert len(candidates) == 1
    assert "journal paper" in candidates[0].raw_citation


def test_inline_unpublished_heading_does_not_relabel_preceding_paper() -> None:
    """Break caught: a following unpublished heading relabeled a completed paper as preprint."""
    candidates = extract_candidates_from_pages(
        (
            _page(
                1,
                """LIST OF PUBLICATIONS
Example E, Alpha A. A completed paper. Journal One. 2021. Unpublished Manuscripts (under preparation/preprints/submitted manuscripts) From Postdoctoral work
Example E, Beta B. A submitted future paper. bioRxiv. 2026.
""",
            ),
        ),
        applicant_name="Erika Example",
        filename="publication-list.pdf",
    )

    assert len(candidates) == 2
    assert candidates[0].status_hint == "PUBLISHED"
    assert candidates[0].raw_citation.endswith("2021.")
    assert candidates[1].status_hint == "ACCEPTED_PREPRINT"


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


def test_fallback_parser_handles_title_first_and_author_year_title_orders() -> None:
    """Break caught: citations were parsed only when authors appeared before the title."""
    title_first = PublicationCandidate(
        applicant_name="Miloš T. Ivanović",
        filename="publications.pdf",
        page_start=1,
        page_end=1,
        line_start=1,
        line_end=2,
        section_label="PUBLICATIONS",
        status_hint="PUBLISHED",
        raw_citation=(
            "Structure and dynamics of the quaternary hunchback mRNA translation repression complex. "
            "Jakub Macošek, Bernd Simon, Miloš T. Ivanović, Janosch Hennig. "
            "Nucleic Acids Research. 2021;49:8866-8885."
        ),
        normalized_citation="title first fixture",
        year=2021,
        segmentation_method="test",
    )
    apa = PublicationCandidate(
        applicant_name="Erika Example",
        filename="publications.pdf",
        page_start=1,
        page_end=1,
        line_start=3,
        line_end=4,
        section_label="PUBLICATIONS",
        status_hint="PUBLISHED",
        raw_citation=(
            "Example E, Alpha A. (2024). A paper in APA ordering. Journal of Ordered Citations. 12:10-20."
        ),
        normalized_citation="apa fixture",
        year=2024,
        segmentation_method="test",
    )

    first = fallback_parse_candidate(title_first)
    second = fallback_parse_candidate(apa)

    assert first.title.startswith("Structure and dynamics")
    assert any("Ivanović" in author for author in first.authors)
    assert first.journal == "Nucleic Acids Research"
    assert second.title == "A paper in APA ordering"
    assert second.authors == ("Example E", "Alpha A")
    assert second.journal == "Journal of Ordered Citations"


def test_fallback_parser_handles_comma_delimited_authors_title_venue_year() -> None:
    """Break caught: initial-heavy comma citations treated an author as the title."""
    candidate = PublicationCandidate(
        applicant_name="Erika Example",
        filename="publications.pdf",
        page_start=1,
        page_end=1,
        line_start=1,
        line_end=2,
        section_label="PUBLICATIONS",
        status_hint="PUBLISHED",
        raw_citation=(
            "Kulcsár P. I.*, Villiger E. A.*, Example E., In vivo genome editing prevents obesity in mice, "
            "Nature (2026 - under revision)"
        ),
        normalized_citation="comma fixture",
        year=2026,
        segmentation_method="test",
    )

    parsed = fallback_parse_candidate(candidate)

    assert parsed.title == "In vivo genome editing prevents obesity in mice"
    assert parsed.journal == "Nature"
    assert any("Example" in author for author in parsed.authors)


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


def test_low_quality_fragments_and_application_narrative_stay_pending() -> None:
    """Break caught: author initials and support-letter prose were accepted as publications."""
    cases = (
        ParsedPublication(
            authors=("Example E",),
            title="Dr",
            journal="Example E has an outstanding research trajectory",
            year=2026,
            raw_citation="Dr. Example E has an outstanding research trajectory. 2026.",
        ),
        ParsedPublication(
            authors=("Example E",),
            title="Kulcsár P. I., Villiger E. A.",
            journal="Schmidheini L.",
            year=2026,
            raw_citation="Kulcsár P. I., Villiger E. A., Example E. Schmidheini L. 2026.",
        ),
        ParsedPublication(
            authors=("Example E",),
            title="Emini Veseli, L",
            journal="Da Dalt, Sh",
            year=2026,
            raw_citation="Emini Veseli, L. Da Dalt, Sh. Example E. 2026.",
        ),
        ParsedPublication(
            authors=("Example E",),
            title="Malong L, Napoli I, Casal G, White IJ, Stierli S, Vaughan A",
            journal="Characterisation of a biological barrier",
            year=2023,
            raw_citation="Malong L, Napoli I, Casal G, White IJ, Stierli S, Vaughan A. 2023.",
        ),
        ParsedPublication(
            authors=("Example E",),
            title="Contributed equally",
            journal="A later manuscript title",
            year=None,
            raw_citation="Example E. *Contributed equally. A later manuscript title. In preparation.",
        ),
        ParsedPublication(
            authors=("Example E",),
            title="A promising fellowship application",
            journal="Dear Members of the Selection Committee",
            year=2026,
            raw_citation="Dear Members of the Selection Committee, Example E applies in 2026.",
        ),
        ParsedPublication(
            authors=("Example E",),
            title="Anschrift Vorstand Bankverbindung TUM Klinikum",
            journal=None,
            year=2026,
            raw_citation="Anschrift Vorstand Bankverbindung TUM Klinikum Example E 2026.",
        ),
    )

    for parsed in cases:
        assert classify_publication(parsed, section_status="PUBLISHED").disposition == "PENDING_REVIEW"


def test_master_degree_thesis_is_not_a_publication() -> None:
    """Break caught: degree theses inflated the published-paper count."""
    parsed = ParsedPublication(
        authors=("Example E",),
        title="Isolation and characterization of cells",
        journal="Master degree thesis, Example University",
        year=2013,
        raw_citation=(
            "Example E. Isolation and characterization of cells. "
            "Master degree thesis, Example University. 2013."
        ),
    )

    assert classify_publication(parsed, section_status="PUBLISHED").disposition == "NON_PUBLICATION"


def test_administrative_heading_is_not_a_credible_pending_paper_title() -> None:
    parsed = ParsedPublication(
        authors=("Example E",),
        title="Anschrift Vorstand Bankverbindung TUM Klinikum",
        year=2026,
        raw_citation="Anschrift Vorstand Bankverbindung TUM Klinikum Example E 2026.",
    )

    classification = classify_publication(parsed, section_status="PUBLISHED")

    assert classification.disposition == "PENDING_REVIEW"
    assert "credible title" in classification.reason


def test_fallback_parser_rejects_obviously_truncated_doi_suffix() -> None:
    """Break caught: a line-wrapped DOI ending in a hyphen was treated as resolved."""
    candidate = extract_candidates_from_pages(
        (
            _page(
                1,
                """PUBLICATIONS
Example E, Alpha A. A paper with a wrapped identifier. Journal One. 2024. doi:10.1136/gutjnl-
""",
            ),
        ),
        applicant_name="Erika Example",
        filename="cv.pdf",
    )[0]

    assert fallback_parse_candidate(candidate).doi is None


def test_unpublished_candidate_does_not_take_year_from_date_of_birth() -> None:
    """Break caught: a CV birth year became the publication year of an in-revision paper."""
    candidate = PublicationCandidate(
        applicant_name="Erika Example",
        filename="cv.pdf",
        page_start=1,
        page_end=1,
        line_start=1,
        line_end=3,
        section_label="PUBLICATIONS",
        status_hint="PUBLISHED",
        raw_citation=(
            "Example E, Alpha A. A future manuscript. In revision at Nature. "
            "Date of birth: 14/08/1987."
        ),
        normalized_citation="example e alpha a future manuscript in revision nature 1987",
        year=1987,
        segmentation_method="test",
    )

    assert fallback_parse_candidate(candidate).year is None


def test_layout_year_column_is_inherited_by_each_blank_separated_paper() -> None:
    """Break caught: one margin year plus several papers collapsed into one citation."""
    plain = """PUBLICATIONS
2025 Example E, Alpha A. A first paper. Nature 648, 443-450
Beta B, Example E. A second paper. Science 12, 20-29.
Gamma G, Example E. A third paper. Journal One 2, 23.
"""
    layout = """PUBLICATIONS

2025     Example E, Alpha A. A first paper. Nature 648, 443-450

         Beta B, Example E. A second paper. Science 12, 20-29.

         Gamma G, Example E. A third paper. Journal One 2, 23.
"""
    pages = (PdfPageText(1, plain, layout, "cv.pdf"),)

    selected, mode = choose_page_text(plain, layout)
    candidates = extract_candidates_from_pages(
        pages, applicant_name="Erika Example", filename="cv.pdf"
    )

    assert mode == "layout"
    assert selected == layout
    assert [candidate.year for candidate in candidates] == [2025, 2025, 2025]
    assert [fallback_parse_candidate(candidate).title for candidate in candidates] == [
        "A first paper",
        "A second paper",
        "A third paper",
    ]


def test_inline_intellectual_property_heading_stops_patent_leakage() -> None:
    """Break caught: patents following a paper on the same extracted line counted as papers."""
    candidates = extract_candidates_from_pages(
        (
            _page(
                1,
                """PUBLICATIONS
2017 Example E, Alpha A. A real paper. Acta Example 73, 804-813. INTELLECTUAL PROPERTY - Example E (2024). Genetically altered plants. WO2020035486A1. Patent pending.
""",
            ),
        ),
        applicant_name="Erika Example",
        filename="cv.pdf",
    )

    assert len(candidates) == 1
    assert candidates[0].raw_citation.endswith("804-813.")
    assert "Genetically altered plants" not in candidates[0].raw_citation


def test_patent_identifier_is_never_classified_as_a_published_paper() -> None:
    """Break caught: a patent with complete-looking metadata inflated paper totals."""
    parsed = ParsedPublication(
        authors=("Example E", "Alpha A"),
        title="Genetically altered plants expressing heterologous receptors",
        journal="WO2020035486A1",
        year=2024,
        raw_citation=(
            "Example E, Alpha A (2024). Genetically altered plants expressing "
            "heterologous receptors. WO2020035486A1. Patent pending."
        ),
    )

    classification = classify_publication(parsed, section_status="PUBLISHED")

    assert classification.disposition == "NON_PUBLICATION"


def test_candidate_year_ignores_later_cv_date_of_birth() -> None:
    """Break caught: page furniture after a citation replaced its publication year."""
    candidates = extract_candidates_from_pages(
        (
            _page(
                1,
                """PUBLICATIONS
Example E, Alpha A. A real paper. EMBO J. 2022 Sep 1;41:e111955. Date of birth: 14/08/1987.
""",
            ),
        ),
        applicant_name="Erika Example",
        filename="cv.pdf",
    )

    assert candidates[0].year == 2022
    assert fallback_parse_candidate(candidates[0]).year == 2022


def test_in_review_is_preprint_and_lowercase_journal_is_split_from_title() -> None:
    """Break caught: 'in review' was published and lowercase journal text stayed in the title."""
    preprint = ParsedPublication(
        authors=("Example E", "Alpha A"),
        title="A manuscript being evaluated",
        journal="In review New Phytologist",
        year=2026,
        raw_citation="Example E, Alpha A. A manuscript being evaluated. In review New Phytologist.",
    )
    candidate = PublicationCandidate(
        applicant_name="Erika Example",
        filename="publications.pdf",
        page_start=1,
        page_end=1,
        line_start=1,
        line_end=1,
        section_label="PUBLICATIONS",
        status_hint="PUBLISHED",
        raw_citation=(
            "Example E, Alpha A. Nanobodies improve cellular uptake of oligomers. "
            "npj Biosensing 2, 23."
        ),
        normalized_citation="lowercase journal fixture",
        year=2025,
        segmentation_method="test",
    )

    parsed = fallback_parse_candidate(candidate)

    assert classify_publication(preprint, section_status="PUBLISHED").disposition == "ACCEPTED_PREPRINT"
    assert parsed.title == "Nanobodies improve cellular uptake of oligomers"
    assert parsed.journal == "npj Biosensing 2, 23"
    assert classify_publication(parsed, section_status="PUBLISHED").disposition == "PUBLISHED"


def test_colon_inside_title_is_not_mistaken_for_author_title_separator() -> None:
    """Break caught: a subtitle after a colon replaced the first half of the title."""
    candidate = PublicationCandidate(
        applicant_name="Zsolt Balázs",
        filename="publications.pdf",
        page_start=1,
        page_end=1,
        line_start=1,
        line_end=1,
        section_label="PUBLICATIONS",
        status_hint="PUBLISHED",
        raw_citation=(
            "Moreira, R.G., Balázs, Z., Rodrigues-Soares, F.* Population Genetics of PDE4B "
            "in Native Americans: Implications for Cancer Pharmacogenetics. CLIN TRANSL SCI. 2022."
        ),
        normalized_citation="colon in title fixture",
        year=2022,
        segmentation_method="test",
    )

    parsed = fallback_parse_candidate(candidate)

    assert parsed.title == (
        "Population Genetics of PDE4B in Native Americans: "
        "Implications for Cancer Pharmacogenetics"
    )
    assert parsed.journal == "CLIN TRANSL SCI"


def test_bare_numbered_entries_are_segmented_and_parenthesized_year_is_parsed() -> None:
    """Break caught: publication lists numbered `1 Paper`, `2 Paper` became one record."""
    candidates = extract_candidates_from_pages(
        (
            _page(
                1,
                """PUBLICATIONS
1 Example E, Alpha A. (2020) A first numbered paper. FEBS Lett. 12:10-20.
2 Beta B, Example E. (2021) A second numbered paper. Int J Mol Sci. 13:30-40.
""",
            ),
        ),
        applicant_name="Erika Example",
        filename="publication-list.pdf",
    )

    assert len(candidates) == 2
    assert [fallback_parse_candidate(candidate).title for candidate in candidates] == [
        "A first numbered paper",
        "A second numbered paper",
    ]


def test_title_first_citation_parses_comma_year_venue_and_ocr_ligatures() -> None:
    """Break caught: title-first journal/year citations remained pending after OCR."""
    candidate = PublicationCandidate(
        applicant_name="Sébastien Trzebanski",
        filename="publications.pdf",
        page_start=1,
        page_end=1,
        line_start=1,
        line_end=3,
        section_label="PUBLICATIONS",
        status_hint="PUBLISHED",
        raw_citation=(
            "PublicaƟon List (conƟnued) Research ArƟcles CompeƟƟve fungal commensalism "
            "miƟgates candidiasis pathology. Kralova, J.; Trzebanski, S.; Jung, S. "
            "Journal of Experimental Medicine, 2024; 221(5), e20231686."
        ),
        normalized_citation="title first OCR fixture",
        year=2024,
        segmentation_method="test",
    )

    parsed = fallback_parse_candidate(candidate)

    assert parsed.title == "Competitive fungal commensalism mitigates candidiasis pathology"
    assert parsed.journal == "Journal of Experimental Medicine"
    assert classify_publication(parsed, section_status="PUBLISHED").disposition == "PUBLISHED"


def test_contact_profile_with_orcid_year_is_not_a_publication_candidate() -> None:
    """Break caught: the year embedded in an ORCID created a pending paper."""
    candidates = extract_candidates_from_pages(
        (
            _page(
                1,
                """PUBLICATIONS
Erika Example Postdoctoral Fellow erika@example.test +41 77 000 00 00 https://orcid.org/0000-0002-1968-9827
Example E, Alpha A. A real paper. Journal One. 2025.
""",
            ),
        ),
        applicant_name="Erika Example",
        filename="publication-list.pdf",
    )

    assert len(candidates) == 1
    assert "real paper" in candidates[0].raw_citation


def test_three_part_applicant_name_matches_truncated_first_middle_authorship() -> None:
    """Break caught: a truncated author list omitted the final surname and lost the paper."""
    candidates = extract_candidates_from_pages(
        (
            _page(
                1,
                """PUBLICATIONS
10 Alpha A, Besa Emini, Beta B. (2016) BRP-187 inhibits leukotriene biosynthesis. Biochem Pharmacol. 119:17-26.
""",
            ),
        ),
        applicant_name="Besa Emini Veseli",
        filename="publication-list.pdf",
    )

    assert len(candidates) == 1
    assert fallback_parse_candidate(candidates[0]).title == (
        "BRP-187 inhibits leukotriene biosynthesis"
    )


def test_inline_unpublished_work_heading_keeps_following_citation() -> None:
    """Break caught: a same-line unpublished heading either leaked into or erased the title."""
    candidates = extract_candidates_from_pages(
        (
            _page(
                1,
                """PUBLICATIONS
Example E, Alpha A. A completed paper. Journal One. 2024.
Unpublished work (manuscript under preparation): Example E, Beta B. A future manuscript. 2026.
""",
            ),
        ),
        applicant_name="Erika Example",
        filename="publication-list.pdf",
    )

    assert len(candidates) == 2
    assert candidates[1].status_hint == "UNDER_PREPARATION"
    assert candidates[1].raw_citation.startswith("Example E")
    assert fallback_parse_candidate(candidates[1]).title == "A future manuscript"


def test_side_column_status_and_citation_count_are_removed_from_title() -> None:
    """Break caught: layout side-column labels were stored as title words."""
    candidate = PublicationCandidate(
        applicant_name="Erika Example",
        filename="publications.pdf",
        page_start=1,
        page_end=1,
        line_start=1,
        line_end=1,
        section_label="PUBLICATIONS",
        status_hint="PUBLISHED",
        raw_citation=(
            "Example E, Alpha A. (2026) Modulation of Submitted #205 hepatocellular metabolism. "
            "Journal One."
        ),
        normalized_citation="side column fixture",
        year=2026,
        segmentation_method="test",
    )

    parsed = fallback_parse_candidate(candidate)

    assert parsed.title == "Modulation of hepatocellular metabolism"
    assert parsed.journal == "Journal One"
    numeric_venue = fallback_parse_candidate(
        replace(
            candidate,
            raw_citation="Example E, Alpha A. (2026) A submitted manuscript. 2",
        )
    )
    assert numeric_venue.journal is None


def test_title_first_parser_accepts_stylized_lowercase_elife_venue() -> None:
    """Break caught: eLife's stylized lowercase name left an otherwise complete paper pending."""
    candidate = PublicationCandidate(
        applicant_name="Sébastien Trzebanski",
        filename="publications.pdf",
        page_start=1,
        page_end=1,
        line_start=1,
        line_end=2,
        section_label="PUBLICATIONS",
        status_hint="PUBLISHED",
        raw_citation=(
            "Defining murine monocyte differentiation into colonic macrophages. "
            "Gross-Vered, M.; Trzebanski, S.; Jung, S. eLife, 2020; 9, e49998."
        ),
        normalized_citation="elife fixture",
        year=2020,
        segmentation_method="test",
    )

    parsed = fallback_parse_candidate(candidate)

    assert parsed.journal == "eLife"
    assert classify_publication(parsed, section_status="PUBLISHED").disposition == "PUBLISHED"
