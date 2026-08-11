"""Identity-neutral applicant invitation and verification routes."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.auth.applicant import ApplicantAuthService, NEUTRAL_CODE_MESSAGE
from app.auth.rate_limit import InMemoryRateLimiter
from app.auth.turnstile import TurnstileVerifier


PREAUTH_COOKIE = "ehf_applicant_preauth"
SESSION_COOKIE = "__Host-ehf_applicant_session"
CSRF_COOKIE = "__Host-ehf_applicant_csrf"


def register_applicant_auth_routes(
    application: FastAPI,
    *,
    auth: ApplicantAuthService,
    turnstile: TurnstileVerifier,
    rate_limiter: InMemoryRateLimiter,
    verify_page: Path,
    turnstile_site_key: str = "",
) -> None:
    page_html = verify_page.read_text(encoding="utf-8").replace(
        "__EHF_TURNSTILE_SITE_KEY__", turnstile_site_key
    )
    failed_verifications: dict[str, int] = {}

    @application.get("/a/{invitation_token}", response_class=RedirectResponse)
    def applicant_invitation_entry(invitation_token: str) -> RedirectResponse:
        context = auth.establish(invitation_token)
        response = RedirectResponse("/applicant/verify", status_code=303)
        response.set_cookie(
            PREAUTH_COOKIE,
            context,
            max_age=1200,
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return response

    @application.get("/applicant/verify", response_class=HTMLResponse)
    def applicant_verify_page() -> HTMLResponse:
        return HTMLResponse(page_html)

    @application.post("/api/applicant/auth/code")
    async def request_applicant_code(request: Request) -> JSONResponse:
        payload = await _json_object(request)
        turnstile_token = payload.get("turnstileToken")
        remote_ip = request.client.host if request.client else "unknown"
        preauth = request.cookies.get(PREAUTH_COOKIE, "")
        if not _within_limits(rate_limiter, preauth, remote_ip):
            return JSONResponse(
                status_code=429,
                content={"message": "Please wait before trying again."},
            )
        if not isinstance(turnstile_token, str) or not turnstile.verify(
            turnstile_token, remote_ip, "applicant-code-request"
        ):
            return JSONResponse(
                status_code=400,
                content={"message": "The request could not be verified."},
            )
        auth.request_code(preauth)
        return JSONResponse(status_code=202, content={"message": NEUTRAL_CODE_MESSAGE})

    @application.post("/api/applicant/auth/verify")
    async def verify_applicant_code(request: Request) -> JSONResponse:
        payload = await _json_object(request)
        code = payload.get("code")
        preauth = request.cookies.get(PREAUTH_COOKIE, "")
        remote_ip = request.client.host if request.client else "unknown"
        if not _within_verification_limits(rate_limiter, preauth, remote_ip):
            return JSONResponse(
                status_code=429,
                content={"message": "Please wait before trying again."},
            )
        context_key = hashlib.sha256(preauth.encode("utf-8")).hexdigest()
        if failed_verifications.get(context_key, 0) >= 1:
            turnstile_token = payload.get("turnstileToken")
            if not isinstance(turnstile_token, str) or not turnstile.verify(
                turnstile_token, remote_ip, "applicant-code-request"
            ):
                return JSONResponse(
                    status_code=400,
                    content={
                        "message": "Complete the security check before trying the code again.",
                        "turnstileRequired": True,
                    },
                )
        verified = auth.verify_code(preauth, code if isinstance(code, str) else "")
        if verified is None:
            failed_verifications[context_key] = failed_verifications.get(context_key, 0) + 1
            return JSONResponse(
                status_code=401,
                content={
                    "message": "The code could not be verified. Complete the security check before trying again.",
                    "turnstileRequired": True,
                },
            )
        failed_verifications.pop(context_key, None)
        response = JSONResponse({"next": "/applicant/review"})
        response.delete_cookie(PREAUTH_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        response.set_cookie(
            SESSION_COOKIE,
            verified.session_token,
            max_age=max(1, int((verified.absolute_expires_at - datetime.now(UTC)).total_seconds())),
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        response.set_cookie(
            CSRF_COOKIE,
            verified.csrf_token,
            max_age=max(1, int((verified.absolute_expires_at - datetime.now(UTC)).total_seconds())),
            path="/",
            secure=True,
            httponly=False,
            samesite="strict",
        )
        return response

    @application.get("/api/applicant/session")
    def applicant_session(request: Request) -> JSONResponse:
        session_token = request.cookies.get(SESSION_COOKIE, "")
        if auth.authenticate(session_token) is None:
            return JSONResponse(status_code=401, content={"authenticated": False})
        return JSONResponse({"authenticated": True})


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _within_limits(
    limiter: InMemoryRateLimiter, preauth_token: str, remote_ip: str
) -> bool:
    now = datetime.now(UTC)
    subject = hashlib.sha256(preauth_token.encode("utf-8")).hexdigest()
    return all(
        (
            limiter.allow("INVITATION", subject, now),
            limiter.allow("IP", remote_ip, now),
            limiter.allow("GLOBAL", "all", now),
        )
    )


def _within_verification_limits(
    limiter: InMemoryRateLimiter, preauth_token: str, remote_ip: str
) -> bool:
    now = datetime.now(UTC)
    subject = hashlib.sha256(preauth_token.encode("utf-8")).hexdigest()
    return all(
        (
            limiter.allow("VERIFY_CONTEXT", subject, now),
            limiter.allow("VERIFY_IP", remote_ip, now),
            limiter.allow("VERIFY_GLOBAL", "all", now),
        )
    )
