"""Fail-closed HTTP request validation for the EHF service."""

from __future__ import annotations

import ipaddress
import logging
import re
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.errors import error_response
from app.security_headers import is_security_header, security_headers


MAX_REQUEST_BODY_BYTES = 1_048_576
_SAFE_CORRELATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_LOGGER = logging.getLogger("ehf.http")


def is_safe_correlation_id(value: str | None) -> bool:
    """Permit only a bounded plain identifier suitable for a response header and log."""
    return value is not None and _SAFE_CORRELATION_ID.fullmatch(value) is not None


def correlation_id(headers: Mapping[str, str]) -> str:
    """Reuse a safe caller ID or create an opaque server-side identifier."""
    supplied = headers.get("x-request-id")
    return supplied if is_safe_correlation_id(supplied) else uuid.uuid4().hex


def effective_host(headers: Mapping[str, str], peer_host: str | None) -> str:
    """Return the direct Host unless a loopback Nginx peer supplied a forwarded Host."""
    host = headers.get("host", "")
    if _is_loopback(peer_host):
        host = headers.get("x-forwarded-host", host).split(",", 1)[0].strip()
    return _normalize_host(host)


def allowed_hosts(settings: Any) -> frozenset[str]:
    """Build the small host allowlist from the existing typed configuration."""
    if settings.environment == "production":
        return frozenset({"ehf.isab.science"})
    return frozenset({settings.allowed_host, "127.0.0.1", "::1"})


class SecurityMiddleware:
    """Validate host and streaming body size before a handler can consume content."""

    def __init__(self, app: Callable[..., Awaitable[None]], settings: Any) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts(settings)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[..., Awaitable[None]],
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = _headers(scope)
        request_id = correlation_id(headers)
        scope["ehf.correlation_id"] = request_id
        private = _is_private_request(scope, headers)

        if effective_host(headers, _peer_host(scope)) not in self.allowed_hosts:
            await _send_response(
                error_response(400, "invalid_host", "Invalid host", request_id, private=private), send
            )
            _log_completion(scope, 400, request_id)
            return

        if _declared_body_is_too_large(headers):
            await _send_response(
                error_response(
                    413, "request_too_large", "Request body is too large", request_id, private=private
                ),
                send,
            )
            _log_completion(scope, 413, request_id)
            return

        body_messages = await _read_bounded_body(receive)
        if body_messages is None:
            await _send_response(
                error_response(
                    413, "request_too_large", "Request body is too large", request_id, private=private
                ),
                send,
            )
            _log_completion(scope, 413, request_id)
            return

        response_status: int | None = None

        async def secure_send(message: dict[str, Any]) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = int(message["status"])
                raw_headers = list(message.get("headers", []))
                response_headers = [
                    (key, value)
                    for key, value in raw_headers
                    if key.lower() != b"x-request-id"
                    and not is_security_header(key.decode("latin-1"))
                ]
                response_headers.append((b"x-request-id", request_id.encode("latin-1")))
                response_headers.extend(
                    (name.lower().encode("latin-1"), value.encode("latin-1"))
                    for name, value in security_headers(private=private).items()
                )
                message = {
                    **message,
                    "headers": response_headers,
                }
            await send(message)

        try:
            await self.app(scope, _replay_receive(body_messages), secure_send)
        finally:
            if response_status is not None:
                _log_completion(scope, response_status, request_id)


def _headers(scope: Mapping[str, Any]) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _peer_host(scope: Mapping[str, Any]) -> str | None:
    client = scope.get("client")
    return str(client[0]) if client else None


def _is_loopback(value: str | None) -> bool:
    if value is None:
        return False
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _normalize_host(value: str) -> str:
    candidate = value.strip().lower().rstrip(".")
    if candidate.startswith("["):
        close = candidate.find("]")
        return candidate[1:close] if close > 0 else ""
    if candidate.count(":") == 1:
        candidate = candidate.split(":", 1)[0]
    if any(character.isspace() or character in "/\\\x00" for character in candidate):
        return ""
    return candidate


def _declared_body_is_too_large(headers: Mapping[str, str]) -> bool:
    value = headers.get("content-length")
    if value is None:
        return False
    try:
        return int(value) > MAX_REQUEST_BODY_BYTES
    except ValueError:
        return False


def _is_private_request(scope: Mapping[str, Any], headers: Mapping[str, str]) -> bool:
    return bool(
        headers.get("authorization")
        or headers.get("cookie")
        or str(scope.get("path", "")).startswith(("/applicant", "/internal"))
    )


async def _read_bounded_body(
    receive: Callable[..., Awaitable[dict[str, Any]]]
) -> list[dict[str, Any]] | None:
    messages: list[dict[str, Any]] = []
    total = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            messages.append(message)
            return messages
        body = bytes(message.get("body", b""))
        total += len(body)
        if total > MAX_REQUEST_BODY_BYTES:
            return None
        messages.append(message)
        if not message.get("more_body", False):
            return messages


def _replay_receive(
    messages: list[dict[str, Any]]
) -> Callable[..., Awaitable[dict[str, Any]]]:
    remaining = deque(messages)

    async def replay() -> dict[str, Any]:
        if remaining:
            return remaining.popleft()
        return {"type": "http.request", "body": b"", "more_body": False}

    return replay


async def _send_response(response: Any, send: Callable[..., Awaitable[None]]) -> None:
    await response({"type": "http"}, _empty_receive, send)


async def _empty_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


def _log_completion(scope: Mapping[str, Any], status: int, request_id: str) -> None:
    supplied_method = str(scope.get("method", "")).upper()
    method = supplied_method if supplied_method in {
        "GET",
        "HEAD",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    } else "OTHER"
    _LOGGER.info(
        "http request complete method=%s status=%d correlation_id=%s",
        method,
        status,
        request_id,
    )
