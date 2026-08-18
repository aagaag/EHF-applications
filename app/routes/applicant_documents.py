"""Applicant-scoped controlled PDF upload and download routes."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from app.applicant.documents import (
    ApplicantDocumentService,
    DocumentUnavailable,
    DocumentUploadRejected,
)
from app.auth.applicant import ApplicantAuthService, ApplicantSessionContext
from app.routes.applicant_auth import CSRF_COOKIE, SESSION_COOKIE


MAX_UPLOAD_READ_BYTES = 25 * 1024 * 1024 + 1


def register_applicant_document_routes(
    application: FastAPI,
    *,
    auth: ApplicantAuthService,
    documents: ApplicantDocumentService,
) -> None:
    @application.get("/api/applicant/documents")
    def applicant_document_slots(request: Request) -> JSONResponse:
        session = _session(auth, request)
        if session is None:
            return _unauthorized()
        if session.synthetic_actor_identity is not None:
            return _unavailable()
        slots = []
        for slot in documents.slots(session):
            if slot.active_version_id is not None:
                status = "Available"
            elif slot.upload_mode == "MISSING":
                status = "Upload requested"
            elif slot.upload_mode == "REPLACEMENT":
                status = "Replacement requested"
            else:
                status = "Not yet available"
            slots.append(
                {
                    "slotId": str(slot.slot_id),
                    "code": slot.code,
                    "label": slot.label,
                    "required": slot.required,
                    "uploadMode": slot.upload_mode,
                    "rowVersion": slot.row_version,
                    "status": status,
                    "downloadAvailable": slot.active_version_id is not None,
                }
            )
        return JSONResponse({"slots": slots})

    @application.post("/api/applicant/documents/{slot_id}/upload")
    async def upload_applicant_document(
        slot_id: UUID,
        request: Request,
        expectedRowVersion: int = Form(...),
        file: UploadFile = File(...),
    ) -> JSONResponse:
        session = _session(auth, request)
        if session is None:
            return _unauthorized()
        if session.synthetic_actor_identity is not None:
            return _unavailable()
        if not _valid_csrf(auth, session, request):
            return JSONResponse(status_code=403, content={"message": "The request was rejected."})
        payload = await file.read(MAX_UPLOAD_READ_BYTES)
        await file.close()
        if len(payload) >= MAX_UPLOAD_READ_BYTES:
            return JSONResponse(status_code=413, content={"message": "The PDF is too large."})
        with TemporaryDirectory(prefix="ehf-u-") as temporary:
            source = Path(temporary) / "u"
            source.write_bytes(payload)
            try:
                documents.upload(
                    session,
                    slot_id,
                    expectedRowVersion,
                    source,
                    file.filename or "upload.pdf",
                    file.content_type or "application/octet-stream",
                )
            except DocumentUnavailable:
                return JSONResponse(
                    status_code=404,
                    content={"message": "The document slot is unavailable."},
                )
            except DocumentUploadRejected:
                return JSONResponse(
                    status_code=422,
                    content={
                        "message": "The PDF could not be accepted. Your existing document is unchanged."
                    },
                )
        return JSONResponse(
            status_code=202,
            content={"status": "PENDING", "message": "Uploaded for Foundation review."},
        )

    @application.get("/api/applicant/documents/{slot_id}/download")
    def download_applicant_document(slot_id: UUID, request: Request) -> Response:
        session = _session(auth, request)
        if session is None:
            return _unauthorized()
        if session.synthetic_actor_identity is not None:
            return _unavailable()
        payload = documents.download(session, slot_id)
        if payload is None:
            return JSONResponse(
                status_code=404,
                content={"message": "The document slot is unavailable."},
            )
        return Response(
            payload,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="document.pdf"'},
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


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=404, content={"message": "The document is unavailable."})
