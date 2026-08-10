from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import ReadinessChecks, create_app


def development_settings() -> Settings:
    return Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"})


def client_with_checks(
    sql_probe: Callable[[float], None], storage_probe: Callable[[float], None]
) -> TestClient:
    return TestClient(
        create_app(
            development_settings(),
            readiness_checks=ReadinessChecks(
                sql_probe=sql_probe,
                storage_probe=storage_probe,
                timeout_seconds=0.25,
            ),
        ),
        base_url="http://localhost",
    )


def test_liveness_does_not_call_dependency_probes() -> None:
    """Break caught: a database or document outage could make liveness fail."""
    calls: list[str] = []
    client = client_with_checks(
        lambda _: calls.append("sql"), lambda _: calls.append("storage")
    )

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}
    assert calls == []
    assert "server" not in response.text.lower()
    assert "version" not in response.text.lower()


def test_readiness_uses_bounded_injected_probes_without_disclosing_details() -> None:
    """Break caught: readiness could skip a dependency or expose its failure text."""
    timeouts: list[tuple[str, float]] = []
    client = client_with_checks(
        lambda timeout: timeouts.append(("sql", timeout)),
        lambda timeout: timeouts.append(("storage", timeout)),
    )

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert timeouts == [("sql", 0.25), ("storage", 0.25)]


def test_readiness_returns_generic_unavailable_when_a_probe_fails() -> None:
    """Break caught: operational exceptions could reveal SQL or filesystem details."""
    client = client_with_checks(
        lambda _: (_ for _ in ()).throw(RuntimeError("sql01 password=not-for-output")),
        lambda _: None,
    )

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "sql01" not in response.text
    assert "password" not in response.text


def test_health_responses_are_never_cached() -> None:
    """Break caught: monitoring answers could be stored by a browser or intermediary."""
    client = client_with_checks(lambda _: None, lambda _: None)

    response = client.get("/health/live")

    assert response.headers["cache-control"] == "no-store"


def test_default_readiness_bounds_the_sql_connection_attempt(monkeypatch, tmp_path) -> None:
    """Break caught: a failed SQL connect could outlive the health-check budget."""
    import app.main as runtime

    document_root = tmp_path / "documents"
    quarantine_root = tmp_path / "quarantine"
    document_root.mkdir()
    quarantine_root.mkdir()
    settings = Settings.from_environment(
        {
            "EHF_ALLOWED_HOST": "localhost",
            "EHF_DOCUMENT_ROOT": str(document_root),
            "EHF_QUARANTINE_ROOT": str(quarantine_root),
        }
    )
    calls: list[int] = []

    class FakeConnection:
        timeout = 0

        def execute(self, statement: str) -> None:
            assert statement == "SELECT 1"

    @contextmanager
    def fake_connect(
        supplied_settings: Settings, *, connect_timeout_seconds: int
    ) -> Iterator[FakeConnection]:
        assert supplied_settings is settings
        calls.append(connect_timeout_seconds)
        yield FakeConnection()

    monkeypatch.setattr(runtime, "connect", fake_connect)

    response = TestClient(create_app(settings), base_url="http://localhost").get("/health/ready")

    assert response.status_code == 200
    assert calls == [1]
