"""Entra B2B bootstrap for an applicant identity mapped to one application."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

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
    review_page: Path,
    documents_page: Path,
    final_review_page: Path,
) -> None:
    workspace_pages = {
        "/applicant/review": review_page.read_text(encoding="utf-8"),
        "/applicant/documents": documents_page.read_text(encoding="utf-8"),
        "/applicant/final-review": final_review_page.read_text(encoding="utf-8"),
    }

    def workspace_page(request: Request, page_html: str) -> Response:
        principal = resolve_identity(request)
        live_entra_applicant = (
            principal is not None
            and INTERNAL_GROUPS.applicants in principal.groups
            and principal.entra_object_id is not None
        )
        session = auth.authenticate(request.cookies.get(SESSION_COOKIE, ""))
        if session is None:
            if live_entra_applicant:
                return RedirectResponse("/applicant/sign-in", status_code=303)
            return Response(status_code=404)
        if session.synthetic_actor_identity is not None:
            if (
                principal is None
                or INTERNAL_GROUPS.administrators not in principal.groups
                or principal.identity.key != session.synthetic_actor_identity
            ):
                return Response(status_code=404)
        elif session.entra_object_id is not None and (
                not live_entra_applicant
                or session.entra_object_id != principal.entra_object_id
            ):
                return Response(status_code=404)
        return HTMLResponse(page_html)

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
            samesite="lax",
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

    @application.get("/applicant/review", response_class=HTMLResponse)
    def applicant_review_page(request: Request) -> Response:
        return workspace_page(request, workspace_pages["/applicant/review"])

    @application.get("/applicant/documents", response_class=HTMLResponse)
    def applicant_documents_page(request: Request) -> Response:
        return workspace_page(request, workspace_pages["/applicant/documents"])

    @application.get("/applicant/final-review", response_class=HTMLResponse)
    def applicant_final_review_page(request: Request) -> Response:
        return workspace_page(request, workspace_pages["/applicant/final-review"])

    if include_session_probe:
        @application.get("/api/applicant/session")
        def applicant_entra_session(request: Request) -> JSONResponse:
            session = auth.authenticate(request.cookies.get(SESSION_COOKIE, ""))
            if session is None:
                return JSONResponse(
                    status_code=401,
                    content={"authenticated": False, "syntheticAdmin": False},
                )
            return JSONResponse(
                {
                    "authenticated": True,
                    "syntheticAdmin": session.synthetic_actor_identity is not None,
                }
            )
