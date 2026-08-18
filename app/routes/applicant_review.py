"""CSRF-protected applicant autosave and confirmation routes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.applicant.drafts import (
    CorrectionRequired,
    DraftConflict,
    DraftLocked,
    DraftSnapshot,
)
from app.applicant.fields import FieldValidationError
from app.applicant.publications import (
    InvalidDoi,
    PublicationLookup,
    PublicationLookupUnavailable,
    PublicationNotFound,
)
from app.applicant.review import ApplicantReviewService
from app.auth.applicant import ApplicantAuthService, ApplicantSessionContext
from app.auth.rate_limit import InMemoryRateLimiter
from app.routes.applicant_auth import CSRF_COOKIE, SESSION_COOKIE


def register_applicant_review_routes(
    application: FastAPI,
    *,
    auth: ApplicantAuthService,
    review: ApplicantReviewService,
    publications: PublicationLookup | None = None,
    rate_limiter: InMemoryRateLimiter | None = None,
) -> None:
    @application.get("/api/applicant/review/fields")
    def applicant_field_metadata(request: Request) -> JSONResponse:
        session = _session(auth, request)
        if session is None:
            return _unauthorized()
        return JSONResponse(jsonable_encoder({"fields": review.metadata()}))

    @application.get("/api/applicant/review/{section}")
    def applicant_section(section: str, request: Request) -> JSONResponse:
        session = _session(auth, request)
        if session is None:
            return _unauthorized()
        snapshot = review.load(session, section)
        if snapshot is None:
            return JSONResponse(
                {"rowVersion": None, "values": {}, "confirmed": False}
            )
        return JSONResponse(jsonable_encoder(_snapshot(review, session, snapshot)))

    @application.put("/api/applicant/review/{section}")
    async def save_applicant_section(section: str, request: Request) -> JSONResponse:
        session = _session(auth, request)
        if session is None:
            return _unauthorized()
        if not _valid_csrf(auth, session, request):
            return JSONResponse(status_code=403, content={"message": "The request was rejected."})
        payload = await _json_object(request)
        values = payload.get("values")
        expected = payload.get("expectedRowVersion")
        if not isinstance(values, dict) or (expected is not None and not isinstance(expected, int)):
            return JSONResponse(status_code=400, content={"message": "The request is invalid."})
        try:
            snapshot = review.save(session, section, values, expected)
        except FieldValidationError as error:
            return JSONResponse(status_code=422, content={"errors": error.errors})
        except DraftConflict:
            return _conflict(review, session, section)
        except DraftLocked:
            return JSONResponse(status_code=423, content={"message": "This section is locked."})
        response = _snapshot(review, session, snapshot)
        response["saved"] = True
        return JSONResponse(jsonable_encoder(response))

    @application.post("/api/applicant/review/{section}/confirm")
    async def confirm_applicant_section(section: str, request: Request) -> JSONResponse:
        session = _session(auth, request)
        if session is None:
            return _unauthorized()
        if not _valid_csrf(auth, session, request):
            return JSONResponse(status_code=403, content={"message": "The request was rejected."})
        payload = await _json_object(request)
        row_version = payload.get("rowVersion")
        if not isinstance(row_version, int):
            return JSONResponse(status_code=400, content={"message": "The request is invalid."})
        try:
            confirmation = review.confirm(session, section, row_version)
        except FieldValidationError as error:
            return JSONResponse(status_code=422, content={"errors": error.errors})
        except CorrectionRequired as error:
            return JSONResponse(status_code=422, content={"message": str(error)})
        except DraftConflict:
            return _conflict(review, session, section)
        return JSONResponse(
            {
                "confirmed": True,
                "rowVersion": confirmation.row_version,
                "canonicalSha256": confirmation.canonical_sha256,
            }
        )

    if publications is not None:
        @application.post("/api/applicant/review/publications/lookup")
        async def lookup_applicant_publication(request: Request) -> JSONResponse:
            session = _session(auth, request)
            if session is None:
                return _unauthorized()
            if not _valid_csrf(auth, session, request):
                return JSONResponse(
                    status_code=403, content={"message": "The request was rejected."}
                )
            if rate_limiter is not None and not rate_limiter.allow(
                "APPLICANT_DOI", str(session.application_id), datetime.now(UTC)
            ):
                return JSONResponse(
                    status_code=429,
                    content={"message": "Too many publication lookups. Please wait and try again."},
                )
            payload = await _json_object(request)
            if set(payload) != {"doi"}:
                return JSONResponse(
                    status_code=400, content={"message": "The request is invalid."}
                )
            try:
                metadata = await asyncio.to_thread(publications.lookup, payload["doi"])
            except InvalidDoi:
                return JSONResponse(
                    status_code=422, content={"message": "Enter a valid DOI."}
                )
            except PublicationNotFound:
                return JSONResponse(
                    status_code=404,
                    content={"message": "No publication was found for this DOI."},
                )
            except PublicationLookupUnavailable:
                return JSONResponse(
                    status_code=503,
                    content={"message": "Publication lookup is temporarily unavailable."},
                )
            publication = dict(metadata)
            publication["lookupReceipt"] = review.publication_lookup_receipt(
                session, publication.get("doi")
            )
            return JSONResponse(jsonable_encoder({"publication": publication}))


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


def _snapshot(
    review: ApplicantReviewService,
    session: ApplicantSessionContext,
    snapshot: DraftSnapshot,
) -> dict[str, Any]:
    returned = None
    if snapshot.return_reason is not None:
        returned = {
            "reason": snapshot.return_reason,
            "returnedAtUtc": snapshot.returned_at_utc,
        }
    response = {
        "rowVersion": snapshot.row_version,
        "values": snapshot.values,
        "confirmed": review.is_current(session, snapshot.section, snapshot),
    }
    if returned is not None:
        response["returnedForCorrection"] = returned
    return response


def _conflict(
    review: ApplicantReviewService,
    session: ApplicantSessionContext,
    section: str,
) -> JSONResponse:
    current = review.load(session, section)
    return JSONResponse(
        status_code=409,
        content={
            "message": "The section changed in another session.",
            "current": jsonable_encoder(_snapshot(review, session, current)) if current else None,
        },
    )


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _unauthorized() -> JSONResponse:
    return JSONResponse(status_code=401, content={"message": "Authentication required."})
