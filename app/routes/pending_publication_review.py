"""Internal rapid publication-classification routes."""
from __future__ import annotations
from collections.abc import Callable
from pathlib import Path
from uuid import UUID
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from app.http import is_same_origin_write
from app.identity import AuthenticatedIdentity
from app.internal_shell import render_internal_page
from app.navigation import INTERNAL_GROUPS
from app.pending_publication_review import PendingPublicationReviewRepository

_DECISIONS = {"published": "PUBLISHED", "preprint": "ACCEPTED_PREPRINT", "remove": "NON_PUBLICATION"}

def register_pending_publication_review_routes(application: FastAPI, *, authenticated: Callable[[Request], AuthenticatedIdentity], repository: PendingPublicationReviewRepository, page: Path) -> None:
    @application.get("/internal/review-pending-papers")
    def pending_page(request: Request) -> HTMLResponse:
        principal = authenticated(request)
        _group(principal)
        return HTMLResponse(render_internal_page(page.read_text(encoding="utf-8"), principal))

    @application.get("/api/internal/pending-publications")
    def pending(request: Request) -> JSONResponse:
        items = repository.list(_group(authenticated(request)))
        return JSONResponse(jsonable_encoder({"publications": [
            {"publicationId": x.publication_id, "applicantName": x.applicant_name,
             "authors": x.authors, "title": x.title, "journal": x.journal,
             "volume": x.volume, "pages": x.pages, "year": x.year, "doi": x.doi,
             "url": x.url, "rawCitation": x.raw_citation, "resolutionStatus": x.resolution_status}
            for x in items]}))

    @application.post("/api/internal/pending-publications/{publication_id}/{decision}")
    async def record(publication_id: UUID, decision: str, request: Request) -> JSONResponse:
        principal = authenticated(request)
        group = _group(principal)
        disposition = _DECISIONS.get(decision)
        if disposition is None:
            raise HTTPException(status_code=404)
        if not is_same_origin_write(request):
            return JSONResponse(status_code=403, content={"message": "The request is invalid."})
        if await request.body():
            return JSONResponse(status_code=400, content={"message": "The request is invalid."})
        try:
            repository.record(publication_id, disposition, principal.identity.key, group)
        except LookupError:
            return JSONResponse(status_code=409, content={"message": "This paper is no longer pending review."})
        return JSONResponse({"publicationId": str(publication_id), "disposition": disposition})

def _group(principal: AuthenticatedIdentity) -> str:
    if INTERNAL_GROUPS.administrators in principal.groups:
        return INTERNAL_GROUPS.administrators
    if INTERNAL_GROUPS.trustees in principal.groups:
        return INTERNAL_GROUPS.trustees
    raise HTTPException(status_code=404)
