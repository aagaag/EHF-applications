"""Fail-closed Cloudflare Turnstile verification with replay rejection."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib import parse, request


TurnstileTransport = Callable[[str, str, str], Mapping[str, Any]]


class TurnstileVerifier:
    def __init__(
        self,
        secret: str,
        expected_hostname: str,
        transport: TurnstileTransport | None = None,
    ) -> None:
        if not secret or not expected_hostname:
            raise ValueError("Turnstile secret and hostname are required")
        self._secret = secret
        self._hostname = expected_hostname.casefold()
        self._transport = transport or _siteverify
        self._used: dict[bytes, float] = {}

    def verify(self, response_token: str, remote_ip: str, expected_action: str) -> bool:
        if not response_token or not remote_ip or not expected_action:
            return False
        token_digest = hashlib.sha256(response_token.encode("utf-8")).digest()
        now = time.monotonic()
        if len(self._used) >= 10_000:
            self._used = {
                digest: used_at for digest, used_at in self._used.items()
                if now - used_at < 600
            }
        if token_digest in self._used:
            return False
        try:
            payload = self._transport(self._secret, response_token, remote_ip)
        except Exception:
            return False
        valid = (
            payload.get("success") is True
            and str(payload.get("hostname", "")).casefold() == self._hostname
            and payload.get("action") == expected_action
        )
        if valid:
            self._used[token_digest] = now
        return valid


def _siteverify(secret: str, token: str, remote_ip: str) -> Mapping[str, Any]:
    body = parse.urlencode(
        {"secret": secret, "response": token, "remoteip": remote_ip}
    ).encode("ascii")
    outbound = request.Request(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with request.urlopen(outbound, timeout=5) as response:  # noqa: S310 - fixed HTTPS endpoint
        payload = json.loads(response.read(65537))
    return payload if isinstance(payload, dict) else {}
