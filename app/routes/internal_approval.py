"""Cloudflare-identity protected applicant-submission review routes."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse

from app.applicant.approval import (
    ApplicantApprovalBlocked,
    ApplicantApprovalService,
    REVIEWER_GROUPS,
)
from app.applicant.documents import ApplicantDocumentService
from app.applicant.fields import upgrade_legacy_applicant, upgrade_legacy_section
from app.applicant.admin_preview import render_applicant_preview
from app.identity import AuthenticatedIdentity
from app.http import is_same_origin_write
from app.internal_shell import authorization_pills, help_navigation, primary_navigation
from app.navigation import INTERNAL_GROUPS
from app.routes.documents import pdf_response


def register_internal_approval_routes(
    application: FastAPI,
    *,
    authenticated: Callable[[Request], AuthenticatedIdentity],
    approval: ApplicantApprovalService,
    documents: ApplicantDocumentService | None = None,
) -> None:
    @application.get("/api/internal/applicant-previews")
    def applicant_previews(request: Request) -> JSONResponse:
        principal = authenticated(request)
        group = _administrator_group(principal)
        return JSONResponse(jsonable_encoder({
            "applications": [
                {
                    "applicationId": item.application_id,
                    "applicantName": item.applicant_name,
                    "applicationStatus": item.application_status,
                    "href": f"/internal/applicants/{item.application_id}",
                }
                for item in sorted(
                    approval.previews(group),
                    key=lambda item: (item.applicant_name.casefold(), str(item.application_id)),
                )
            ]
        }))

    @application.get("/internal/applicant-previews/{application_id}")
    @application.get("/internal/applicants/{application_id}")
    def applicant_preview(application_id: str, request: Request) -> HTMLResponse:
        principal = authenticated(request)
        group = _administrator_group(principal)
        try:
            preview_id = UUID(application_id)
        except ValueError:
            raise HTTPException(status_code=404) from None
        try:
            bundle = approval.preview(
                preview_id, actor=principal.identity.key, actor_group=group
            )
        except LookupError:
            raise HTTPException(status_code=404) from None
        return HTMLResponse(
            render_applicant_preview(
                bundle,
                primary_navigation=primary_navigation(principal),
                help_navigation=help_navigation(principal),
                authorization_pills=authorization_pills(principal),
                back_href=request.query_params.get("return"),
            )
        )

    @application.get("/api/internal/applicant-submissions")
    def pending_applicant_submissions(request: Request) -> JSONResponse:
        principal = authenticated(request)
        group = _reviewer_group(principal)
        return JSONResponse(
            jsonable_encoder(
                {
                    "capabilities": {
                        "returnForCorrection": group == "EHF-Administrators"
                    },
                    "submissions": [
                        {
                            "confirmationId": item.confirmation_id,
                            "applicationId": item.application_id,
                            "submittedAtUtc": item.submitted_at_utc,
                            "status": item.status,
                        }
                        for item in approval.pending()
                    ]
                }
            )
        )

    @application.post("/api/internal/applicant-submissions/{confirmation_id}/approve")
    async def approve_applicant_submission(
        confirmation_id: UUID, request: Request
    ) -> JSONResponse:
        principal = authenticated(request)
        group = _reviewer_group(principal)
        if not is_same_origin_write(request):
            return JSONResponse(status_code=403, content={"message": "The request is invalid."})
        if await request.body():
            return JSONResponse(
                status_code=400, content={"message": "The request is invalid."}
            )
        try:
            review = approval.approve(
                confirmation_id,
                actor=principal.identity.key,
                actor_group=group,
            )
        except LookupError:
            return JSONResponse(
                status_code=404, content={"message": "The submission is unavailable."}
            )
        except ApplicantApprovalBlocked as error:
            return JSONResponse(
                status_code=409,
                content={
                    "code": "section_requires_correction",
                    "section": error.section,
                    "message": str(error),
                },
            )
        return JSONResponse(
            jsonable_encoder(
                {
                    "confirmationId": review.confirmation_id,
                    "status": review.status,
                    "reviewedAtUtc": review.reviewed_at_utc,
                }
            )
        )

    @application.post(
        "/api/internal/applicant-submissions/{confirmation_id}/return-for-correction"
    )
    async def return_applicant_submission_for_correction(
        confirmation_id: UUID, request: Request
    ) -> JSONResponse:
        principal = authenticated(request)
        group = _reviewer_group(principal)
        if group != "EHF-Administrators":
            raise HTTPException(status_code=404)
        if not is_same_origin_write(request):
            return JSONResponse(status_code=403, content={"message": "The request is invalid."})
        try:
            payload = await request.json()
            section = payload.get("section") if isinstance(payload, dict) else None
            reason = payload.get("reason") if isinstance(payload, dict) else None
        except (TypeError, ValueError):
            section = reason = None
        if not isinstance(section, str) or not isinstance(reason, str):
            return JSONResponse(status_code=400, content={"message": "A section and reason are required."})
        try:
            review = approval.return_for_correction(
                confirmation_id,
                section=section,
                reason=reason,
                actor=principal.identity.key,
                actor_group=group,
            )
        except ValueError:
            return JSONResponse(status_code=400, content={"message": "A valid section and reason are required."})
        except LookupError:
            return JSONResponse(status_code=404, content={"message": "The submission is unavailable."})
        return JSONResponse(
            jsonable_encoder(
                {
                    "confirmationId": review.confirmation_id,
                    "applicationId": review.application_id,
                    "status": review.status,
                    "reviewedAtUtc": review.reviewed_at_utc,
                }
            )
        )

    @application.get("/api/internal/applicant-submissions/{confirmation_id}")
    def applicant_submission_detail(
        confirmation_id: UUID, request: Request
    ) -> JSONResponse:
        principal = authenticated(request)
        _reviewer_group(principal)
        try:
            bundle = approval.detail(confirmation_id)
        except LookupError:
            return JSONResponse(status_code=404, content={"message": "The submission is unavailable."})
        baseline = dict(bundle.baseline)
        applicant = baseline.get("applicant")
        if isinstance(applicant, dict):
            baseline["applicant"] = upgrade_legacy_applicant(applicant)
        drafts = {
            section: upgrade_legacy_section(section, values)
            for section, values in bundle.drafts.items()
        }
        return JSONResponse(jsonable_encoder({
            "confirmationId": bundle.confirmation_id,
            "applicationId": bundle.application_id,
            "baseline": baseline,
            "manifest": bundle.manifest,
            "drafts": drafts,
        }))

    @application.get("/api/internal/applicant-document-submissions")
    def pending_applicant_document_submissions(request: Request) -> JSONResponse:
        principal = authenticated(request)
        _reviewer_group(principal)
        return JSONResponse(jsonable_encoder({
            "submissions": [
                {
                    "submissionId": item.submission_id,
                    "applicationId": item.application_id,
                    "slotId": item.slot_id,
                    "versionId": item.version_id,
                    "displayName": item.display_name,
                    "submittedAtUtc": item.submitted_at_utc,
                    "status": item.status,
                }
                for item in approval.pending_documents()
            ]
        }))

    @application.get("/api/internal/applicants/{application_id}/documents")
    def internal_applicant_documents(
        application_id: UUID, request: Request
    ) -> JSONResponse:
        principal = authenticated(request)
        group = _reviewer_group(principal)
        if documents is None:
            raise HTTPException(status_code=404)
        items = documents.internal_documents(
            application_id, actor=principal.identity.key, actor_group=group
        )
        return JSONResponse(
            jsonable_encoder(
                {
                    "documents": [
                        {
                            "slotId": item.slot_id,
                            "versionId": item.version_id,
                            "code": item.code,
                            "label": item.label,
                            "versionNumber": item.version_number,
                            "status": item.status,
                        }
                        for item in items
                    ],
                    "packageAvailable": bool(items),
                }
            )
        )

    @application.get("/api/internal/applicants/{application_id}/documents/package/view")
    def view_internal_applicant_package(
        application_id: UUID, request: Request
    ) -> Response:
        return _internal_package_response(
            application_id, request, authenticated, documents, disposition="inline"
        )

    @application.get("/api/internal/applicants/{application_id}/documents/package/download")
    def download_internal_applicant_package(
        application_id: UUID, request: Request
    ) -> Response:
        return _internal_package_response(
            application_id, request, authenticated, documents, disposition="attachment"
        )

    @application.get(
        "/api/internal/applicants/{application_id}/documents/{version_id}/view"
    )
    def view_internal_applicant_document(
        application_id: UUID, version_id: UUID, request: Request
    ) -> Response:
        return _internal_document_response(
            application_id, version_id, request, authenticated, documents,
            purpose="VIEW", disposition="inline",
        )

    @application.get(
        "/api/internal/applicants/{application_id}/documents/{version_id}/download"
    )
    def download_internal_applicant_document(
        application_id: UUID, version_id: UUID, request: Request
    ) -> Response:
        return _internal_document_response(
            application_id, version_id, request, authenticated, documents,
            purpose="DOWNLOAD", disposition="attachment",
        )

    @application.post(
        "/api/internal/applicant-document-submissions/{submission_id}/accept"
    )
    async def accept_applicant_document(
        submission_id: UUID, request: Request
    ) -> JSONResponse:
        principal = authenticated(request)
        group = _reviewer_group(principal)
        if not is_same_origin_write(request):
            return JSONResponse(status_code=403, content={"message": "The request is invalid."})
        if await request.body():
            return JSONResponse(status_code=400, content={"message": "The request is invalid."})
        try:
            review = approval.accept_document(
                submission_id, actor=principal.identity.key, actor_group=group
            )
        except LookupError:
            return JSONResponse(status_code=404, content={"message": "The submission is unavailable."})
        return JSONResponse(jsonable_encoder({
            "submissionId": review.submission_id,
            "status": review.status,
            "reviewedAtUtc": review.reviewed_at_utc,
        }))

    @application.post(
        "/api/internal/applicant-document-submissions/{submission_id}/reject"
    )
    async def reject_applicant_document(
        submission_id: UUID, request: Request
    ) -> JSONResponse:
        principal = authenticated(request)
        group = _reviewer_group(principal)
        if not is_same_origin_write(request):
            return JSONResponse(status_code=403, content={"message": "The request is invalid."})
        try:
            payload = await request.json()
            reason = payload.get("reason") if isinstance(payload, dict) else None
        except (TypeError, ValueError):
            reason = None
        if not isinstance(reason, str) or not reason.strip():
            return JSONResponse(status_code=400, content={"message": "A reason is required."})
        try:
            review = approval.reject_document(
                submission_id, actor=principal.identity.key,
                actor_group=group, reason=reason,
            )
        except LookupError:
            return JSONResponse(status_code=404, content={"message": "The submission is unavailable."})
        return JSONResponse(jsonable_encoder({
            "submissionId": review.submission_id,
            "status": review.status,
            "reviewedAtUtc": review.reviewed_at_utc,
        }))


def _reviewer_group(principal: AuthenticatedIdentity) -> str:
    if principal.groups & {"EHF-Administrators"}:
        return "EHF-Administrators"
    if principal.groups & {"EHF-Trustees"}:
        return "EHF-Trustees"
    raise HTTPException(status_code=404)


def _administrator_group(principal: AuthenticatedIdentity) -> str:
    if INTERNAL_GROUPS.administrators in principal.groups:
        return INTERNAL_GROUPS.administrators
    raise HTTPException(status_code=404)


def _internal_document_response(
    application_id: UUID,
    version_id: UUID,
    request: Request,
    authenticated: Callable[[Request], AuthenticatedIdentity],
    documents: ApplicantDocumentService | None,
    *,
    purpose: str,
    disposition: str,
) -> Response:
    principal = authenticated(request)
    group = _reviewer_group(principal)
    if documents is None:
        return _internal_document_unavailable()
    payload = documents.internal_download(
        application_id,
        version_id,
        actor=principal.identity.key,
        actor_group=group,
        purpose=purpose,
    )
    if payload is None:
        return _internal_document_unavailable()
    return pdf_response(payload, disposition=disposition, filename="document.pdf")


def _internal_package_response(
    application_id: UUID,
    request: Request,
    authenticated: Callable[[Request], AuthenticatedIdentity],
    documents: ApplicantDocumentService | None,
    *,
    disposition: str,
) -> Response:
    principal = authenticated(request)
    group = _reviewer_group(principal)
    if documents is None:
        return _internal_document_unavailable()
    payload = documents.internal_package(
        application_id, actor=principal.identity.key, actor_group=group
    )
    if payload is None:
        return _internal_document_unavailable()
    return pdf_response(
        payload,
        disposition=disposition,
        filename="application-document-package.pdf",
    )


def _internal_document_unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=404, content={"message": "The document is unavailable."}
    )
