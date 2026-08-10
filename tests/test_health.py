from __future__ import annotations

import asyncio
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace

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
        supplied_settings: Settings,
        *,
        connect_timeout_seconds: int,
        query_timeout_seconds: int,
    ) -> Iterator[FakeConnection]:
        assert supplied_settings is settings
        assert query_timeout_seconds == 1
        calls.append(connect_timeout_seconds)
        yield FakeConnection()

    monkeypatch.setattr(runtime, "connect", fake_connect)

    response = TestClient(create_app(settings), base_url="http://localhost").get("/health/ready")

    assert response.status_code == 200
    assert calls == [1]


def test_readiness_enforces_a_wall_clock_deadline_off_the_event_loop() -> None:
    """Break caught: a ten-millisecond readiness budget could wait for a slow probe."""
    import httpx

    def slow_probe(_: float) -> None:
        time.sleep(0.2)

    app = create_app(
        development_settings(),
        readiness_checks=ReadinessChecks(
            sql_probe=slow_probe,
            storage_probe=lambda _: None,
            timeout_seconds=0.01,
            max_concurrency=1,
        ),
    )

    async def exercise() -> tuple[int, dict[str, str], float]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as session:
            started = time.perf_counter()
            response = await session.get("/health/ready")
            elapsed = time.perf_counter() - started
        return response.status_code, response.json(), elapsed

    status, payload, elapsed = asyncio.run(exercise())

    assert status == 503
    assert payload == {"status": "unavailable"}
    assert elapsed < 0.12


def test_timed_out_readiness_work_keeps_the_gate_saturated_until_it_finishes() -> None:
    """Break caught: repeated timeouts could create unlimited still-running probe threads."""
    import httpx

    entered = threading.Event()

    def slow_probe(_: float) -> None:
        entered.set()
        time.sleep(0.2)

    app = create_app(
        development_settings(),
        readiness_checks=ReadinessChecks(
            sql_probe=slow_probe,
            storage_probe=lambda _: None,
            timeout_seconds=0.01,
            max_concurrency=1,
        ),
    )

    async def exercise() -> tuple[int, float, int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as session:
            first = asyncio.create_task(session.get("/health/ready"))
            assert await asyncio.to_thread(entered.wait, 0.1)
            started = time.perf_counter()
            second = await session.get("/health/ready")
            elapsed = time.perf_counter() - started
            first_response = await first
        return first_response.status_code, elapsed, second.status_code

    first_status, elapsed, second_status = asyncio.run(exercise())

    assert first_status == 503
    assert second_status == 503
    assert elapsed < 0.12


def test_late_timed_out_probe_errors_are_consumed_without_logging_details() -> None:
    """Break caught: a late background probe error could escape the redacted readiness boundary."""
    import httpx

    def late_failure(_: float) -> None:
        time.sleep(0.03)
        raise RuntimeError("probe-secret-not-for-output")

    app = create_app(
        development_settings(),
        readiness_checks=ReadinessChecks(
            sql_probe=late_failure,
            storage_probe=lambda _: None,
            timeout_seconds=0.01,
            max_concurrency=1,
        ),
    )

    async def exercise() -> tuple[int, list[str]]:
        loop = asyncio.get_running_loop()
        diagnostics: list[str] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(
            lambda _loop, context: diagnostics.append(str(context.get("exception") or context))
        )
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as session:
                response = await session.get("/health/ready")
            await asyncio.sleep(0.08)
        finally:
            loop.set_exception_handler(previous_handler)
        return response.status_code, diagnostics

    status, diagnostics = asyncio.run(exercise())

    assert status == 503
    assert "probe-secret-not-for-output" not in str(diagnostics)


def test_sql_query_timeout_is_set_before_session_options(monkeypatch) -> None:
    """Break caught: session setup could run without the readiness query timeout."""
    from app import db

    observed_timeouts: list[int] = []

    class FakeDriverError(Exception):
        pass

    class FakeConnection:
        timeout = 0

        def execute(self, statement: str) -> None:
            observed_timeouts.append(self.timeout)

        def close(self) -> None:
            return None

    fake_driver = SimpleNamespace(
        Error=FakeDriverError,
        connect=lambda *_args, **_kwargs: FakeConnection(),
    )
    monkeypatch.setitem(sys.modules, "pyodbc", fake_driver)

    with db.connect(
        SimpleNamespace(read_sql_credential=lambda: "test-password"),
        query_timeout_seconds=2,
    ):
        pass

    assert observed_timeouts == [2]
