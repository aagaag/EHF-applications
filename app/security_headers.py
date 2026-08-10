"""Response headers that keep the EHF HTTP boundary private by default."""

from __future__ import annotations

from collections.abc import Mapping


CONTENT_SECURITY_POLICY = (
    "default-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
_SECURITY_HEADER_NAMES = frozenset(
    {
        "cache-control",
        "content-security-policy",
        "x-frame-options",
        "x-content-type-options",
        "referrer-policy",
    }
)


def security_headers(*, private: bool) -> dict[str, str]:
    """Return the exact fixed cache and browser-security header set."""
    return {
        "Cache-Control": "private, no-store" if private else "no-store",
        "Content-Security-Policy": CONTENT_SECURITY_POLICY,
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


def is_security_header(name: str) -> bool:
    """Identify headers owned by this boundary without matching unrelated headers."""
    return name.lower() in _SECURITY_HEADER_NAMES


def apply_security_headers(headers: Mapping[str, str], *, private: bool) -> None:
    """Apply the fixed browser and caching contract to one response."""
    for name in tuple(headers):
        if is_security_header(name):
            del headers[name]
    for name, value in security_headers(private=private).items():
        headers[name] = value
