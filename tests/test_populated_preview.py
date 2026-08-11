"""Development preview contract for real, administrator-only register data."""

from __future__ import annotations

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
