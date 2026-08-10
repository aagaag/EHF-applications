"""Fail-closed HTTP request validation for the EHF service."""

from __future__ import annotations

from dataclasses import dataclass
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
MAX_DECLARED_CONTENT_LENGTH = 9_223_372_036_854_775_807
_SAFE_CORRELATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_AUTHORITY_HOSTNAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")
_BRACKETED_IPV6 = re.compile(r"\[([0-9A-Fa-f:.]+)\](?::([0-9]+))?\Z")
_DECIMAL = re.compile(r"[0-9]+\Z")
_LOGGER = logging.getLogger("ehf.http")


def is_safe_correlation_id(value: str | None) -> bool:
    """Permit only a bounded plain identifier suitable for a response header and log."""
    return value is not None and _SAFE_CORRELATION_ID.fullmatch(value) is not None


def correlation_id(headers: Mapping[str, str]) -> str:
    """Reuse a safe caller ID or create an opaque server-side identifier."""
    supplied = headers.get("x-request-id")
    return supplied if is_safe_correlation_id(supplied) else uuid.uuid4().hex


def effective_host(headers: Mapping[str, str], peer_host: str | None) -> str:
    """Parse only the raw Host authority; forwarding headers never alter host validation."""
    return _parse_authority(headers.get("host", "")) or ""


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

        raw_headers = list(scope.get("headers", []))
        headers = _headers(raw_headers)
        request_id = correlation_id(headers)
        scope["ehf.correlation_id"] = request_id
        private = _is_private_request(scope, raw_headers)

        host = _raw_host(raw_headers)
        if host is None or host not in self.allowed_hosts:
            await _send_response(
                error_response(400, "invalid_host", "Invalid host", request_id, private=private), send
            )
            _log_completion(scope, 400, request_id)
            return

        try:
            declared_length = _content_length(raw_headers)
        except ValueError:
            await _send_response(
                error_response(400, "invalid_request", "Request could not be processed", request_id, private=private),
                send,
            )
            _log_completion(scope, 400, request_id)
            return

        if declared_length is not None and declared_length > MAX_REQUEST_BODY_BYTES:
            await _send_response(
                error_response(
                    413, "request_too_large", "Request body is too large", request_id, private=private
                ),
                send,
            )
            _log_completion(scope, 413, request_id)
            return

        buffered_body = await _read_bounded_body(receive)
        if buffered_body is None:
            await _send_response(
                error_response(
                    413, "request_too_large", "Request body is too large", request_id, private=private
                ),
                send,
            )
            _log_completion(scope, 413, request_id)
            return
        if buffered_body.disconnected or (
            declared_length is not None and buffered_body.length != declared_length
        ):
            await _send_response(
                error_response(400, "invalid_request", "Request could not be processed", request_id, private=private),
                send,
            )
            _log_completion(scope, 400, request_id)
            return

        response_status: int | None = None
        response_complete = False

        async def secure_send(message: dict[str, Any]) -> None:
            nonlocal response_complete, response_status
            if message["type"] == "http.response.start":
                if response_status is not None:
                    return
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
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                response_complete = True
            await send(message)

        try:
            await self.app(scope, _replay_receive(buffered_body.messages), secure_send)
        except Exception:
            if response_status is None:
                await _send_response(
                    error_response(
                        500,
                        "internal_error",
                        "The service could not process this request",
                        request_id,
                        private=private,
                    ),
                    secure_send,
                )
            elif not response_complete:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            if response_status is not None:
                _log_completion(scope, response_status, request_id)


def _headers(raw_headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in raw_headers
    }


def _raw_host(raw_headers: list[tuple[bytes, bytes]]) -> str | None:
    values = [value.decode("latin-1") for key, value in raw_headers if key.lower() == b"host"]
    if len(values) != 1:
        return None
    return _parse_authority(values[0])


def _parse_authority(value: str) -> str | None:
    if not value or any(character.isspace() or ord(character) < 32 or character in "/\\,@" for character in value):
        return None
    bracketed = _BRACKETED_IPV6.fullmatch(value)
    if bracketed is not None:
        host, port = bracketed.groups()
        try:
            parsed = ipaddress.ip_address(host)
        except ValueError:
            return None
        return str(parsed) if parsed.version == 6 and _valid_port(port) else None
    if value.startswith("[") or "]" in value:
        return None
    host, separator, port = value.partition(":")
    if separator and (":" in port or not _valid_port(port)):
        return None
    terminal_hostname_dot = host.endswith(".")
    if terminal_hostname_dot:
        host = host[:-1]
        if host.endswith("."):
            return None
    if not host:
        return None
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        parsed = None
    if parsed is not None:
        return str(parsed) if parsed.version == 4 and not terminal_hostname_dot else None
    labels = host.split(".")
    if not all(_AUTHORITY_HOSTNAME.fullmatch(label) for label in labels):
        return None
    return host.lower()


def _valid_port(value: str | None) -> bool:
    if value is None:
        return True
    if _DECIMAL.fullmatch(value) is None:
        return False
    return 1 <= int(value) <= 65535


def _content_length(raw_headers: list[tuple[bytes, bytes]]) -> int | None:
    values = [
        value.decode("latin-1")
        for key, value in raw_headers
        if key.lower() == b"content-length"
    ]
    if not values:
        return None
    if len(values) != 1 or _DECIMAL.fullmatch(values[0]) is None:
        raise ValueError("malformed content length")
    length = int(values[0])
    if length > MAX_DECLARED_CONTENT_LENGTH:
        raise ValueError("content length overflows")
    return length


def _is_private_request(scope: Mapping[str, Any], raw_headers: list[tuple[bytes, bytes]]) -> bool:
    return bool(
        any(
            key.lower() in {b"authorization", b"cookie"}
            for key, _value in raw_headers
        )
        or str(scope.get("path", "")).startswith(("/applicant", "/internal"))
    )


async def _read_bounded_body(
    receive: Callable[..., Awaitable[dict[str, Any]]]
) -> "BufferedBody | None":
    messages: list[dict[str, Any]] = []
    total = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return BufferedBody(messages, total, disconnected=True)
        if message["type"] != "http.request":
            return BufferedBody(messages, total, disconnected=True)
        body = bytes(message.get("body", b""))
        total += len(body)
        if total > MAX_REQUEST_BODY_BYTES:
            return None
        messages.append(message)
        if not message.get("more_body", False):
            return BufferedBody(messages, total, disconnected=False)


@dataclass(frozen=True, slots=True)
class BufferedBody:
    messages: list[dict[str, Any]]
    length: int
    disconnected: bool


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
