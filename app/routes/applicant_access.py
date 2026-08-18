"""Public Entra-access intake and reviewer-only decision routes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse

from app.applicant.access import ApplicantAccessService
from app.auth.rate_limit import InMemoryRateLimiter
from app.auth.turnstile import TurnstileVerifier
from app.identity import AuthenticatedIdentity
from app.navigation import INTERNAL_GROUPS
from app.http import is_same_origin_write


def register_applicant_access_routes(
    application: FastAPI, *, access: ApplicantAccessService,
    turnstile: TurnstileVerifier, rate_limiter: InMemoryRateLimiter,
    authenticated: Callable[[Request], AuthenticatedIdentity],
    page: Path, turnstile_site_key: str,
) -> None:
    page_html = page.read_text(encoding="utf-8").replace(
        "__EHF_TURNSTILE_SITE_KEY__", turnstile_site_key
    )

    @application.get("/request-access", response_class=HTMLResponse)
    def request_access_page() -> HTMLResponse:
        return HTMLResponse(page_html)

    @application.post("/api/applicant-access-requests")
    async def request_access(request: Request) -> JSONResponse:
        remote_ip = request.client.host if request.client else "unknown"
        now = datetime.now(UTC)
        if not rate_limiter.allow("ACCESS_IP", remote_ip, now) or not rate_limiter.allow(
            "ACCESS_GLOBAL", "all", now
        ):
            return JSONResponse(status_code=429, content={"message": "Please wait before trying again."})
        try:
            payload = await request.json()
        except (TypeError, ValueError):
            payload = {}
        token = payload.get("turnstileToken") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not turnstile.verify(
            token, remote_ip, "applicant-access-request"
        ):
            return JSONResponse(status_code=400, content={"message": "The request could not be verified."})
        try:
            access.request(str(payload.get("email", "")), str(payload.get("displayName", "")))
        except ValueError:
            return JSONResponse(status_code=400, content={"message": "Enter a valid name and email address."})
        return JSONResponse(status_code=202, content={
            "message": "Your request has been received. The Foundation will contact you after review."
        })

    @application.get("/api/internal/applicant-access-requests")
    def pending_access_requests(request: Request) -> JSONResponse:
        _reviewer(authenticated(request))
        return JSONResponse(jsonable_encoder({"requests": [
            {
                "requestId": item.request_id,
                "email": item.requested_email,
                "displayName": item.requested_display_name,
                "requestedAtUtc": item.requested_at_utc,
                "status": item.status,
            }
            for item in access.actionable()
        ]}))

    @application.post("/api/internal/applicant-access-requests/{request_id}/review/{decision}")
    async def review_access_request(
        request_id: UUID, decision: str, request: Request
    ) -> JSONResponse:
        principal = authenticated(request)
        group = _reviewer(principal)
        if not is_same_origin_write(request):
            return JSONResponse(status_code=403, content={"message": "The request is invalid."})
        if await request.body() or decision not in {"approve", "reject"}:
            return JSONResponse(status_code=400, content={"message": "The request is invalid."})
        try:
            reviewed = access.review(
                request_id,
                decision="APPROVED" if decision == "approve" else "REJECTED",
                actor=principal.identity.key,
                actor_group=group,
            )
        except LookupError:
            return JSONResponse(status_code=404, content={"message": "The request is unavailable."})
        return JSONResponse(jsonable_encoder({
            "requestId": reviewed.request_id,
            "status": reviewed.status,
            "reviewedAtUtc": reviewed.reviewed_at_utc,
        }))

    @application.post("/api/internal/applicant-access-requests/{request_id}/provision")
    async def provision_access_request(
        request_id: UUID, request: Request
    ) -> JSONResponse:
        principal = authenticated(request)
        group = _reviewer(principal)
        if not is_same_origin_write(request):
            return JSONResponse(status_code=403, content={"message": "The request is invalid."})
        try:
            payload = await request.json()
            application_id = UUID(str(payload["applicationId"]))
            entra_object_id = UUID(str(payload["entraObjectId"]))
        except (KeyError, TypeError, ValueError):
            return JSONResponse(status_code=400, content={"message": "The request is invalid."})
        try:
            provisioned = access.provision(
                request_id,
                application_id=application_id,
                entra_object_id=entra_object_id,
                actor=principal.identity.key,
                actor_group=group,
            )
        except LookupError:
            return JSONResponse(status_code=404, content={"message": "The request is unavailable."})
        except ValueError:
            return JSONResponse(status_code=409, content={"message": "The identity or application is already linked."})
        return JSONResponse(jsonable_encoder({
            "requestId": provisioned.request_id,
            "status": provisioned.status,
        }))


def _reviewer(principal: AuthenticatedIdentity) -> str:
    if INTERNAL_GROUPS.administrators in principal.groups:
        return INTERNAL_GROUPS.administrators
    if INTERNAL_GROUPS.trustees in principal.groups:
        return INTERNAL_GROUPS.trustees
    raise HTTPException(status_code=404)
