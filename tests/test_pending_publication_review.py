from __future__ import annotations

from uuid import UUID
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.identity import AuthenticatedIdentity
from app.navigation import INTERNAL_GROUPS


class Queue:
    def __init__(self) -> None:
        self.items = ()
        self.recorded: list[tuple[UUID, str, str, str]] = []

    def list(self, group: str):
        assert group == INTERNAL_GROUPS.administrators
        return self.items

    def record(self, publication_id: UUID, disposition: str, actor: str, group: str) -> None:
        self.recorded.append((publication_id, disposition, actor, group))


def _identity(groups: set[str]) -> AuthenticatedIdentity:
    from app.preferences import Identity

    return AuthenticatedIdentity(Identity("entra:reviewer", "reviewer@example.org", "Reviewer"), frozenset(groups))


def _client(queue: Queue, groups: set[str]) -> TestClient:
    from app.main import create_app

    return TestClient(create_app(
        Settings.from_environment({"EHF_ENVIRONMENT": "development", "EHF_ALLOWED_HOST": "testserver"}),
        identity_resolver=lambda _request: _identity(groups),
        pending_publication_review_repository=queue,
    ))


def test_pending_review_page_uses_internal_navigation_and_full_denominations() -> None:
    from app.pending_publication_review import PendingPublication

    publication_id = UUID("a1000000-0000-4000-8000-000000000001")
    queue = Queue()
    queue.items = (PendingPublication(
        publication_id, "Ada Applicant", "Ada Author; Ben Biologist", "A pending paper",
        "Journal of Tests", "12", "101-110", 2026, "10.1234/test", "https://doi.org/10.1234/test",
        "Raw source citation", "UNRESOLVED",
    ),)

    response = _client(queue, {INTERNAL_GROUPS.administrators}).get("/internal/review-pending-papers")

    assert response.status_code == 200
    assert 'href="/internal/review-pending-papers"' in response.text
    assert "Review Pending Papers" in response.text
    assert 'data-pending-publications' in response.text
    assert "/assets/pending-publication-review.js" in response.text
    payload = _client(queue, {INTERNAL_GROUPS.administrators}).get("/api/internal/pending-publications").json()
    assert payload["publications"][0]["applicantName"] == "Ada Applicant"
    assert payload["publications"][0]["rawCitation"] == "Raw source citation"
    assert payload["publications"][0]["doi"] == "10.1234/test"


def test_pending_review_decision_is_immediate_and_authorized() -> None:
    publication_id = UUID("a1000000-0000-4000-8000-000000000001")
    queue = Queue()
    client = _client(queue, {INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees})

    response = client.post(f"/api/internal/pending-publications/{publication_id}/preprint", headers={"Origin": "http://testserver"})

    assert response.status_code == 200
    assert response.json()["disposition"] == "ACCEPTED_PREPRINT"
    assert queue.recorded == [(publication_id, "ACCEPTED_PREPRINT", "entra:reviewer", INTERNAL_GROUPS.administrators)]
    denied = _client(queue, set()).get("/api/internal/pending-publications")
    assert denied.status_code == 404


def test_pending_review_rejects_cross_origin_and_unknown_decisions() -> None:
    publication_id = UUID("a1000000-0000-4000-8000-000000000001")
    client = _client(Queue(), {INTERNAL_GROUPS.trustees})

    assert client.post(f"/api/internal/pending-publications/{publication_id}/published", headers={"Origin": "https://attacker.invalid"}).status_code == 403
    assert client.post(f"/api/internal/pending-publications/{publication_id}/unknown", headers={"Origin": "http://testserver"}).status_code == 404


def test_pending_review_client_renders_applicant_text_without_html_injection() -> None:
    source = (Path(__file__).resolve().parents[1] / "public" / "assets" / "pending-publication-review.js").read_text(encoding="utf-8")
    assert ".innerHTML" not in source
    assert "textContent" in source
