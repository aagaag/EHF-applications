"""Shared HTTP response boundary for authorized PDF content."""

from __future__ import annotations

from fastapi.responses import Response


def pdf_response(payload: bytes, *, disposition: str, filename: str) -> Response:
    return Response(
        payload,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Content-Security-Policy": (
                "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'"
            ),
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )
