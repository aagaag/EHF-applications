from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from fastapi.testclient import TestClient

from app.config import Settings
from app.identity import AuthenticatedIdentity
from app.internal_preview import PreviewApplicantMetric, render_internal_preview
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity
from app.shortlist import (
    ADRIANO_ENTRA_OBJECT_ID,
    RICKY_ENTRA_OBJECT_ID,
    ShortlistState,
    SqlShortlistRepository,
)


APPLICATION_ID = UUID("a7000000-0000-4000-8000-000000000001")


class MemoryShortlistRepository:
    def __init__(self) -> None:
        self.state = ShortlistState({str(APPLICATION_ID): frozenset({"ricky"})}, "adriano")
        self.writes: list[tuple[object, ...]] = []

    def load(self, actor_identity: str, actor_group: str, entra_object_id: UUID | None) -> ShortlistState:
        del actor_identity, actor_group, entra_object_id
        return self.state

    def set(self, application_id: UUID, trustee_code: str, selected: bool, actor_identity: str, actor_group: str, entra_object_id: UUID | None) -> bool:
        self.writes.append((application_id, trustee_code, selected, actor_identity, actor_group, entra_object_id))
        return selected


def _principal(oid: UUID, *groups: str) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        Identity("entra:person", "person@example.org", "Person"),
        frozenset(groups),
        oid,
    )


def _settings() -> Settings:
    return Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"})


def _client(principal: AuthenticatedIdentity, shortlist: object) -> TestClient:
    return TestClient(
        create_app(
            _settings(),
            readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
            identity_resolver=lambda _request: principal,
            shortlist_repository=shortlist,
        ),
        base_url="http://localhost",
    )


def test_report_renders_grouped_shortlist_columns_and_only_identity_owned_checkbox() -> None:
    record = PreviewApplicantMetric(
        applicant="Ada Researcher", application_id=str(APPLICATION_ID), h_index=4
    )
    state = ShortlistState({str(APPLICATION_ID): frozenset({"ricky"})}, "adriano")

    html = render_internal_preview(
        _principal(ADRIANO_ENTRA_OBJECT_ID, INTERNAL_GROUPS.administrators),
        records=(record,),
        shortlist=state,
    )

    assert 'class="report-shortlist-group" role="columnheader" aria-colspan="3">Shortlist' in html
    for trustee in ("Ricky", "Magda", "Adriano"):
        assert f'role="columnheader">{trustee}</span>' in html
        assert f'data-label="Shortlist — {trustee}"' in html
    assert 'data-shortlist-owner="ricky" checked disabled' in html
    assert 'data-shortlist-owner="magda" disabled' in html
    assert 'data-shortlist-owner="adriano"' in html
    assert 'data-shortlist-owner="adriano" disabled' not in html
    assert 'data-shortlist-status role="status" aria-live="polite"' in html


def test_adriano_admin_login_can_save_only_adriano_column_and_requires_same_origin() -> None:
    repository = MemoryShortlistRepository()
    client = _client(
        _principal(ADRIANO_ENTRA_OBJECT_ID, INTERNAL_GROUPS.administrators), repository
    )
    path = f"/api/internal/applicants/{APPLICATION_ID}/shortlist/adriano"

    assert client.post(path, json={"selected": True}).status_code == 404
    saved = client.post(path, json={"selected": True}, headers={"Origin": "http://localhost"})
    assert saved.status_code == 200
    assert saved.json() == {"selected": True}
    assert repository.writes[0][0:3] == (APPLICATION_ID, "adriano", True)
    assert repository.writes[0][-1] == ADRIANO_ENTRA_OBJECT_ID


def test_route_rejects_another_column_and_non_boolean_or_extra_payload() -> None:
    repository = MemoryShortlistRepository()
    client = _client(
        _principal(ADRIANO_ENTRA_OBJECT_ID, INTERNAL_GROUPS.trustees), repository
    )
    headers = {"Origin": "http://localhost"}

    assert client.post(
        f"/api/internal/applicants/{APPLICATION_ID}/shortlist/ricky",
        json={"selected": True}, headers=headers,
    ).status_code == 404
    assert client.post(
        f"/api/internal/applicants/{APPLICATION_ID}/shortlist/adriano",
        json={"selected": 1}, headers=headers,
    ).status_code == 422
    assert client.post(
        f"/api/internal/applicants/{APPLICATION_ID}/shortlist/adriano",
        json={"selected": True, "extra": 1}, headers=headers,
    ).status_code == 422
    assert repository.writes == []


def test_sql_repository_uses_only_bounded_procedures_and_commits_writes() -> None:
    calls: list[tuple[object, ...]] = []

    class Cursor:
        def __init__(self, rows: list[tuple[object, ...]]) -> None:
            self.rows = rows

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.rows

        def fetchone(self) -> tuple[object, ...] | None:
            return self.rows[0] if self.rows else None

    class Connection:
        def __init__(self) -> None:
            self.commits = 0

        def execute(self, *arguments: object) -> Cursor:
            calls.append(arguments)
            if "GetInternal" in str(arguments[0]):
                return Cursor([(str(APPLICATION_ID), "ricky", True)])
            return Cursor([(True,)])

        def commit(self) -> None:
            self.commits += 1

    connection = Connection()
    repository = SqlShortlistRepository(lambda: connection)
    state = repository.load("entra:person", INTERNAL_GROUPS.trustees, RICKY_ENTRA_OBJECT_ID)
    result = repository.set(
        APPLICATION_ID, "ricky", False, "entra:person",
        INTERNAL_GROUPS.trustees, RICKY_ENTRA_OBJECT_ID,
    )

    assert state.selected(str(APPLICATION_ID), "ricky") is True
    assert state.editable_trustee == "ricky"
    assert result is True
    assert "dbo.GetInternalShortlistSelections" in str(calls[0][0])
    assert "dbo.SetInternalShortlistSelection" in str(calls[1][0])
    assert connection.commits == 1
