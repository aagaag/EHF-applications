"""Layout-aware, privacy-preserving applicant publication extraction."""

from __future__ import annotations

from pypdf import PdfWriter

from app.importer.publication_extraction import (
    PdfPageText,
    choose_page_text,
    extract_candidates_from_pages,
    extract_document,
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
