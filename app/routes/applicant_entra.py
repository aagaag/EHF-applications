"""Entra B2B bootstrap for an applicant identity mapped to one application."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.auth.applicant import ApplicantAuthService
from app.identity import AuthenticatedIdentity
from app.navigation import INTERNAL_GROUPS
from app.routes.applicant_auth import CSRF_COOKIE, SESSION_COOKIE


def register_applicant_entra_routes(
    application: FastAPI,
    *,
    auth: ApplicantAuthService,
    resolve_identity: Callable[[Request], AuthenticatedIdentity | None],
    include_session_probe: bool,
) -> None:
    @application.get("/applicant/sign-in")
    def applicant_entra_sign_in(request: Request) -> Response:
        principal = resolve_identity(request)
        if (
            principal is None
            or INTERNAL_GROUPS.applicants not in principal.groups
            or principal.entra_object_id is None
        ):
            return Response(status_code=404)
        session = auth.establish_entra(principal.entra_object_id)
        if session is None:
            return Response(status_code=404)
        response = RedirectResponse("/applicant/review", status_code=303)
        max_age = max(
            1, int((session.absolute_expires_at - datetime.now(UTC)).total_seconds())
        )
        response.set_cookie(
            SESSION_COOKIE,
            session.session_token,
            max_age=max_age,
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        response.set_cookie(
            CSRF_COOKIE,
            session.csrf_token,
            max_age=max_age,
            path="/",
            secure=True,
            httponly=False,
            samesite="strict",
        )
        return response

    if include_session_probe:
        @application.get("/api/applicant/session")
        def applicant_entra_session(request: Request) -> JSONResponse:
            session = auth.authenticate(request.cookies.get(SESSION_COOKIE, ""))
            if session is None:
                return JSONResponse(status_code=401, content={"authenticated": False})
            return JSONResponse({"authenticated": True})
