"""Session-scoped final review and atomic submission routes."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.applicant.finalize import (
    FinalizationBlocked,
    FinalizationService,
    FinalizationSessionUnavailable,
)
from app.auth.applicant import ApplicantAuthService, ApplicantSessionContext
from app.routes.applicant_auth import CSRF_COOKIE, SESSION_COOKIE


def register_applicant_finalize_routes(
    application: FastAPI,
    *,
    auth: ApplicantAuthService,
    finalization: FinalizationService,
) -> None:
    @application.get("/api/applicant/finalization")
    def applicant_finalization_preview(request: Request) -> JSONResponse:
        session = _session(auth, request)
        if session is None:
            return _unauthorized()
        return JSONResponse(jsonable_encoder(finalization.preview(session)))

    @application.post("/api/applicant/finalization")
    def finalize_applicant_application(request: Request) -> JSONResponse:
        session = _session(auth, request)
        if session is None:
            return _unauthorized()
        if session.synthetic_actor_identity is not None:
            return JSONResponse(
                status_code=404,
                content={"message": "The application submission is unavailable."},
            )
        if not _valid_csrf(auth, session, request):
            return JSONResponse(
                status_code=403, content={"message": "The request was rejected."}
            )
        try:
            confirmation = finalization.submit(session)
        except FinalizationSessionUnavailable:
            return _unauthorized()
        except FinalizationBlocked as error:
            return JSONResponse(
                status_code=422,
                content={
                    "message": "Complete every unresolved item before submitting.",
                    "unresolved": list(error.unresolved),
                },
            )
        return JSONResponse(
            jsonable_encoder(
                {
                    "submitted": True,
                    "confirmationId": confirmation.confirmation_id,
                    "confirmedAtUtc": confirmation.confirmed_at_utc,
                }
            )
        )


def _session(
    auth: ApplicantAuthService, request: Request
) -> ApplicantSessionContext | None:
    return auth.authenticate(request.cookies.get(SESSION_COOKIE, ""))


def _valid_csrf(
    auth: ApplicantAuthService,
    session: ApplicantSessionContext,
    request: Request,
) -> bool:
    header = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(CSRF_COOKIE, "")
    return bool(header) and header == cookie and auth.valid_csrf(session, header)


def _unauthorized() -> JSONResponse:
    return JSONResponse(status_code=401, content={"message": "Authentication required."})
