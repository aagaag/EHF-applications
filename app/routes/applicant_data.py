"""Session-scoped applicant data routes with no browser-supplied application ID."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.applicant.projection import ApplicantProjectionService
from app.auth.applicant import ApplicantAuthService
from app.routes.applicant_auth import SESSION_COOKIE


def register_applicant_data_routes(
    application: FastAPI,
    *,
    auth: ApplicantAuthService,
    projection: ApplicantProjectionService,
) -> None:
    @application.get("/api/applicant/application")
    def applicant_application(request: Request) -> JSONResponse:
        session = auth.authenticate(request.cookies.get(SESSION_COOKIE, ""))
        if session is None:
            return JSONResponse(status_code=401, content={"message": "Authentication required."})
        payload = projection.load(session)
        if payload is None:
            return JSONResponse(status_code=404, content={"message": "The record is unavailable."})
        return JSONResponse(payload)

    @application.get("/api/applicant/documents/{document_id}/metadata")
    def applicant_document_metadata(document_id: str, request: Request) -> JSONResponse:
        session = auth.authenticate(request.cookies.get(SESSION_COOKIE, ""))
        if session is None:
            return JSONResponse(status_code=401, content={"message": "Authentication required."})
        document = projection.visible_document(session, document_id)
        if document is None:
            return JSONResponse(status_code=404, content={"message": "The record is unavailable."})
        return JSONResponse(document)
