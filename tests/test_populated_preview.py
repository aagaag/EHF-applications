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


def test_overview_starts_with_three_reports_and_uses_compact_combined_metrics() -> None:
    records = (
        PreviewApplicantMetric(
            application_id="a7000000-0000-4000-8000-000000000001",
            application_number="EHF-2026-001",
            applicant="Applicant One",
            degree="PhD",
            age=36,
            academic_age=8.5,
            gender=None,
            first_author_papers=2,
            last_author_papers=0,
            total_papers=18,
            validated_published_papers=16,
            validated_preprint_papers=2,
            h_index=12,
            orcid="0000-0002-1825-0097",
            google_scholar_citations=710,
            identity_certainty="High",
            verified_citations=656,
            verified_citation_source="OpenAlex",
            verified_citation_profile_url="https://openalex.org/A123",
        ),
    )

    html = render_internal_preview(_administrator(), simulation=True, records=records)

    assert 'workspaces-heading' not in html
    assert 'class="shell-grid"' not in html
    assert html.index('class="report-grid"') < html.index('class="report-table"')
    assert 'id="applications"' not in html
    assert 'href="#applications"' not in html
    assert 'class="application-row"' not in html
    assert "Applicant One" in html
    assert html.count('role="img"') == 3
    assert 'class="report-table"' in html
    assert html.count('class="report-data-row"') == len(records)
    assert html.count('data-report-row tabindex="0"') == len(records)
    assert 'data-report-modal aria-labelledby="report-details-title"' in html
    assert 'data-application-id="a7000000-0000-4000-8000-000000000001"' in html
    assert 'data-report-details-url="/api/internal/applicants/a7000000-0000-4000-8000-000000000001/metrics-detail"' in html
    assert '<div class="report-details-content" data-report-details>' in html
    assert html.count('<strong class="missing-value">Missing</strong>') == 1
    assert html.count('data-report-sort-direction="ascending"') == 9
    assert html.count('data-report-sort-direction="descending"') == 9
    assert 'aria-label="Sort Applicant ascending"' in html
    assert 'aria-label="Sort OpenAlex citations (20 Sep 2026) descending"' in html
    assert 'data-report-filter' in html
    assert '<option value="completed">Completed applications</option>' in html
    assert '<option value="missing">Applications where anything is missing</option>' in html
    assert 'data-report-status="missing"' in html
    assert 'href="/internal/reports/metrics.xlsx"' in html
    assert ">Download Excel<" in html
    assert "Citations by anagraphic age" in html
    assert "Citations by academic age" in html
    assert "Academic age versus anagraphic age" in html
    assert "First / last author papers" in html
    assert "Published papers/preprints" in html
    assert "Applicant-reported / validated published papers" not in html
    assert "OpenAlex citations (20 Sep 2026)" in html
    assert "2 / 0" in html
    assert "16 / 2" in html
    assert ">656<" in html
    assert "Citation source" not in html
    assert "ORCID" not in html
    assert "No applicant records" not in html


def test_reports_name_the_verified_profile_source_without_overwriting_the_self_report() -> None:
    record = PreviewApplicantMetric(
        applicant="Profile Source",
        age=36,
        academic_age=8.5,
        verified_citations=710,
        verified_citation_source="OpenAlex",
        verified_citation_profile_url="https://openalex.org/A123",
    )

    html = render_internal_preview(_administrator(), simulation=True, records=(record,))

    assert "OpenAlex citations (20 Sep 2026)" in html
    assert "Citation source" not in html
    assert ">710<" in html
    assert "OpenAlex citations are calculated" in html


def test_empty_preview_remains_honest() -> None:
    html = render_internal_preview(_administrator(), simulation=True, records=())

    assert "No application records are loaded" in html
    assert 'id="applications"' not in html
    assert 'class="application-row"' not in html
    assert 'class="report-table"' in html
    assert 'class="report-data-row"' not in html


def test_report_h_index_uses_the_candidate_relative_blue_heat_scale() -> None:
    """Break caught: H-index cells could lose their relative reviewer comparison."""
    records = (
        PreviewApplicantMetric(applicant="Lowest", h_index=4),
        PreviewApplicantMetric(applicant="Middle", h_index=14),
        PreviewApplicantMetric(applicant="Highest", h_index=24),
        PreviewApplicantMetric(applicant="Unavailable", h_index=None),
    )

    html = render_internal_preview(_administrator(), simulation=True, records=records)

    assert re.findall(
        r'data-label="h-index" data-h-index-heat class="h-index-heat-(\d+)">(\d+)',
        html,
    ) == [("10", "4"), ("50", "14"), ("90", "24")]
    assert 'style="--h-index-saturation:' not in html
    assert 'data-label="h-index"><strong class="missing-value">Missing</strong>' in html


def test_citation_plots_color_every_applicant_and_label_top_15_surnames() -> None:
    """Break caught: plot points could become monochrome or label the wrong applicants."""
    records = tuple(
        PreviewApplicantMetric(
            applicant=f"Given Surname{index:02d}",
            age=30 + index,
            academic_age=3 + index,
            verified_citations=index,
            h_index=index,
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
    assert point_colors[0] == "#EEF0F1"
    assert point_colors[17] == "#0B6BCB"
    assert point_colors[18:36] == point_colors[:18]
    assert point_colors[36:] == point_colors[:18]
    assert callout_labels
    assert len(callout_labels) <= 45
    assert set(callout_labels) <= {f"Surname{index:02d}" for index in range(3, 18)}
    for index in range(3):
        assert f">Surname{index:02d}</text>" not in html
    assert html.count('class="plot-point') == 54
    assert (
        'aria-label="Given Surname17: anagraphic age 47, 17 citations, h-index 17"'
        in html
    )


def test_report_plots_render_linear_value_axes_and_a_citation_scaled_age_bubble_plot() -> None:
    """Break caught: charts could omit value scales or disguise a bubble plot as categories."""
    records = (
        PreviewApplicantMetric(
            applicant="First Author", age=30, academic_age=4, verified_citations=25
        ),
        PreviewApplicantMetric(
            applicant="Second Author", age=40, academic_age=14, verified_citations=100
        ),
        PreviewApplicantMetric(
            applicant="Zero Citations", age=35, academic_age=8,
            verified_citations=0, h_index=0,
        ),
    )

    html = render_internal_preview(_administrator(), simulation=True, records=records)

    assert html.count('class="plot-gridline"') >= 12
    assert 'data-plot-x="30" data-plot-y="25"' in html
    assert 'data-plot-x="40" data-plot-y="100"' in html
    assert "100 citations, h-index Missing" in html
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
    assert bubble_radii[0] == 3.0


def test_every_overview_graph_explains_its_axes_and_encodings() -> None:
    records = (
        PreviewApplicantMetric(
            applicant="Lowest Person", age=30, academic_age=4,
            verified_citations=10, h_index=2,
        ),
        PreviewApplicantMetric(
            applicant="Highest Person", age=40, academic_age=12,
            verified_citations=100, h_index=22,
        ),
    )

    html = render_internal_preview(_administrator(), simulation=True, records=records)

    assert html.count('class="chart-legend report-plot-legend"') == 3
    assert html.count("Horizontal axis:") == 3
    assert html.count("Vertical axis:") == 3
    assert html.count("Equal-sized circles represent candidates") == 2
    assert "Bubble area represents OpenAlex citations" in html
    assert "Surname labels mark the 15 candidates with the most citations" in html
    assert html.count("Light blue: h-index 2") == 3
    assert html.count("Deep blue: h-index 22") == 3
    assert html.count("Red: h-index unavailable") == 3
    assert html.count("Focus a point to read its exact values") == 3


def test_graph_legends_use_the_full_candidate_h_index_range() -> None:
    records = (
        PreviewApplicantMetric(applicant="Plotted", age=35, academic_age=8, verified_citations=20, h_index=12),
        PreviewApplicantMetric(applicant="Low without age", verified_citations=5, h_index=2),
        PreviewApplicantMetric(applicant="High without age", verified_citations=50, h_index=32),
    )

    html = render_internal_preview(_administrator(), simulation=True, records=records)

    assert html.count("Light blue: h-index 2") == 3
    assert html.count("Deep blue: h-index 32") == 3


def test_age_comparison_callouts_rank_only_records_that_can_be_plotted() -> None:
    """Break caught: excluded high-citation records could consume bubble-chart labels."""
    records = tuple(
        PreviewApplicantMetric(
            applicant=f"Excluded Author{index}", age=30 + index, verified_citations=1000 + index
        )
        for index in range(15)
    ) + (
        PreviewApplicantMetric(
            applicant="Visible Author", age=46, academic_age=12, verified_citations=10
        ),
    )

    html = render_internal_preview(_administrator(), simulation=True, records=records)
    bubble_chart = html.split("Academic age versus anagraphic age", 1)[1]

    assert ">Author</text>" in bubble_chart
