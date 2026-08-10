"""Minimal, fail-closed FastAPI runtime for the EHF fellowship portal."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings
from app.db import connect
from app.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.http import SecurityMiddleware


Probe = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class ReadinessChecks:
    """Injectable, bounded dependency probes used only by readiness."""

    sql_probe: Probe
    storage_probe: Probe
    timeout_seconds: float = 1.0

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= 15:
            raise ValueError("readiness timeout must be between zero and fifteen seconds")


def create_app(
    settings: Settings | None = None,
    *,
    readiness_checks: ReadinessChecks | None = None,
) -> FastAPI:
    """Create the HTTP service without starting application workflows."""
    resolved_settings = settings or Settings.from_environment()
    resolved_checks = readiness_checks or ReadinessChecks(
        sql_probe=lambda timeout: _probe_sql(resolved_settings, timeout),
        storage_probe=lambda timeout: _probe_storage(resolved_settings, timeout),
    )
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    application.add_middleware(SecurityMiddleware, settings=resolved_settings)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)

    @application.get("/health/live", response_model=None)
    def live() -> dict[str, str]:
        return {"status": "live"}

    @application.get("/health/ready", response_model=None)
    def ready() -> JSONResponse | dict[str, str]:
        try:
            resolved_checks.sql_probe(resolved_checks.timeout_seconds)
            resolved_checks.storage_probe(resolved_checks.timeout_seconds)
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "ready"}

    return application


def _probe_sql(settings: Settings, timeout_seconds: float) -> None:
    """Run a bounded constant SQL statement without retrieving application data."""
    bounded_seconds = max(1, math.ceil(timeout_seconds))
    with connect(settings, connect_timeout_seconds=bounded_seconds) as connection:
        connection.timeout = bounded_seconds
        connection.execute("SELECT 1")


def _probe_storage(settings: Settings, timeout_seconds: float) -> None:
    """Stat configured storage roots without enumerating or reading documents."""
    for root in (settings.document_root, settings.quarantine_root):
        if root is None:
            raise RuntimeError("storage is not configured")
        Path(root).stat()


app = create_app()
