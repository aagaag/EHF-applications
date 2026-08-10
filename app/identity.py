"""Injected, fail-closed identity boundary for EHF browser routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
