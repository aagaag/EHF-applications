from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from fastapi.testclient import TestClient

from app.config import Settings
from app.calls import CallContext, InMemoryCallCatalog
from app.identity import AuthenticatedIdentity
from app.internal_preview import PreviewApplicantMetric, render_internal_preview
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity, InMemoryPreferenceRepository
from app.second_stage import SecondStageState, SqlSecondStageRepository


APPROVED = UUID("a7000000-0000-4000-8000-000000000001")
OTHER = UUID("a7000000-0000-4000-8000-000000000002")


class MemorySecondStageRepository:
    def __init__(self) -> None:
        self.state = SecondStageState(frozenset({str(APPROVED)}))
        self.writes: list[tuple[object, ...]] = []

    def load(self, call_id: UUID, actor_group: str) -> SecondStageState:
        return self.state

    def set(self, call_id: UUID, application_id: UUID, selected: bool, actor_identity: str,
            actor_group: str, entra_object_id: UUID | None) -> bool:
        self.writes.append((call_id, application_id, selected, actor_identity, actor_group, entra_object_id))
        return selected


def principal() -> AuthenticatedIdentity:
    return AuthenticatedIdentity(Identity("entra:person", "person@example.org", "Person"),
                                 frozenset({INTERNAL_GROUPS.administrators}), UUID(int=1))


CALL = CallContext(UUID(int=3), "EHF-2026", "ehf-2026", "EHF Fellowships", "EHF 2026",
                   "CLOSED", "CLOSED", "OPEN", False, "ehf-standard-v1",
                   datetime(2026, 1, 1, tzinfo=UTC), None, b"12345678")


def test_stage_switch_filters_graphs_and_rows_and_marks_promotions() -> None:
    records = (PreviewApplicantMetric("Ada", age=40, academic_age=10, verified_citations=20,
                                     application_id=str(APPROVED)),
               PreviewApplicantMetric("Bea", age=50, academic_age=12, verified_citations=30,
                                     application_id=str(OTHER)))
    html = render_internal_preview(principal(), records=records, current_call=CALL,
                                   second_stage=SecondStageState(frozenset({str(APPROVED)})),
                                       stage_two=True, advancement_editable=True)
    assert 'data-selection-stage="second" aria-current="page"' in html
    assert 'data-advancement-checkbox' not in html
    assert 'report-review-strip' not in html
    assert "Bea" not in html
    assert html.count('class="report-card"') == 3


def test_advancement_endpoint_persists_same_origin_selection() -> None:
    repository = MemorySecondStageRepository()
    client = TestClient(create_app(Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
                                   readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
                                       identity_resolver=lambda _request: principal(),
                                       second_stage_repository=repository,
                                       call_catalog=InMemoryCallCatalog((CALL,), {"ehf-2026": frozenset({INTERNAL_GROUPS.administrators})})),
                        base_url="http://localhost")
    response = client.post(f"/api/internal/calls/ehf-2026/applications/{OTHER}/second-stage",
                           json={"selected": True}, headers={"Origin": "http://localhost"})
    assert response.status_code == 200
    assert response.json() == {"selected": True}
    assert repository.writes[0][1:3] == (OTHER, True)


def test_stage_buttons_replace_live_preview_notice_above_reports() -> None:
    for stage_two in (False, True):
        html = render_internal_preview(principal(), current_call=CALL, stage_two=stage_two)
        assert 'class="preview-notice"' not in html
        assert html.count('class="selection-stage-switch"') == 1
        assert html.count('Show Second Stage Applicants') == 1
        assert html.count('Show Full Applicants') == 1
        assert html.index('class="selection-stage-switch"') < html.index('<section id="reports"')
        assert 'href="/internal/calls/ehf-2026/?stage=second"' in html
        assert 'href="/internal/calls/ehf-2026/?stage=first"' in html
        active_stage = "second" if stage_two else "first"
        assert f'data-selection-stage="{active_stage}" aria-current="page"' in html


def test_sql_second_stage_repository_calls_scoped_procedures_and_commits() -> None:
    calls: list[tuple[object, ...]] = []

    class Cursor:
        def fetchall(self):
            return [(str(APPROVED),)]

        def fetchone(self):
            return (1,)

    class Connection:
        commits = 0

        def execute(self, *args):
            calls.append(args)
            return Cursor()

        def commit(self):
            self.commits += 1

    connection = Connection()

    @contextmanager
    def factory():
        yield connection

    repository = SqlSecondStageRepository(factory)
    state = repository.load(UUID(int=3), "EHF-Administrators")
    assert state.selected(str(APPROVED))
    assert repository.set(UUID(int=3), OTHER, True, "entra:person", "EHF-Administrators", UUID(int=1))
    assert "dbo.GetCallSecondStageSelections" in str(calls[0][0])
    assert "dbo.SetCallSecondStageSelection" in str(calls[1][0])
    assert connection.commits == 1


@pytest.mark.parametrize("group", [INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees])
@pytest.mark.parametrize(
    ("advanced", "query", "expected_stage"),
    [
        (True, "", "second"),
        (False, "", "first"),
        (True, "?stage=first", "first"),
        (False, "?stage=second", "second"),
        (True, "?stage=second", "second"),
        (False, "?stage=first", "first"),
    ],
)
def test_call_workspace_defaults_to_persisted_advancement_and_allows_switching(
    group, advanced, query, expected_stage
) -> None:
    repository = MemorySecondStageRepository()
    repository.state = SecondStageState(frozenset({str(APPROVED)}) if advanced else frozenset())
    class Metrics:
        def load(self, actor_group):
            return (
                PreviewApplicantMetric("Ada", application_id=str(APPROVED)),
                PreviewApplicantMetric("Bea", application_id=str(OTHER)),
            )

    client = TestClient(create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
        identity_resolver=lambda _: replace(principal(), groups=frozenset({group})),
        preference_repository=InMemoryPreferenceRepository(),
        second_stage_repository=repository,
        metric_repository=Metrics(),
        call_catalog=InMemoryCallCatalog((CALL,), {CALL.public_slug: frozenset({group})}),
    ))
    response = client.get("/" if not query else f"/internal/calls/{CALL.public_slug}/{query}",
                          headers={"host": "localhost"})
    assert response.status_code == 200
    assert f'data-selection-stage="{expected_stage}" aria-current="page"' in response.text
    assert ("Bea" in response.text) == (expected_stage == "first")
    assert ("Ada" in response.text) == (expected_stage == "first" or advanced)


def test_stage_two_report_hides_first_round_controls_and_primary_rows_keep_review_strip() -> None:
    from app.shortlist import ShortlistState

    record = PreviewApplicantMetric("Ada", age=40, academic_age=10, verified_citations=20,
                                    application_id=str(APPROVED))
    shortlist = ShortlistState({str(APPROVED).casefold(): {"ricky": "B"}}, "adriano")
    second = render_internal_preview(principal(), records=(record,), current_call=CALL,
                                     shortlist=shortlist, second_stage=SecondStageState(frozenset({str(APPROVED)})), stage_two=True)
    table = second.split('class="report-table"', 1)[1].split("</div>", 1)[0]
    assert 'data-selection-stage="second"' in table
    assert 'data-label="Advance to second stage"' not in second
    assert "Shortlist — Ricky" not in second
    assert "data-shortlist-grade" not in second
    assert 'First-round shortlist history' in second
    assert 'Ricky: B' in second
    assert 'data-selection-stage="first"' in render_internal_preview(
        principal(), records=(record,), current_call=CALL, shortlist=shortlist
    )
    first = render_internal_preview(principal(), records=(record,), current_call=CALL,
                                    shortlist=shortlist)
    assert 'class="report-review-strip"' in first
    assert first.count('data-report-sort-select') == 1




def test_report_row_details_activation_ignores_nested_labels() -> None:
    source = (Path(__file__).resolve().parents[1] / "public/assets/shell.js").read_text(encoding="utf-8")
    selector = "input, button, a, select, textarea, summary, label"
    report_row_handlers = source.split('document.querySelectorAll("[data-report-row]")', 1)[1].split(
        'const shortlistStatus', 1
    )[0]
    assert report_row_handlers.count(f'event.target.closest("{selector}")') == 2
