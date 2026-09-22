from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.calls import CallContext, CallSummary, InMemoryCallCatalog
from app.config import Settings
from app.identity import AuthenticatedIdentity
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import (
    CallNavigationPreference,
    Identity,
    InMemoryPreferenceRepository,
)


CALL_2026 = CallContext(
    fellowship_call_id=UUID("26000000-0000-4000-8000-000000000001"),
    call_code="EHF-2026",
    public_slug="ehf-2026",
    display_name="Ernst Hadorn Transitional Fellowships 2026",
    compact_title="EHF 2026",
    call_status="OPEN",
    applicant_review_status="OPEN",
    internal_selection_status="OPEN",
    invitations_enabled=False,
    analysis_profile_code="ehf-standard-v1",
    application_deadline_utc=datetime(2026, 12, 31, tzinfo=UTC),
    applicant_review_deadline_utc=None,
    row_version=b"12345678",
)
CALL_2027 = CallContext(
    fellowship_call_id=UUID("27000000-0000-4000-8000-000000000001"),
    call_code="EHF-2027",
    public_slug="ehf-2027",
    display_name="Ernst Hadorn Fellowships with a deliberately long 2027 title",
    compact_title="EHF 2027",
    call_status="DRAFT",
    applicant_review_status="DISABLED",
    internal_selection_status="DISABLED",
    invitations_enabled=False,
    analysis_profile_code="ehf-standard-v1",
    application_deadline_utc=datetime(2027, 12, 31, tzinfo=UTC),
    applicant_review_deadline_utc=None,
    row_version=b"abcdefgh",
)


def _identity(group: str):
    principal = AuthenticatedIdentity(
        Identity("test:caller", "caller@example.invalid", "Test caller"),
        frozenset({group}),
    )
    return lambda _request: principal


def _client_and_preferences(
    group: str,
    preference: CallNavigationPreference | None = None,
) -> tuple[TestClient, InMemoryPreferenceRepository]:
    summaries = (
        CallSummary(CALL_2026, 38, datetime(2026, 9, 20, tzinfo=UTC), None, 3, "ACTIVE"),
        CallSummary(CALL_2027, 0, None, None, 0, "NOT_CONFIGURED"),
    )
    catalog = InMemoryCallCatalog(
        (CALL_2026, CALL_2027),
        {
            "ehf-2026": frozenset({INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees}),
            "ehf-2027": frozenset({INTERNAL_GROUPS.administrators}),
        },
        summaries=summaries,
    )
    repository = InMemoryPreferenceRepository()
    if preference is not None:
        repository.save_call_navigation(
            Identity("test:caller", "caller@example.invalid", "Test caller"), preference
        )
    client = TestClient(
        create_app(
            Settings.from_environment({}),
            call_catalog=catalog,
            identity_resolver=_identity(group),
            preference_repository=repository,
            readiness_checks=ReadinessChecks(
                sql_probe=lambda _timeout: None,
                storage_probe=lambda _timeout: None,
            ),
        )
    )
    return client, repository


def _client(group: str) -> TestClient:
    return _client_and_preferences(group)[0]


def test_administrator_call_inventory_and_sidebar_show_every_authorized_call() -> None:
    """Break caught: the database call catalog could remain absent from the left navigation."""
    response = _client(INTERNAL_GROUPS.administrators).get(
        "/internal/calls/", headers={"host": "localhost"}
    )

    assert response.status_code == 200
    assert 'href="/internal/calls/ehf-2026/"' in response.text
    assert 'href="/internal/calls/ehf-2027/"' in response.text
    assert "38 applicants" in response.text
    assert "Create call" in response.text


def test_trustee_inventory_hides_ungranted_calls_and_administration() -> None:
    """Break caught: call navigation could disclose an unauthorized draft call."""
    response = _client(INTERNAL_GROUPS.trustees).get(
        "/internal/calls/", headers={"host": "localhost"}
    )

    assert response.status_code == 200
    assert 'href="/internal/calls/ehf-2026/"' in response.text
    assert "ehf-2027" not in response.text
    assert "Create call" not in response.text


def test_unknown_call_is_neutral_and_never_falls_back_to_2026() -> None:
    """Break caught: an invalid call URL could silently expose the legacy workspace."""
    response = _client(INTERNAL_GROUPS.administrators).get(
        "/internal/calls/ehf-2099/",
        follow_redirects=False,
        headers={"host": "localhost"},
    )

    assert response.status_code == 404
    assert response.headers.get("location") is None


def test_internal_home_resumes_the_last_authorized_call_by_default() -> None:
    """Break caught: returning users could lose their last application-round context."""
    client, _repository = _client_and_preferences(
        INTERNAL_GROUPS.administrators,
        CallNavigationPreference(
            "resume-last-opened", CALL_2026.fellowship_call_id
        ),
    )

    response = client.get(
        "/internal/", follow_redirects=False, headers={"host": "localhost"}
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/internal/calls/ehf-2026/"


def test_latest_deadline_mode_chooses_the_authorized_call_with_latest_deadline() -> None:
    """Break caught: latest mode could use insertion order instead of the call deadline."""
    client, _repository = _client_and_preferences(
        INTERNAL_GROUPS.administrators,
        CallNavigationPreference(
            "latest-application-deadline", CALL_2026.fellowship_call_id
        ),
    )

    response = client.get(
        "/internal/", follow_redirects=False, headers={"host": "localhost"}
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/internal/calls/ehf-2027/"


def test_opening_a_call_updates_only_the_current_identity_last_opened_call() -> None:
    """Break caught: selecting a round could fail to persist the user's context."""
    client, repository = _client_and_preferences(INTERNAL_GROUPS.administrators)

    response = client.get(
        "/internal/calls/ehf-2027/", headers={"host": "localhost"}
    )

    assert response.status_code == 200
    saved = repository.load_call_navigation(
        Identity("test:caller", "caller@example.invalid", "Test caller")
    )
    assert saved.mode == "resume-last-opened"
    assert saved.last_fellowship_call_id == CALL_2027.fellowship_call_id


def test_legacy_round_keeps_the_applicant_report_inside_the_new_call_shell() -> None:
    client, _repository = _client_and_preferences(INTERNAL_GROUPS.administrators)

    response = client.get(
        "/internal/calls/ehf-2026/", headers={"host": "localhost"}
    )

    assert response.status_code == 200
    assert 'aria-label="2026 applicant metrics"' in response.text
    assert 'href="/internal/calls/ehf-2027/"' in response.text
    assert 'aria-current="page"><span>EHF 2026</span>' in response.text
    assert "Full application PDF is available" not in response.text
    assert "reviewed supporting PDF is available" not in response.text


def test_settings_can_switch_default_call_behavior() -> None:
    """Break caught: the Settings choice could be cosmetic rather than server-backed."""
    client, repository = _client_and_preferences(INTERNAL_GROUPS.administrators)

    response = client.post(
        "/api/internal/call-navigation-preference",
        json={"mode": "latest-application-deadline"},
        headers={"host": "localhost", "origin": "http://localhost"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "latest-application-deadline"
    assert repository.load_call_navigation(
        Identity("test:caller", "caller@example.invalid", "Test caller")
    ).mode == "latest-application-deadline"


def test_administrator_can_create_a_draft_call_from_the_inventory() -> None:
    """Break caught: the visible Create call form could be a nonfunctional control."""
    client, _repository = _client_and_preferences(INTERNAL_GROUPS.administrators)

    response = client.post(
        "/api/internal/calls",
        json={
            "callCode": "EHF-2028",
            "publicSlug": "ehf-2028",
            "displayName": "Ernst Hadorn Fellowships 2028",
            "compactTitle": "EHF 2028",
            "applicationDeadlineUtc": "2028-12-31T23:00:00Z",
        },
        headers={"host": "localhost", "origin": "http://localhost"},
    )

    assert response.status_code == 201
    assert response.json() == {"location": "/internal/calls/ehf-2028/"}
    assert client.get(
        "/internal/calls/ehf-2028/", headers={"host": "localhost"}
    ).status_code == 200


def test_trustee_cannot_create_a_call() -> None:
    client, _repository = _client_and_preferences(INTERNAL_GROUPS.trustees)

    response = client.post(
        "/api/internal/calls",
        json={
            "callCode": "EHF-2028",
            "publicSlug": "ehf-2028",
            "displayName": "Ernst Hadorn Fellowships 2028",
            "compactTitle": "EHF 2028",
            "applicationDeadlineUtc": "2028-12-31T23:00:00Z",
        },
        headers={"host": "localhost", "origin": "http://localhost"},
    )

    assert response.status_code == 404
