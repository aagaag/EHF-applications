from __future__ import annotations

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


def test_render_detail_marks_confident_first_and_last_author_publications() -> None:
    """Break caught: applicant lead-author publications could be indistinguishable in review."""
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

    assert 'data-author-position="first"' in html
    assert 'data-author-position="last"' in html
    assert 'data-author-position="middle"' not in html
    assert html.count("applicant-publication-row--lead-author") == 2


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
