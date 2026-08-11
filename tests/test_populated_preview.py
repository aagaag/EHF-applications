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
    assert html.count('role="img"') == 2
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
        r'<circle class="plot-point"[^>]+fill="(#[0-9A-F]{6})"', html
    )
    callout_labels = re.findall(
        r'<text class="plot-callout-label"[^>]*>([^<]+)</text>', html
    )

    assert len(point_colors) == 36
    assert len(set(point_colors[:18])) == 18
    assert point_colors[18:] == point_colors[:18]
    assert len(callout_labels) == 30
    assert sorted(callout_labels) == sorted(
        [f"Surname{index:02d}" for index in range(3, 18)] * 2
    )
    for index in range(3):
        assert f">Surname{index:02d}</text>" not in html
    assert html.count('class="plot-point" tabindex="0" aria-label=') == 36
    assert 'aria-label="Given Surname17: age 47, 17 citations"' in html
