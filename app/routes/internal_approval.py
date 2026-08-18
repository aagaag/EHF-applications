"""Cloudflare-identity protected applicant-submission review routes."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.applicant.approval import ApplicantApprovalService, REVIEWER_GROUPS
from app.identity import AuthenticatedIdentity
from app.http import is_same_origin_write


def register_internal_approval_routes(
    application: FastAPI,
    *,
    authenticated: Callable[[Request], AuthenticatedIdentity],
    approval: ApplicantApprovalService,
) -> None:
    @application.get("/api/internal/applicant-submissions")
    def pending_applicant_submissions(request: Request) -> JSONResponse:
        principal = authenticated(request)
        _reviewer_group(principal)
        return JSONResponse(
            jsonable_encoder(
                {
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
        return JSONResponse(
            jsonable_encoder(
                {
                    "confirmationId": review.confirmation_id,
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
        return JSONResponse(jsonable_encoder({
            "confirmationId": bundle.confirmation_id,
            "applicationId": bundle.application_id,
            "baseline": bundle.baseline,
            "manifest": bundle.manifest,
            "drafts": bundle.drafts,
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
