"""Minimal, fail-closed FastAPI runtime for the EHF fellowship portal."""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings
from app.auth.applicant import ApplicantAuthService
from app.auth.rate_limit import InMemoryRateLimiter, RateLimitPolicy
from app.auth.turnstile import TurnstileVerifier
from app.applicant.projection import ApplicantProjectionService
from app.applicant.review import ApplicantReviewService
from app.applicant.publications import CrossrefPublicationLookup, PublicationLookup
from app.applicant.documents import ApplicantDocumentService
from app.applicant.finalize import FinalizationService
from app.applicant.approval import ApplicantApprovalService
from app.applicant.access import ApplicantAccessService
from app.applicant.synthetic import SyntheticApplicantWorkspaceService
from app.applicant.sql_pilot import build_entra_applicant_services
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
from app.internal_calls import render_call_inventory, render_call_workspace
from app.applicant_detail import render_applicant_detail, render_full_page_chart
from app.metrics import EmptyMetricRepository, MetricRepository, SqlMetricRepository
from app.calls import CallCatalog, InMemoryCallCatalog, NewCall, SqlCallCatalog
from app.navigation import INTERNAL_GROUPS
from app.preferences import (
    AppearancePreference,
    CallNavigationPreference,
    Identity,
    PreferenceRepository,
    PreferenceValidationError,
    SqlPreferenceRepository,
)
from app.preview_register import load_preview_register
from app.report_exports import (
    EmptyReportAuditRepository,
    ReportAuditRepository,
    ReportExportMetadata,
    SqlReportAuditRepository,
    build_metrics_workbook,
)
from app.routes.applicant_auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    register_applicant_auth_routes,
)
from app.routes.applicant_data import register_applicant_data_routes
from app.routes.applicant_review import register_applicant_review_routes
from app.routes.applicant_documents import register_applicant_document_routes
from app.routes.applicant_finalize import register_applicant_finalize_routes
from app.routes.applicant_entra import register_applicant_entra_routes
from app.routes.internal_approval import register_internal_approval_routes
from app.routes.internal_synthetic import register_internal_synthetic_routes
from app.routes.applicant_access import register_applicant_access_routes
from app.routes.pending_publication_review import register_pending_publication_review_routes
from app.pending_publication_review import (
    EmptyPendingPublicationReviewRepository,
    PendingPublicationReviewRepository,
    SqlPendingPublicationReviewRepository,
)
from app.http import SecurityMiddleware, is_same_origin_write
from app.shortlist import (
    EmptyShortlistRepository,
    ShortlistRepository,
    SqlShortlistRepository,
    editable_trustee,
)


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
    shortlist_repository: ShortlistRepository | None = None,
    report_audit_repository: ReportAuditRepository | None = None,
    applicant_auth_service: ApplicantAuthService | None = None,
    applicant_turnstile: TurnstileVerifier | None = None,
    applicant_rate_limiter: InMemoryRateLimiter | None = None,
    applicant_publication_rate_limiter: InMemoryRateLimiter | None = None,
    applicant_projection_service: ApplicantProjectionService | None = None,
    applicant_review_service: ApplicantReviewService | None = None,
    applicant_publication_lookup: PublicationLookup | None = None,
    applicant_document_service: ApplicantDocumentService | None = None,
    applicant_finalization_service: FinalizationService | None = None,
    applicant_turnstile_site_key: str | None = None,
    applicant_approval_service: ApplicantApprovalService | None = None,
    applicant_access_service: ApplicantAccessService | None = None,
    synthetic_applicant_service: SyntheticApplicantWorkspaceService | None = None,
    call_catalog: CallCatalog | None = None,
    pending_publication_review_repository: PendingPublicationReviewRepository | None = None,
) -> FastAPI:
    """Create the HTTP service without starting application workflows."""
    resolved_settings = settings or Settings.from_environment()
    resolved_checks = readiness_checks or ReadinessChecks(
        sql_probe=lambda timeout: _probe_sql(resolved_settings, timeout),
        storage_probe=lambda timeout: _probe_storage(resolved_settings, timeout),
    )
    resolve_identity = identity_resolver or _production_identity_resolver(resolved_settings)
    if resolved_settings.applicant_portal_enabled and applicant_auth_service is None:
        pilot = build_entra_applicant_services(resolved_settings)
        applicant_auth_service = pilot.auth
        applicant_projection_service = pilot.projection
        applicant_review_service = pilot.review
        applicant_document_service = pilot.documents  # type: ignore[assignment]
        applicant_finalization_service = pilot.finalization  # type: ignore[assignment]
        applicant_approval_service = pilot.approval  # type: ignore[assignment]
        applicant_access_service = pilot.access
        synthetic_applicant_service = pilot.synthetic
    if resolved_settings.applicant_portal_enabled and applicant_turnstile is None:
        applicant_turnstile = TurnstileVerifier(
            resolved_settings.read_turnstile_secret(), resolved_settings.allowed_host
        )
    if resolved_settings.applicant_portal_enabled and applicant_rate_limiter is None:
        applicant_rate_limiter = InMemoryRateLimiter(
            RateLimitPolicy(limit=20, window=timedelta(minutes=10))
        )
    if applicant_review_service is not None and applicant_publication_lookup is None:
        applicant_publication_lookup = CrossrefPublicationLookup()
    if applicant_review_service is not None and applicant_publication_rate_limiter is None:
        applicant_publication_rate_limiter = InMemoryRateLimiter(
            RateLimitPolicy(limit=240, window=timedelta(minutes=10))
        )
    preferences = preference_repository or SqlPreferenceRepository(lambda: connect(resolved_settings))
    metrics = metric_repository or (
        SqlMetricRepository(lambda: connect(resolved_settings))
        if resolved_settings.environment == "production"
        else EmptyMetricRepository()
    )
    shortlists = shortlist_repository or (
        SqlShortlistRepository(lambda: connect(resolved_settings))
        if resolved_settings.environment == "production"
        else EmptyShortlistRepository()
    )
    report_audits = report_audit_repository or (
        SqlReportAuditRepository(lambda: connect(resolved_settings))
        if resolved_settings.environment == "production"
        else EmptyReportAuditRepository()
    )
    calls = call_catalog or (
        SqlCallCatalog(lambda: connect(resolved_settings))
        if resolved_settings.environment == "production"
        else InMemoryCallCatalog()
    )
    pending_publications = pending_publication_review_repository or (
        SqlPendingPublicationReviewRepository(lambda: connect(resolved_settings))
        if resolved_settings.environment == "production"
        else EmptyPendingPublicationReviewRepository()
    )
    readiness_gate = ReadinessGate(resolved_checks)
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    application.state.call_catalog = calls
    application.add_middleware(SecurityMiddleware, settings=resolved_settings)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)

    if applicant_auth_service is not None and (
        resolved_settings.applicant_portal_enabled
        or synthetic_applicant_service is not None
    ):
        @application.middleware("http")
        async def enforce_live_applicant_identity(request: Request, call_next: Callable) -> Response:
            if request.url.path.startswith("/api/applicant/"):
                session = applicant_auth_service.authenticate(
                    request.cookies.get(SESSION_COOKIE, "")
                )
                if session is None:
                    return JSONResponse(
                        status_code=401,
                        content={"message": "Authentication required."},
                    )
                principal = resolve_identity(request)
                if session.synthetic_actor_identity is not None:
                    if (
                        principal is None
                        or INTERNAL_GROUPS.administrators not in principal.groups
                        or principal.identity.key != session.synthetic_actor_identity
                    ):
                        return Response(status_code=404)
                    if request.url.path.startswith("/api/applicant/documents") or (
                        request.url.path == "/api/applicant/finalization"
                        and request.method.upper() != "GET"
                    ):
                        return Response(status_code=404)
                elif session.entra_object_id is not None:
                    if (
                        principal is None
                        or INTERNAL_GROUPS.applicants not in principal.groups
                        or principal.entra_object_id is None
                        or session.entra_object_id != principal.entra_object_id
                    ):
                        return Response(status_code=404)
                else:
                    # Invitation sessions have no live Entra principal. Their opaque
                    # session and CSRF bindings remain the authorization source.
                    pass
            elif request.url.path == "/applicant" or request.url.path.startswith(
                "/applicant/"
            ):
                session_token = request.cookies.get(SESSION_COOKIE, "")
                session = (
                    applicant_auth_service.authenticate(session_token)
                    if session_token
                    else None
                )
                if session is not None and session.synthetic_actor_identity is not None:
                    principal = resolve_identity(request)
                    if (
                        principal is None
                        or INTERNAL_GROUPS.administrators not in principal.groups
                        or principal.identity.key != session.synthetic_actor_identity
                    ):
                        return Response(status_code=404)
                    canonical = _synthetic_applicant_page_alias(request.url.path)
                    if canonical is not None and request.method.upper() in {"GET", "HEAD"}:
                        return RedirectResponse(canonical, status_code=303)
            return await call_next(request)

    public_root = Path(__file__).resolve().parents[1] / "public"
    application.mount("/assets", StaticFiles(directory=public_root / "assets"), name="assets")

    def authenticated(request: Request) -> AuthenticatedIdentity:
        principal = resolve_identity(request)
        if principal is None:
            raise HTTPException(status_code=404)
        return principal

    def internal_role(principal: AuthenticatedIdentity) -> str:
        if INTERNAL_GROUPS.administrators in principal.groups:
            return INTERNAL_GROUPS.administrators
        if INTERNAL_GROUPS.trustees in principal.groups:
            return INTERNAL_GROUPS.trustees
        raise HTTPException(status_code=404)

    def default_call(principal: AuthenticatedIdentity):
        summaries = calls.list_authorized(internal_role(principal))
        if not summaries:
            return None
        preference = preferences.load_call_navigation(principal.identity)
        if preference.mode == "resume-last-opened" and preference.last_fellowship_call_id:
            resumed = next(
                (
                    summary.context
                    for summary in summaries
                    if summary.context.fellowship_call_id
                    == preference.last_fellowship_call_id
                ),
                None,
            )
            if resumed is not None:
                return resumed
        return max(
            (summary.context for summary in summaries),
            key=lambda context: (context.application_deadline_utc, context.public_slug),
        )

    if synthetic_applicant_service is not None:
        register_internal_synthetic_routes(
            application,
            resolve_identity=resolve_identity,
            synthetic=synthetic_applicant_service,
        )

    if (
        applicant_access_service is not None
        and applicant_turnstile is not None
        and applicant_rate_limiter is not None
    ):
        register_applicant_access_routes(
            application,
            access=applicant_access_service,
            turnstile=applicant_turnstile,
            rate_limiter=applicant_rate_limiter,
            authenticated=authenticated,
            page=public_root / "applicant" / "request-access.html",
            turnstile_site_key=(
                applicant_turnstile_site_key
                or resolved_settings.turnstile_site_key
                or ""
            ),
        )

    if applicant_approval_service is not None:
        register_internal_approval_routes(
            application,
            authenticated=authenticated,
            approval=applicant_approval_service,
            documents=applicant_document_service,
        )

    register_pending_publication_review_routes(
        application,
        authenticated=authenticated,
        repository=pending_publications,
        page=public_root / "internal" / "review-pending-papers.html",
    )

    @application.get("/", response_class=RedirectResponse)
    def home(request: Request) -> RedirectResponse:
        principal = authenticated(request)
        if not principal.groups & {INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees}:
            raise HTTPException(status_code=404)
        return RedirectResponse("/internal/", status_code=303)

    @application.get("/internal/")
    def internal_preview(request: Request) -> Response:
        principal = authenticated(request)
        role = internal_role(principal)
        selected = default_call(principal)
        if selected is None:
            shortlist = shortlists.load(
                principal.identity.key, role, principal.entra_object_id
            )
            return HTMLResponse(
                render_internal_preview(
                    principal,
                    records=metrics.load(role),
                    shortlist=shortlist,
                )
            )
        return RedirectResponse(
            f"/internal/calls/{selected.public_slug}/", status_code=303
        )

    @application.get("/internal/calls/", response_class=HTMLResponse)
    def internal_calls(request: Request) -> HTMLResponse:
        principal = authenticated(request)
        role = internal_role(principal)
        summaries = calls.list_authorized(role)
        preference = (
            preferences.load_call_navigation(principal.identity)
            if summaries
            else CallNavigationPreference()
        )
        return HTMLResponse(
            render_call_inventory(
                principal, summaries, preference=preference
            )
        )

    @application.get("/internal/calls/{call_slug}/", response_class=HTMLResponse)
    def internal_call_workspace(call_slug: str, request: Request) -> HTMLResponse:
        principal = authenticated(request)
        role = internal_role(principal)
        try:
            current_call = calls.resolve(call_slug, role, "READ")
        except (LookupError, ValueError):
            raise HTTPException(status_code=404) from None
        preference = preferences.load_call_navigation(principal.identity)
        preference = preferences.save_call_navigation(
            principal.identity,
            CallNavigationPreference(preference.mode, current_call.fellowship_call_id),
        )
        summaries = calls.list_authorized(role)
        if current_call.public_slug == "ehf-2026":
            shortlist = shortlists.load(
                principal.identity.key, role, principal.entra_object_id
            )
            return HTMLResponse(
                render_internal_preview(
                    principal,
                    records=metrics.load(role),
                    shortlist=shortlist,
                    call_summaries=summaries,
                    current_call=current_call,
                    call_preference=preference,
                )
            )
        return HTMLResponse(
            render_call_workspace(
                principal, summaries, current_call, preference=preference
            )
        )

    @application.post("/api/internal/call-navigation-preference")
    async def set_call_navigation_preference(request: Request) -> JSONResponse:
        principal = authenticated(request)
        internal_role(principal)
        if not is_same_origin_write(request):
            raise HTTPException(status_code=404)
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(status_code=422) from None
        if not isinstance(payload, dict) or set(payload) != {"mode"}:
            raise HTTPException(status_code=422)
        current = preferences.load_call_navigation(principal.identity)
        try:
            requested = CallNavigationPreference(
                mode=payload["mode"],
                last_fellowship_call_id=current.last_fellowship_call_id,
            )
        except (PreferenceValidationError, TypeError):
            raise HTTPException(status_code=422) from None
        stored = preferences.save_call_navigation(principal.identity, requested)
        return JSONResponse({"mode": stored.mode})

    @application.post("/api/internal/calls")
    async def create_internal_call(request: Request) -> JSONResponse:
        principal = authenticated(request)
        role = internal_role(principal)
        if role != INTERNAL_GROUPS.administrators or not is_same_origin_write(request):
            raise HTTPException(status_code=404)
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(status_code=422) from None
        expected = {
            "callCode",
            "publicSlug",
            "displayName",
            "compactTitle",
            "applicationDeadlineUtc",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise HTTPException(status_code=422)
        try:
            deadline = datetime.fromisoformat(
                str(payload["applicationDeadlineUtc"]).replace("Z", "+00:00")
            )
            new_call = NewCall(
                call_code=payload["callCode"],
                public_slug=payload["publicSlug"],
                display_name=payload["displayName"],
                compact_title=payload["compactTitle"],
                application_deadline_utc=deadline,
            )
            created = calls.create(new_call, principal.identity.key, role)
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=422) from None
        return JSONResponse(
            {"location": f"/internal/calls/{created.public_slug}/"}, status_code=201
        )

    @application.post("/api/internal/applicants/{application_id}/shortlist/{trustee_code}")
    async def set_internal_shortlist(
        application_id: UUID, trustee_code: str, request: Request
    ) -> JSONResponse:
        principal = authenticated(request)
        if not principal.groups & {INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees}:
            raise HTTPException(status_code=404)
        if not is_same_origin_write(request):
            raise HTTPException(status_code=404)
        owner = editable_trustee(principal.entra_object_id)
        if owner is None or trustee_code != owner:
            raise HTTPException(status_code=404)
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(status_code=422) from None
        if (
            not isinstance(payload, dict)
            or set(payload) != {"group"}
            or payload["group"] not in {"A", "B", "C"}
        ):
            raise HTTPException(status_code=422)
        role = (
            INTERNAL_GROUPS.administrators
            if INTERNAL_GROUPS.administrators in principal.groups
            else INTERNAL_GROUPS.trustees
        )
        try:
            group = shortlists.set(
                application_id,
                trustee_code,
                payload["group"],
                principal.identity.key,
                role,
                principal.entra_object_id,
            )
        except (LookupError, PermissionError):
            raise HTTPException(status_code=404) from None
        return JSONResponse({"group": group})

    @application.get(
        "/api/internal/applicants/{application_id}/metrics-detail",
        response_class=HTMLResponse,
    )
    def internal_applicant_metric_detail(
        application_id: UUID, request: Request, full_page_chart: int | None = None
    ) -> HTMLResponse:
        principal = authenticated(request)
        if not principal.groups & {INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees}:
            raise HTTPException(status_code=404)
        role = (
            INTERNAL_GROUPS.administrators
            if INTERNAL_GROUPS.administrators in principal.groups
            else INTERNAL_GROUPS.trustees
        )
        try:
            detail = metrics.load_detail(application_id, role)
        except LookupError:
            raise HTTPException(status_code=404) from None
        if full_page_chart is None:
            return HTMLResponse(render_applicant_detail(detail))
        try:
            return HTMLResponse(render_full_page_chart(detail, full_page_chart))
        except ValueError:
            raise HTTPException(status_code=404) from None

    @application.get("/internal/reports/metrics.xlsx")
    def metrics_workbook(request: Request) -> Response:
        principal = authenticated(request)
        if not principal.groups & {INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees}:
            raise HTTPException(status_code=404)
        role = (
            INTERNAL_GROUPS.administrators
            if INTERNAL_GROUPS.administrators in principal.groups
            else INTERNAL_GROUPS.trustees
        )
        records = metrics.load(role)
        metadata = ReportExportMetadata(
            actor_identity=principal.identity.key,
            actor_group=role,
            generated_at_utc=datetime.now(UTC),
        )
        try:
            content = build_metrics_workbook(records, metadata)
        except Exception:
            report_audits.record(
                metadata, len(records), "FAILED", failure_stage="workbook-generation"
            )
            raise
        report_audits.record(metadata, len(records), "COMPLETED")
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="ehf-2026.xlsx"',
            },
        )

    @application.get("/api/preferences")
    def get_preferences(request: Request) -> dict[str, str | bool]:
        principal = resolve_identity(request)
        applicant_session = None
        if principal is None and applicant_auth_service is not None:
            applicant_session = applicant_auth_service.authenticate(
                request.cookies.get(SESSION_COOKIE, "")
            )
        if principal is None and applicant_session is None:
            raise HTTPException(status_code=401)
        identity = (
            principal.identity
            if principal is not None
            else _applicant_preference_identity(applicant_session.application_id)
        )
        return _preference_response(preferences.load(identity))

    @application.post("/api/preferences")
    async def save_preferences(request: Request) -> dict[str, str | bool]:
        principal = resolve_identity(request)
        applicant_session = None
        if principal is None and applicant_auth_service is not None:
            applicant_session = applicant_auth_service.authenticate(
                request.cookies.get(SESSION_COOKIE, "")
            )
        if principal is None and applicant_session is None:
            raise HTTPException(status_code=401)
        if applicant_session is not None:
            csrf_header = request.headers.get("x-csrf-token", "")
            csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
            if (
                not csrf_header
                or csrf_header != csrf_cookie
                or not applicant_auth_service.valid_csrf(applicant_session, csrf_header)
            ):
                raise HTTPException(status_code=403)
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
        identity = (
            principal.identity
            if principal is not None
            else _applicant_preference_identity(applicant_session.application_id)
        )
        return _preference_response(preferences.save(identity, preference))

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

    applicant_dependencies_ready = (
        applicant_auth_service is not None
        and applicant_turnstile is not None
        and applicant_rate_limiter is not None
    )
    invitation_workflow_supported = applicant_auth_service is None or bool(
        # A repository that does not declare a capability keeps its historical behaviour;
        # the deployed SQL repository declares itself unable to serve invitations.
        getattr(applicant_auth_service, "supports_invitation_verification", True)
    )
    legacy_invitation_routes_enabled = (
        resolved_settings.environment != "production"
        or resolved_settings.invitations_enabled
    ) and invitation_workflow_supported
    if applicant_auth_service is not None:
        register_applicant_entra_routes(
            application,
            auth=applicant_auth_service,
            resolve_identity=resolve_identity,
            include_session_probe=not (
                legacy_invitation_routes_enabled and applicant_dependencies_ready
            ),
            review_page=public_root / "applicant" / "review.html",
            documents_page=public_root / "applicant" / "documents.html",
            final_review_page=public_root / "applicant" / "final-review.html",
        )
    applicant_routes_enabled = (
        resolved_settings.environment != "production"
        or resolved_settings.invitations_enabled
        or resolved_settings.applicant_portal_enabled
    )
    if resolved_settings.invitations_enabled and not applicant_dependencies_ready:
        raise RuntimeError("Applicant invitations are enabled without the required portal services.")
    if resolved_settings.invitations_enabled and not invitation_workflow_supported:
        raise RuntimeError(
            "Applicant invitations are enabled without a repository that can serve the "
            "invitation and verification-code workflow."
        )
    if legacy_invitation_routes_enabled and applicant_dependencies_ready:
        register_applicant_auth_routes(
            application,
            auth=applicant_auth_service,
            turnstile=applicant_turnstile,
            rate_limiter=applicant_rate_limiter,
            verify_page=public_root / "applicant" / "verify.html",
            turnstile_site_key=(
                applicant_turnstile_site_key
                or resolved_settings.turnstile_site_key
                or ""
            ),
        )
    if applicant_routes_enabled and applicant_auth_service is not None:
        if applicant_projection_service is not None:
            register_applicant_data_routes(
                application,
                auth=applicant_auth_service,
                projection=applicant_projection_service,
            )
        if applicant_review_service is not None:
            register_applicant_review_routes(
                application,
                auth=applicant_auth_service,
                review=applicant_review_service,
                publications=applicant_publication_lookup,
                rate_limiter=applicant_publication_rate_limiter,
            )
        if applicant_document_service is not None:
            register_applicant_document_routes(
                application,
                auth=applicant_auth_service,
                documents=applicant_document_service,
            )
        if applicant_finalization_service is not None:
            register_applicant_finalize_routes(
                application,
                auth=applicant_auth_service,
                finalization=applicant_finalization_service,
            )
    application.mount(
        "/applicant", StaticFiles(directory=public_root / "applicant", html=True), name="applicant"
    )

    return application


def _synthetic_applicant_page_alias(path: str) -> str | None:
    return {
        "/applicant": "/applicant/review",
        "/applicant/": "/applicant/review",
        "/applicant/index.html": "/applicant/review",
        "/applicant/review.html": "/applicant/review",
        "/applicant/review/": "/applicant/review",
        "/applicant/documents.html": "/applicant/documents",
        "/applicant/documents/": "/applicant/documents",
        "/applicant/final-review.html": "/applicant/final-review",
        "/applicant/final-review/": "/applicant/final-review",
    }.get(path)


def _preference_response(preference: AppearancePreference) -> dict[str, str | bool]:
    return {
        "skin": preference.skin,
        "invert": preference.invert,
        "compact": preference.compact,
        "reduceMotion": preference.reduce_motion,
    }


def _applicant_preference_identity(application_id: object) -> Identity:
    return Identity(
        f"applicant:{application_id}",
        "applicant-preference@ehf.invalid",
        "EHF applicant",
    )


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
        audience=tuple(
            item.strip()
            for item in str(settings.cloudflare_access_audience).split(",")
            if item.strip()
        ),
        administrator_group_id=str(settings.administrator_group_id),
        trustee_group_id=str(settings.trustee_group_id),
        applicant_group_id=settings.applicant_group_id,
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
