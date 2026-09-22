from __future__ import annotations

import math
import re

from app.applicant_detail import ApplicantDetail, Publication, render_applicant_detail


def test_render_detail_shows_identity_charts_and_newest_first_links() -> None:
    detail = ApplicantDetail(
        application_number="EHF-2026-007",
        name="Ada <Researcher>",
        age=37,
        academic_age=11,
        publications=(
            Publication(
                title="Older work",
                journal="Journal A",
                year=2022,
                doi="10.1000/older",
                repository_url="https://repo.example/older",
                citation_count=3,
                citations_by_year=((2022, 1), (2024, 2)),
            ),
            Publication(
                title="Newer work",
                journal="Journal B",
                year=2024,
                journal_url="https://journals.example/newer",
                source_url="https://source.example/newer",
                citation_count=7,
                citations_by_year=((2024, 4), (2025, 3)),
            ),
        ),
    )

    html = render_applicant_detail(detail, current_year=2026)

    assert "EHF-2026-007" in html
    assert "Ada &lt;Researcher&gt;" in html
    assert "Age: 37" in html and "Academic age: 11" in html
    assert 'aria-label="Papers by year, 2022 through 2026"' in html
    assert 'aria-label="Citations by year, 2022 through 2026"' in html
    assert 'aria-label="2024: 6"' in html
    assert 'aria-label="2025: 3"' in html
    assert html.index("Newer work") < html.index("Older work")
    assert 'data-publication-url="https://doi.org/10.1000/older"' in html
    assert 'data-publication-url="https://journals.example/newer"' in html
    assert 'href="https://source.example/newer"' not in html
    assert 'data-publication-row' in html and 'data-double-clickable="true"' in html
    assert 'role="table" aria-label="Applicant publications"' in html
    assert 'data-publication-sort-direction="ascending"' in html
    assert 'data-publication-sort-direction="descending"' in html
    assert '>Citations<' in html
    assert 'data-publication-citations="7"' in html
    assert 'data-publication-citations="3"' in html
    assert html.count('data-full-page-chart') == 3
    assert html.count('role="link" tabindex="0"') == 3


def test_render_detail_exposes_labeled_vertical_axes_in_a_single_chart_row() -> None:
    """Break caught: charts could lose their quantity axes or return to a tall stack."""
    detail = ApplicantDetail(
        application_number="EHF-2026-007",
        name="Ada Researcher",
        publications=(
            Publication(title="First work", year=2024, citations_by_year=((2024, 2),)),
            Publication(title="Companion work", year=2024),
            Publication(title="Second work", year=2025, citations_by_year=((2025, 5),)),
        ),
    )

    html = render_applicant_detail(detail, current_year=2025)

    assert '<div class="applicant-detail-charts">' in html
    assert 'class="chart-y-axis-label"' in html
    assert '>Papers</text>' in html
    assert '>Citations</text>' in html
    assert html.count('class="chart-y-axis-tick"') >= 4
    assert '>0</text>' in html
    assert '>2</text>' in html
    assert '>5</text>' in html


def test_every_modal_graph_explains_axes_size_color_and_unavailable_values() -> None:
    detail = ApplicantDetail(
        application_number="EHF-2026-007",
        name="Ada Researcher",
        publications=(
            Publication(
                title="Lead work", year=2024, citation_count=8,
                citations_by_year=((2025, 3),),
                authors_text="Ada Researcher; Ben Biologist",
                journal_two_year_mean_citedness=4.0,
            ),
            Publication(
                title="Middle work", year=2025, citation_count=None,
                authors_text="Ben Biologist; Ada Researcher; Cara Chemist",
                journal_two_year_mean_citedness=None,
            ),
        ),
    )

    html = render_applicant_detail(detail, current_year=2025)

    assert html.count('class="chart-legend"') == 3
    assert "Horizontal axis: publication year" in html
    assert "Vertical axis: number of papers" in html
    assert "Bar height is the paper count" in html
    assert "Horizontal axis: citation year" in html
    assert "Vertical axis: citations received in that year" in html
    assert "Bar height is the total received by all candidate papers" in html
    assert "Vertical axis: OpenAlex 2-year journal citedness" in html
    assert "N/A lane: journal citedness unavailable" not in html
    assert "Bubble area represents OpenAlex citations" in html
    assert "Red: first, sole, or last author. Blue: neither first nor last author." in html
    assert "Dashed outline: citation count unavailable" in html


def test_render_detail_exposes_author_filter_and_marks_known_author_positions() -> None:
    """Break caught: middle-author publications could not be filtered or distinguished."""
    detail = ApplicantDetail(
        application_number="EHF-2026-007",
        name="Ada Researcher",
        publications=(
            Publication(title="First author", year=2022, authors_text="Ada Researcher; Ben Biologist"),
            Publication(title="Middle author", year=2023, authors_text="Ben Biologist; Ada Researcher; Cara Chemist"),
            Publication(title="Last author", year=2024, authors_text="Ben Biologist; Ada Researcher"),
        ),
    )

    html = render_applicant_detail(detail, current_year=2024)

    assert 'role="group" aria-label="Publication author filter"' in html
    assert 'data-publication-author-filter="all" aria-pressed="true">All<' in html
    assert 'data-publication-author-filter="lead" aria-pressed="false">1st/last<' in html
    assert 'data-author-position="first"' in html
    assert 'data-author-position="last"' in html
    assert 'data-author-position="middle"' in html
    assert html.count("applicant-publication-row--lead-author") == 2
    assert "applicant-publication-row--middle-author" in html


def test_render_detail_marks_an_author_with_an_abbreviated_middle_name() -> None:
    """Break caught: a published middle initial hid the applicant's lead role."""
    detail = ApplicantDetail(
        application_number="EHF-2026-007",
        name="Fernando Pablo Canale",
        publications=(
            Publication(
                title="First author with middle initial",
                year=2023,
                authors_text="Fernando P. Canale; Julia Neumann",
            ),
            Publication(
                title="Initial-only names remain ambiguous",
                year=2024,
                authors_text="F. P. Canale; Julia Neumann",
            ),
        ),
    )

    html = render_applicant_detail(detail, current_year=2024)

    assert html.count('data-publication-row data-publication-citations="" data-double-clickable="true" tabindex="0" data-author-position="first"') == 1
    assert html.count("applicant-publication-row--lead-author") == 1


def test_render_detail_escapes_text_and_rejects_unsafe_links() -> None:
    detail = ApplicantDetail(
        application_number='"><script>alert(1)</script>',
        name="Name & Co",
        publications=(
            Publication(
                title="<b>Unsafe</b>",
                journal="J & J",
                year=2025,
                doi="javascript:alert(1)",
                source_url="javascript:alert(2)",
            ),
        ),
    )

    html = render_applicant_detail(detail, current_year=2025)

    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;Unsafe&lt;/b&gt;" in html
    assert "javascript:" not in html.lower()
    assert 'aria-label="Papers by year, 2025 through 2025"' in html


def test_render_detail_omits_publications_without_journal_citedness_from_the_scatter() -> None:
    detail = ApplicantDetail(
        application_number="EHF-2026-007",
        name="Ada Researcher",
        publications=(
            Publication(
                title="Largest first-author work",
                journal="Journal <A>",
                year=2024,
                citation_count=10,
                authors_text="Ada Researcher; Ben Biologist",
                journal_openalex_name="Journal <A>",
                journal_two_year_mean_citedness=4.25,
                journal_metric_observed_at_utc="2026-09-21T08:00:00.000000Z",
            ),
            Publication(
                title="Zero-citation middle work",
                journal="Journal B",
                year=2024,
                citation_count=0,
                authors_text="Ben Biologist; Ada Researcher; Cara Chemist",
                journal_openalex_name="Journal B",
                journal_two_year_mean_citedness=2.0,
            ),
            Publication(
                title="Missing metric last-author work",
                journal="Repository C",
                year=2025,
                citation_count=None,
                authors_text="Ben Biologist; Ada Researcher",
            ),
            Publication(
                title="No year <omitted>",
                journal="Journal D",
                citation_count=4,
                journal_two_year_mean_citedness=3.0,
            ),
        ),
    )

    html = render_applicant_detail(detail, current_year=2025)

    assert 'class="applicant-detail-chart applicant-detail-chart--journal-scatter"' in html
    assert "Papers by year and journal citedness" in html
    assert "OpenAlex 2-year journal citedness" in html
    assert "Bubble area represents OpenAlex citations" in html
    assert "Red: first, sole, or last author. Blue: neither first nor last author." in html
    assert "2026-09-21" in html
    assert "2 papers plotted; 1 omitted because its publication year is unavailable; 1 omitted because its journal citedness is unavailable." in html
    assert html.count('data-journal-scatter-list-item') == 2
    assert 'data-author-position="first"' in html
    assert 'data-author-position="last"' in html
    assert 'journal-scatter-point--lead-author' in html
    assert 'journal-scatter-point--other-author' in html
    assert 'journal-scatter-point--metric-unavailable' not in html
    assert 'journal-scatter-na-lane' not in html
    assert 'journal-scatter-na-label' not in html
    assert "Journal &lt;A&gt;" in html
    assert "Missing metric last-author work" not in html.split('<section class="applicant-publications"', 1)[0]
    assert "No year &lt;omitted&gt;" in html

    circles = re.findall(
        r'<circle[^>]*data-journal-scatter-point[^>]*data-citation-count="([^"]*)"[^>]*data-publication-year="([^"]+)"[^>]*cx="([^"]+)"[^>]*r="([^"]+)"',
        html,
    )
    assert len(circles) == 2
    assert [count for count, _year, _x, _radius in circles] == ["10", "0"]
    assert circles[0][1] == circles[1][1] == "2024"
    assert circles[0][2] == circles[1][2]
    largest_area = math.pi * float(circles[0][3]) ** 2
    zero_area = math.pi * float(circles[1][3]) ** 2
    assert abs((largest_area - zero_area) - 900.0) < 0.25


def test_render_detail_uses_a_compact_journal_scatter_empty_state_when_years_are_unavailable() -> None:
    html = render_applicant_detail(
        ApplicantDetail(
            application_number="EHF-2026-007",
            name="Ada Researcher",
            publications=(Publication(title="Unplaced", year=None, citation_count=2),),
        ),
        current_year=2025,
    )

    assert "Papers by year and journal citedness" in html
    assert "No publications have both a valid publication year and journal citedness value for this chart." in html
    assert "<circle" not in html
