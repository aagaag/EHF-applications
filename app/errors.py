"""Stable, redacted JSON error responses for the public HTTP boundary."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.security_headers import apply_security_headers


def correlation_id(request: Request) -> str:
    """Return the ID installed by the outer HTTP boundary."""
    return str(request.scope.get("ehf.correlation_id") or uuid.uuid4().hex)


def error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    *,
    private: bool = False,
) -> JSONResponse:
    """Build an error without exposing exception details or request content."""
    response = JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "correlation_id": request_id,
            }
        },
    )
    response.headers["X-Request-ID"] = request_id
    apply_security_headers(response.headers, private=private)
    return response


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Convert framework HTTP errors into the fixed public envelope."""
    if exc.status_code == 404:
        return error_response(404, "not_found", "Not found", correlation_id(request))
    return error_response(
        exc.status_code,
        "invalid_request",
        "Request could not be processed",
        correlation_id(request),
        private=_request_is_private(request),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Hide validation details because they can include supplied personal data."""
    return error_response(
        422,
        "invalid_request",
        "Request could not be processed",
        correlation_id(request),
        private=_request_is_private(request),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Hide unhandled exception text while retaining a support correlation ID."""
    return error_response(
        500,
        "internal_error",
        "The service could not process this request",
        correlation_id(request),
        private=_request_is_private(request),
    )


def _request_is_private(request: Request) -> bool:
    return bool(
        request.headers.get("authorization")
        or request.headers.get("cookie")
        or request.url.path.startswith(("/applicant", "/internal"))
    )
