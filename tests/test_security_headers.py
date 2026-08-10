from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import Response
from fastapi.testclient import TestClient

from app.config import Settings
from app.http import MAX_REQUEST_BODY_BYTES, effective_host, is_safe_correlation_id
from app.main import ReadinessChecks, create_app


def client() -> TestClient:
    return TestClient(
        create_app(
            Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
            readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
        ),
        base_url="http://localhost",
    )


def test_all_responses_receive_restrictive_security_headers_and_no_store() -> None:
    """Break caught: a future route could omit a browser security control."""
    response = client().get("/health/live")

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_authenticated_requests_use_private_no_store() -> None:
    """Break caught: an authenticated response could be shared by a cache."""
    response = client().get("/health/live", headers={"Authorization": "Bearer secret"})

    assert response.headers["cache-control"] == "private, no-store"


def test_invalid_hosts_are_rejected_before_routes_run() -> None:
    """Break caught: Host-header attacks could reach the application."""
    response = client().get("/health/live", headers={"Host": "attacker.example"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_host"


def test_forwarded_host_is_honoured_only_for_a_loopback_proxy() -> None:
    """Break caught: a direct client could spoof Nginx forwarding headers."""
    headers = {"host": "127.0.0.1", "x-forwarded-host": "ehf.isab.science"}

    assert effective_host(headers, "127.0.0.1") == "ehf.isab.science"
    assert effective_host(headers, "::1") == "ehf.isab.science"
    assert effective_host(headers, "198.51.100.10") == "127.0.0.1"


def test_correlation_ids_are_bounded_and_spoof_resistant() -> None:
    """Break caught: log correlation could accept control characters or unbounded values."""
    accepted = "request-2026_08.10"
    rejected = ("x" * 65, "two words", "bad\r\nheader", "../escape")

    assert is_safe_correlation_id(accepted)
    assert not any(is_safe_correlation_id(value) for value in rejected)

    response = client().get("/health/live", headers={"X-Request-ID": accepted})
    generated = client().get("/health/live", headers={"X-Request-ID": "bad\r\nheader"})

    assert response.headers["x-request-id"] == accepted
    assert is_safe_correlation_id(generated.headers["x-request-id"])
    assert generated.headers["x-request-id"] != "bad\r\nheader"


def test_oversized_declared_and_streamed_bodies_are_rejected_before_routing() -> None:
    """Break caught: chunked or dishonest uploads could bypass the body-size limit."""
    oversized = b"x" * (MAX_REQUEST_BODY_BYTES + 1)
    app = create_app(
        Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
        readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
    )

    declared = TestClient(app, base_url="http://localhost").post(
        "/not-a-route", content=oversized
    )

    assert declared.status_code == 413
    assert declared.json()["error"]["code"] == "request_too_large"

    async def chunks() -> AsyncIterator[bytes]:
        yield b"x" * (MAX_REQUEST_BODY_BYTES // 2)
        yield b"x" * (MAX_REQUEST_BODY_BYTES // 2 + 1)

    async def exercise_stream() -> int:
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as session:
            response = await session.post("/not-a-route", content=chunks())
        return response.status_code

    assert asyncio.run(exercise_stream()) == 413


def test_misleading_content_length_cannot_bypass_streaming_body_limit() -> None:
    """Break caught: a small claimed length could let an oversized body reach a route."""
    app = create_app(
        Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
        readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
    )

    async def exercise_misleading_length() -> list[dict[str, object]]:
        messages = iter(
            [
                {
                    "type": "http.request",
                    "body": b"x" * (MAX_REQUEST_BODY_BYTES + 1),
                    "more_body": False,
                }
            ]
        )
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return next(messages)

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/not-a-route",
                "raw_path": b"/not-a-route",
                "query_string": b"",
                "headers": [(b"host", b"localhost"), (b"content-length", b"1")],
                "client": ("127.0.0.1", 50000),
                "server": ("localhost", 80),
            },
            receive,
            send,
        )
        return sent

    sent = asyncio.run(exercise_misleading_length())

    assert sent[0]["status"] == 413


def test_declared_oversized_body_is_rejected_without_reading_the_stream() -> None:
    """Break caught: a known oversized request could still consume upload bytes."""
    app = create_app(
        Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
        readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
    )

    async def exercise_declared_oversize() -> list[dict[str, object]]:
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            raise AssertionError("known oversized request body must not be read")

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/not-a-route",
                "raw_path": b"/not-a-route",
                "query_string": b"",
                "headers": [
                    (b"host", b"localhost"),
                    (b"content-length", str(MAX_REQUEST_BODY_BYTES + 1).encode()),
                ],
                "client": ("127.0.0.1", 50000),
                "server": ("localhost", 80),
            },
            receive,
            send,
        )
        return sent

    sent = asyncio.run(exercise_declared_oversize())

    assert sent[0]["status"] == 413


def test_security_headers_preserve_multiple_set_cookie_headers() -> None:
    """Break caught: header hardening could silently discard a future session cookie."""
    app = create_app(
        Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
        readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
    )

    @app.get("/test-cookies")
    def test_cookies() -> Response:
        response = Response("ok")
        response.set_cookie("first", "one", httponly=True)
        response.set_cookie("second", "two", httponly=True)
        return response

    response = TestClient(app, base_url="http://localhost").get("/test-cookies")

    assert len(response.headers.get_list("set-cookie")) == 2
