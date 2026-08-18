"""Administrator-only entry into a server-scoped synthetic applicant workspace."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response

from app.applicant.synthetic import SyntheticApplicantWorkspaceService
from app.identity import AuthenticatedIdentity
from app.http import is_same_origin_write
from app.navigation import INTERNAL_GROUPS
from app.routes.applicant_auth import CSRF_COOKIE, SESSION_COOKIE


def register_internal_synthetic_routes(
    application: FastAPI,
    *,
    authenticated: Callable[[Request], AuthenticatedIdentity],
    synthetic: SyntheticApplicantWorkspaceService,
) -> None:
    @application.post("/api/internal/synthetic-applicants")
    async def create_synthetic_applicant(request: Request) -> Response:
        principal = authenticated(request)
        if (
            INTERNAL_GROUPS.administrators not in principal.groups
            or not is_same_origin_write(request)
            or await request.body()
        ):
            return Response(status_code=404)
        try:
            session = synthetic.create(
                principal.identity.key,
                INTERNAL_GROUPS.administrators,
            )
        except PermissionError:
            return Response(status_code=404)

        response = RedirectResponse("/applicant/review", status_code=303)
        max_age = max(
            1,
            int((session.absolute_expires_at - datetime.now(UTC)).total_seconds()),
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
