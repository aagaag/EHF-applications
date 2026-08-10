"""Injected, fail-closed identity boundary for EHF browser routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from starlette.requests import Request

from app.preferences import Identity


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    """A verified identity supplied by the future applicant or internal sign-in boundary."""

    identity: Identity
    groups: frozenset[str] = frozenset()


IdentityResolver = Callable[[Request], AuthenticatedIdentity | None]


def deny_identity(_request: Request) -> None:
    """Keep every protected route unavailable until a verified resolver is installed."""
    return None


class CloudflareAccessIdentityResolver:
    """Validate Access JWTs and resolve complete Entra group membership fail-closed."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        administrator_group_id: str,
        trustee_group_id: str,
        timeout_seconds: float = 4.0,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._group_map = {
            administrator_group_id.casefold(): "EHF-Applications-Administrators",
            trustee_group_id.casefold(): "EHF-Applications-Trustees",
        }
        self._timeout = timeout_seconds
        self._keys = jwt.PyJWKClient(f"{self._issuer}/cdn-cgi/access/certs", cache_keys=True)

    def __call__(self, request: Request) -> AuthenticatedIdentity | None:
        assertion = request.headers.get("cf-access-jwt-assertion", "").strip()
        cookie = request.cookies.get("CF_Authorization", "").strip()
        if not assertion or not cookie:
            return None
        try:
            signing_key = self._keys.get_signing_key_from_jwt(assertion)
            claims: dict[str, Any] = jwt.decode(
                assertion,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["aud", "exp", "iat", "iss", "sub", "email"]},
            )
            if claims.get("type") != "app":
                return None
            email = str(claims["email"]).strip().casefold()
            subject = str(claims["sub"]).strip()
            if not email or not subject:
                return None
            response = httpx.get(
                f"{self._issuer}/cdn-cgi/access/get-identity",
                headers={"cookie": f"CF_Authorization={cookie}"},
                timeout=self._timeout,
                follow_redirects=False,
            )
            response.raise_for_status()
            identity_payload = response.json()
            if str(identity_payload.get("email", "")).strip().casefold() != email:
                return None
            idp = identity_payload.get("idp")
            if not isinstance(idp, dict):
                return None
            group_values = _string_values(idp.get("groups"))
            groups = frozenset(
                canonical
                for identifier, canonical in self._group_map.items()
                if identifier in group_values
            )
            if not groups:
                return None
            display_name = str(idp.get("name") or identity_payload.get("name") or email).strip()
            return AuthenticatedIdentity(
                identity=Identity(f"cloudflare:{subject}", email, display_name),
                groups=groups,
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, jwt.PyJWTError):
            return None


def _string_values(value: Any) -> frozenset[str]:
    if isinstance(value, str):
        return frozenset({value.casefold()})
    if isinstance(value, list):
        return frozenset(str(item).casefold() for item in value if isinstance(item, str))
    return frozenset()
