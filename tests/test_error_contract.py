from __future__ import annotations

import logging
import asyncio
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import correlation_id
from app.http import SecurityMiddleware, is_safe_correlation_id
from app.main import ReadinessChecks, create_app


def application() -> TestClient:
    app = create_app(
        Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
        readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
    )

    @app.get("/test-http-error")
    def test_http_error() -> None:
        raise HTTPException(status_code=422, detail="applicant data must not escape")

    @app.get("/test-unhandled-error")
    def test_unhandled_error() -> None:
        raise RuntimeError("server-01 /private/document.pdf token=not-for-output")

    return TestClient(app, base_url="http://localhost", raise_server_exceptions=False)


def test_unknown_routes_have_a_stable_redacted_json_error_envelope() -> None:
    """Break caught: framework defaults could disclose a route or implementation detail."""
    response = application().get("/not-a-route")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Not found",
            "correlation_id": response.headers["x-request-id"],
        }
    }


def test_application_errors_are_redacted_and_keep_the_correlation_id() -> None:
    """Break caught: exception messages could disclose applicant or infrastructure data."""
    client = application()

    handled = client.get("/test-http-error")
    unhandled = client.get("/test-unhandled-error")

    assert handled.status_code == 422
    assert handled.json()["error"] == {
        "code": "invalid_request",
        "message": "Request could not be processed",
        "correlation_id": handled.headers["x-request-id"],
    }
    assert unhandled.status_code == 500
    assert unhandled.json()["error"] == {
        "code": "internal_error",
        "message": "The service could not process this request",
        "correlation_id": unhandled.headers["x-request-id"],
    }
    assert "server-01" not in unhandled.text
    assert "document.pdf" not in unhandled.text
    assert "token=" not in unhandled.text


def test_request_logging_excludes_authorization_cookies_and_bodies(caplog) -> None:
    """Break caught: a diagnostic log could leak credentials or applicant data."""
    caplog.set_level(logging.INFO, logger="ehf.http")
    client = application()

    client.post(
        "/not-a-route",
        content=b"applicant-private-answer",
        headers={
            "Authorization": "Bearer authorization-not-for-logs",
            "Cookie": "session=cookie-not-for-logs",
        },
    )

    output = caplog.text
    assert "authorization-not-for-logs" not in output
    assert "cookie-not-for-logs" not in output
    assert "applicant-private-answer" not in output
    assert "correlation_id=" in output


def test_error_fallback_correlation_id_is_safe_when_an_outer_boundary_is_missing() -> None:
    """Break caught: an early framework error could emit an unusable fixed correlation ID."""
    request = SimpleNamespace(scope={})

    resolved = correlation_id(request)

    assert is_safe_correlation_id(resolved)
    assert resolved != "unknown"


def test_default_client_receives_redacted_500_without_the_original_exception(caplog) -> None:
    """Break caught: ServerErrorMiddleware could re-raise a route exception to a default client."""
    caplog.set_level(logging.INFO, logger="ehf.http")
    app = create_app(
        Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
        readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
    )

    @app.get("/outer-exception")
    def outer_exception() -> None:
        raise RuntimeError("private/path token=not-for-logs")

    response = TestClient(app, base_url="http://localhost").get(
        "/outer-exception",
        headers={"Authorization": "Bearer secret-not-for-logs"},
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "private/path" not in caplog.text
    assert "secret-not-for-logs" not in caplog.text


def test_exception_after_response_start_is_not_reraised_or_sent_twice() -> None:
    """Break caught: a late route failure could leak through a second response or exception."""
    async def failing_app(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("late private failure")

    middleware = SecurityMiddleware(
        failing_app,
        Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
    )

    async def exercise() -> list[dict[str, object]]:
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        await middleware(
            {
                "type": "http",
                "method": "GET",
                "path": "/late-failure",
                "headers": [(b"host", b"localhost")],
                "client": ("127.0.0.1", 50000),
            },
            receive,
            send,
        )
        return sent

    sent = asyncio.run(exercise())

    assert [message["type"] for message in sent].count("http.response.start") == 1
    assert sent[-1] == {"type": "http.response.body", "body": b"", "more_body": False}
