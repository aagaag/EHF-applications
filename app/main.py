"""Minimal, fail-closed FastAPI runtime for the EHF fellowship portal."""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings
from app.db import connect
from app.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.identity import (
    AuthenticatedIdentity,
    CloudflareAccessIdentityResolver,
    IdentityResolver,
    deny_identity,
)
from app.internal_preview import render_internal_preview
from app.metrics import EmptyMetricRepository, MetricRepository, SqlMetricRepository
from app.navigation import INTERNAL_GROUPS
from app.preferences import AppearancePreference, Identity, PreferenceRepository, SqlPreferenceRepository
from app.preview_register import load_preview_register
from app.http import SecurityMiddleware


Probe = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class ReadinessChecks:
    """Injectable, bounded dependency probes used only by readiness."""

    sql_probe: Probe
    storage_probe: Probe
    timeout_seconds: float = 1.0
    max_concurrency: int = 2

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= 15:
            raise ValueError("readiness timeout must be between zero and fifteen seconds")
        if not 1 <= self.max_concurrency <= 4:
            raise ValueError("readiness concurrency must be between one and four")


class ReadinessGate:
    """Bound active blocking readiness probes even after a request times out."""

    def __init__(self, checks: ReadinessChecks) -> None:
        self._checks = checks
        self._permits = asyncio.BoundedSemaphore(checks.max_concurrency)

    async def is_ready(self) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._checks.timeout_seconds
        try:
            await asyncio.wait_for(self._permits.acquire(), timeout=self._remaining(deadline))
        except TimeoutError:
            return False

        if self._remaining(deadline) <= 0:
            self._permits.release()
            return False

        worker = asyncio.create_task(asyncio.to_thread(self._run_probes))
        worker.add_done_callback(self._release_completed_worker)
        try:
            await asyncio.wait_for(asyncio.shield(worker), timeout=self._remaining(deadline))
        except (TimeoutError, Exception):
            return False
        return True

    def _run_probes(self) -> None:
        self._checks.sql_probe(self._checks.timeout_seconds)
        self._checks.storage_probe(self._checks.timeout_seconds)

    def _release_completed_worker(self, worker: asyncio.Task[None]) -> None:
        try:
            worker.exception()
        except asyncio.CancelledError:
            pass
        finally:
            self._permits.release()

    @staticmethod
    def _remaining(deadline: float) -> float:
        return max(0.0, deadline - asyncio.get_running_loop().time())


def create_app(
    settings: Settings | None = None,
    *,
    readiness_checks: ReadinessChecks | None = None,
    identity_resolver: IdentityResolver | None = None,
    preference_repository: PreferenceRepository | None = None,
    metric_repository: MetricRepository | None = None,
) -> FastAPI:
    """Create the HTTP service without starting application workflows."""
    resolved_settings = settings or Settings.from_environment()
    resolved_checks = readiness_checks or ReadinessChecks(
        sql_probe=lambda timeout: _probe_sql(resolved_settings, timeout),
        storage_probe=lambda timeout: _probe_storage(resolved_settings, timeout),
    )
    resolve_identity = identity_resolver or _production_identity_resolver(resolved_settings)
    preferences = preference_repository or SqlPreferenceRepository(lambda: connect(resolved_settings))
    metrics = metric_repository or (
        SqlMetricRepository(lambda: connect(resolved_settings))
        if resolved_settings.environment == "production"
        else EmptyMetricRepository()
    )
    readiness_gate = ReadinessGate(resolved_checks)
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    application.add_middleware(SecurityMiddleware, settings=resolved_settings)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)

    public_root = Path(__file__).resolve().parents[1] / "public"
    application.mount("/assets", StaticFiles(directory=public_root / "assets"), name="assets")
    application.mount(
        "/applicant", StaticFiles(directory=public_root / "applicant", html=True), name="applicant"
    )

    def authenticated(request: Request) -> AuthenticatedIdentity:
        principal = resolve_identity(request)
        if principal is None:
            raise HTTPException(status_code=404)
        return principal

    @application.get("/", response_class=RedirectResponse)
    def home(request: Request) -> RedirectResponse:
        principal = authenticated(request)
        if not principal.groups & {INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees}:
            raise HTTPException(status_code=404)
        return RedirectResponse("/internal/", status_code=303)

    @application.get("/internal/", response_class=HTMLResponse)
    def internal_preview(request: Request) -> HTMLResponse:
        principal = authenticated(request)
        if not principal.groups & {INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees}:
            raise HTTPException(status_code=404)
        role = (
            INTERNAL_GROUPS.administrators
            if INTERNAL_GROUPS.administrators in principal.groups
            else INTERNAL_GROUPS.trustees
        )
        return HTMLResponse(render_internal_preview(principal, records=metrics.load(role)))

    @application.get("/api/preferences")
    def get_preferences(request: Request) -> dict[str, str | bool]:
        principal = resolve_identity(request)
        if principal is None:
            raise HTTPException(status_code=401)
        return _preference_response(preferences.load(principal.identity))

    @application.post("/api/preferences")
    async def save_preferences(request: Request) -> dict[str, str | bool]:
        principal = resolve_identity(request)
        if principal is None:
            raise HTTPException(status_code=401)
        try:
            payload = await request.json()
            preference = AppearancePreference(
                skin=payload["skin"],
                invert=payload["invert"],
                compact=payload["compact"],
                reduce_motion=payload["reduceMotion"],
            )
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=400) from None
        return _preference_response(preferences.save(principal.identity, preference))

    if resolved_settings.environment == "development":
        preview_real_data_enabled = (
            os.environ.get("EHF_PREVIEW_REAL_DATA_ENABLED", "").strip().lower() == "true"
        )
        preview_register_path = (
            os.environ.get("EHF_PREVIEW_REGISTER_PATH", "").strip()
            if preview_real_data_enabled
            else ""
        )
        preview_records = (
            load_preview_register(Path(preview_register_path)) if preview_register_path else ()
        )
        simulation = AuthenticatedIdentity(
            identity=Identity(
                "development:administrator", "preview@example.invalid", "Development preview"
            ),
            groups=frozenset({INTERNAL_GROUPS.administrators}),
        )

        @application.get("/__preview/internal/administrator/", response_class=HTMLResponse)
        def development_administrator_preview(request: Request) -> HTMLResponse:
            if not _is_loopback_preview_request(request):
                raise HTTPException(status_code=404)
            return HTMLResponse(
                render_internal_preview(simulation, simulation=True, records=preview_records)
            )

    @application.get("/health/live", response_model=None)
    def live() -> dict[str, str]:
        return {"status": "live"}

    @application.get("/health/ready", response_model=None)
    async def ready() -> JSONResponse | dict[str, str]:
        if not await readiness_gate.is_ready():
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "ready"}

    return application


def _preference_response(preference: AppearancePreference) -> dict[str, str | bool]:
    return {
        "skin": preference.skin,
        "invert": preference.invert,
        "compact": preference.compact,
        "reduceMotion": preference.reduce_motion,
    }


def _production_identity_resolver(settings: Settings) -> IdentityResolver:
    if settings.environment != "production":
        return deny_identity
    required = (
        settings.cloudflare_access_issuer,
        settings.cloudflare_access_audience,
        settings.administrator_group_id,
        settings.trustee_group_id,
    )
    if not all(required):
        return deny_identity
    return CloudflareAccessIdentityResolver(
        issuer=str(settings.cloudflare_access_issuer),
        audience=str(settings.cloudflare_access_audience),
        administrator_group_id=str(settings.administrator_group_id),
        trustee_group_id=str(settings.trustee_group_id),
    )


def _probe_sql(settings: Settings, timeout_seconds: float) -> None:
    """Run a bounded constant SQL statement without retrieving application data."""
    bounded_seconds = max(1, math.ceil(timeout_seconds))
    with connect(
        settings,
        connect_timeout_seconds=bounded_seconds,
        query_timeout_seconds=bounded_seconds,
    ) as connection:
        connection.execute("SELECT 1")


def _probe_storage(settings: Settings, timeout_seconds: float) -> None:
    """Stat configured storage roots without enumerating or reading documents."""
    for root in (settings.document_root, settings.quarantine_root):
        if root is None:
            raise RuntimeError("storage is not configured")
        Path(root).stat()


app = create_app()


def _is_loopback_preview_request(request: Request) -> bool:
    """Keep development simulation and any loaded register off proxied/public hosts."""
    hostname = (request.url.hostname or "").casefold()
    client = request.client.host.casefold() if request.client else ""
    return hostname in {"localhost", "127.0.0.1", "::1"} and client in {
        "127.0.0.1",
        "::1",
        "testclient",
    }
