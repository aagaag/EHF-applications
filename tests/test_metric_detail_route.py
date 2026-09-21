from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from app.applicant_detail import ApplicantDetail, Publication
from app.config import Settings
from app.identity import AuthenticatedIdentity
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity


APPLICATION_ID = UUID("a7000000-0000-4000-8000-000000000001")


class _Metrics:
    def load(self, _role: str):
        return ()

    def load_detail(self, application_id: UUID, role: str) -> ApplicantDetail:
        assert application_id == APPLICATION_ID
        assert role == INTERNAL_GROUPS.trustees
        return ApplicantDetail(
            "EHF-2026-001",
            "Example Applicant",
            31,
            4.5,
            (Publication("A paper", "Journal", 2024, doi="10.1000/example", citations_by_year=((2024, 2),)),),
        )


def test_trustee_can_load_applicant_metric_detail() -> None:
    principal = AuthenticatedIdentity(
        Identity("trustee:1", "trustee@example.test", "Trustee"),
        frozenset({INTERNAL_GROUPS.trustees}),
    )
    app = create_app(
        Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: principal,
        metric_repository=_Metrics(),
    )

    response = TestClient(app, base_url="http://localhost").get(
        f"/api/internal/applicants/{APPLICATION_ID}/metrics-detail"
    )

    assert response.status_code == 200
    assert "EHF-2026-001" in response.text
    assert "Example Applicant" in response.text
    assert "Papers by year" in response.text
    assert "Citations by year" in response.text
    assert 'data-publication-url="https://doi.org/10.1000/example"' in response.text
