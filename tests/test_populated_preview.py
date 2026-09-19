"""Development preview contract for real, administrator-only register data."""

from __future__ import annotations

import re

from app.identity import AuthenticatedIdentity
from app.internal_preview import PreviewApplicantMetric, render_internal_preview
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity


def _administrator() -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        identity=Identity("development:administrator", "preview@example.invalid", "Preview"),
        groups=frozenset({INTERNAL_GROUPS.administrators}),
    )


def test_populated_preview_places_reports_directly_after_workspaces_without_application_cards() -> None:
    records = (
        PreviewApplicantMetric(
            applicant="Applicant One",
            degree="PhD",
            age=36,
            academic_age=8.5,
            gender=None,
            first_author_papers=7,
            last_author_papers=2,
            total_papers=18,
            h_index=12,
            total_citations=640,
            orcid="0000-0002-1825-0097",
            google_scholar_citations=710,
            identity_certainty="High",
        ),
    )

    html = render_internal_preview(_administrator(), simulation=True, records=records)

    after_workspaces = html.split("</section>", 1)[1].lstrip()

    assert after_workspaces.startswith('<section id="reports"')
    assert 'id="applications"' not in html
    assert 'href="#applications"' not in html
    assert 'class="application-row"' not in html
    assert "Applicant One" in html
    assert html.count('role="img"') == 3
    assert 'class="report-table"' in html
    assert html.count('class="report-data-row"') == len(records)
    assert html.count('data-report-row tabindex="0"') == len(records)
    assert 'data-report-modal aria-labelledby="report-details-title"' in html
    assert html.count('<strong class="missing-value">Missing</strong>') == 1
    assert html.count('data-report-sort-direction="ascending"') == 13
    assert html.count('data-report-sort-direction="descending"') == 13
    assert 'aria-label="Sort Applicant ascending"' in html
    assert 'aria-label="Sort GS identity certainty descending"' in html
    assert 'data-report-filter' in html
    assert '<option value="completed">Completed applications</option>' in html
    assert '<option value="missing">Applications where anything is missing</option>' in html
    assert 'data-report-status="missing"' in html
    assert 'href="/internal/reports/metrics.xlsx"' in html
    assert ">Download Excel<" in html
    assert "Citations by anagraphic age" in html
    assert "Citations by academic age" in html
    assert "Academic age versus anagraphic age" in html
    assert "No applicant records" not in html


def test_empty_preview_remains_honest() -> None:
    html = render_internal_preview(_administrator(), simulation=True, records=())

    assert "No application records are loaded" in html
    assert 'id="applications"' not in html
    assert 'class="application-row"' not in html
    assert 'class="report-table"' in html
    assert 'class="report-data-row"' not in html


def test_citation_plots_color_every_applicant_and_label_top_15_surnames() -> None:
    """Break caught: plot points could become monochrome or label the wrong applicants."""
    records = tuple(
        PreviewApplicantMetric(
            applicant=f"Given Surname{index:02d}",
            age=30 + index,
            academic_age=3 + index,
            total_citations=index,
        )
        for index in range(18)
    )

    html = render_internal_preview(_administrator(), simulation=True, records=records)

    point_colors = re.findall(
        r'<circle class="plot-point[^\"]*"[^>]+fill="(#[0-9A-F]{6})"', html
    )
    callout_labels = re.findall(
        r'<text class="plot-callout-label"[^>]*>([^<]+)</text>', html
    )

    assert len(point_colors) == 54
    assert len(set(point_colors[:18])) == 18
    assert point_colors[18:36] == point_colors[:18]
    assert point_colors[36:] == point_colors[:18]
    assert callout_labels
    assert len(callout_labels) <= 45
    assert set(callout_labels) <= {f"Surname{index:02d}" for index in range(3, 18)}
    for index in range(3):
        assert f">Surname{index:02d}</text>" not in html
    assert html.count('class="plot-point') == 54
    assert 'aria-label="Given Surname17: anagraphic age 47, 17 citations"' in html


def test_report_plots_render_linear_value_axes_and_a_citation_scaled_age_bubble_plot() -> None:
    """Break caught: charts could omit value scales or disguise a bubble plot as categories."""
    records = (
        PreviewApplicantMetric(
            applicant="First Author", age=30, academic_age=4, total_citations=25
        ),
        PreviewApplicantMetric(
            applicant="Second Author", age=40, academic_age=14, total_citations=100
        ),
    )

    html = render_internal_preview(_administrator(), simulation=True, records=records)

    assert html.count('class="plot-gridline"') >= 12
    assert 'data-plot-x="30" data-plot-y="25"' in html
    assert 'data-plot-x="40" data-plot-y="100"' in html
    assert 'Academic age versus anagraphic age' in html
    assert 'class="plot-point plot-bubble"' in html
    assert 'data-plot-x="30" data-plot-y="4" data-citations="25"' in html
    assert 'data-plot-x="40" data-plot-y="14" data-citations="100"' in html
    bubble_radii = {
        int(citations): float(radius)
        for citations, radius in re.findall(
            r'class="plot-point plot-bubble"[^>]+data-citations="(\d+)"[^>]+r="([\d.]+)"',
            html,
        )
    }
    assert bubble_radii[100] ** 2 == 4 * bubble_radii[25] ** 2


def test_age_comparison_callouts_rank_only_records_that_can_be_plotted() -> None:
    """Break caught: excluded high-citation records could consume bubble-chart labels."""
    records = tuple(
        PreviewApplicantMetric(
            applicant=f"Excluded Author{index}", age=30 + index, total_citations=1000 + index
        )
        for index in range(15)
    ) + (
        PreviewApplicantMetric(
            applicant="Visible Author", age=46, academic_age=12, total_citations=10
        ),
    )

    html = render_internal_preview(_administrator(), simulation=True, records=records)
    bubble_chart = html.split("Academic age versus anagraphic age", 1)[1]

    assert ">Author</text>" in bubble_chart
