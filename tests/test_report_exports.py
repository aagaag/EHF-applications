"""Contracts for the authorized EHF metrics workbook and download route."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.config import Settings
from app.identity import AuthenticatedIdentity
from app.internal_preview import PreviewApplicantMetric
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity
from app.report_exports import METRIC_HEADERS, ReportExportMetadata, build_metrics_workbook


def _records() -> tuple[PreviewApplicantMetric, ...]:
    return (
        PreviewApplicantMetric(
            applicant="=DANGEROUS()",
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
        PreviewApplicantMetric(
            applicant="Zoë Example",
            degree=None,
            age=31,
            academic_age=4,
            total_papers=9,
            google_scholar_citations=125,
        ),
    )


def _metadata(group: str = INTERNAL_GROUPS.trustees) -> ReportExportMetadata:
    return ReportExportMetadata(
        actor_identity="cloudflare:stable-subject",
        actor_group=group,
        generated_at_utc=datetime(2026, 8, 10, 11, 30, tzinfo=UTC),
    )


def test_workbook_preserves_the_approved_metrics_contract_and_native_charts() -> None:
    workbook = load_workbook(BytesIO(build_metrics_workbook(_records(), _metadata())))

    assert workbook.sheetnames == ["Applicant metrics", "Charts", "Export metadata"]
    metrics = workbook["Applicant metrics"]
    header_row = next(
        row for row in metrics.iter_rows() if tuple(cell.value for cell in row) == METRIC_HEADERS
    )
    assert tuple(cell.value for cell in header_row) == METRIC_HEADERS
    assert metrics.cell(header_row[0].row + 1, 1).value == "'=DANGEROUS()"
    assert metrics.cell(header_row[0].row + 1, 3).value == 36
    assert isinstance(metrics.cell(header_row[0].row + 1, 4).value, float)
    assert metrics.cell(header_row[0].row + 1, 5).value == "NR"
    assert metrics.cell(header_row[0].row + 2, 1).value == "Zoë Example"
    assert metrics.tables
    assert metrics.auto_filter.ref is None
    assert len(workbook["Charts"]._charts) == 2
    assert all(chart.legend is None for chart in workbook["Charts"]._charts)

    all_text = "\n".join(
        str(cell.value)
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.value is not None
    ).casefold()
    for forbidden in ("email", "token", "password", "recommendation", "document path"):
        assert forbidden not in all_text


def test_export_metadata_is_bounded_and_identifies_the_export() -> None:
    workbook = load_workbook(BytesIO(build_metrics_workbook(_records(), _metadata())))
    values = {
        row[0].value: row[1].value
        for row in workbook["Export metadata"].iter_rows(min_col=1, max_col=2)
        if row[0].value
    }

    assert values["Call"] == "EHF-2026"
    assert values["Exporting identity"] == "cloudflare:stable-subject"
    assert values["Authorization group"] == "EHF-Trustees"
    assert values["Row count"] == 2
    assert values["Filters"] == "None"


class RecordingMetricRepository:
    def __init__(self) -> None:
        self.requested_roles: list[str] = []

    def load(self, canonical_group: str) -> tuple[PreviewApplicantMetric, ...]:
        self.requested_roles.append(canonical_group)
        return _records()


def _client(group: str, repository: RecordingMetricRepository) -> TestClient:
    principal = AuthenticatedIdentity(
        Identity("cloudflare:stable-subject", "person@example.org", "Example Person"),
        frozenset({group}),
    )
    return TestClient(
        create_app(
            Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
            readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
            identity_resolver=lambda _request: principal,
            metric_repository=repository,
        ),
        base_url="http://localhost",
    )


def test_authorized_download_uses_the_role_scoped_projection() -> None:
    repository = RecordingMetricRepository()
    response = _client(INTERNAL_GROUPS.administrators, repository).get(
        "/internal/reports/metrics.xlsx"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["content-disposition"] == 'attachment; filename="ehf-2026.xlsx"'
    assert "no-store" in response.headers["cache-control"]
    assert repository.requested_roles == [INTERNAL_GROUPS.administrators]
    workbook = load_workbook(BytesIO(response.content))
    assert workbook["Applicant metrics"].tables
    assert len(workbook["Charts"]._charts) == 2


def test_unauthenticated_download_fails_closed() -> None:
    app = create_app(
        Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
        readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
    )
    assert TestClient(app, base_url="http://localhost").get(
        "/internal/reports/metrics.xlsx"
    ).status_code == 404
