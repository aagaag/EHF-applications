from __future__ import annotations

import base64
import io
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.applicant.documents import ApplicantDocumentService, DocumentSlotRepository
from app.auth.applicant import (
    ApplicantAuthService,
    CapturingVerificationDelivery,
    InMemoryApplicantAuthRepository,
    invitation_token_hash,
    new_opaque_token,
)
from app.auth.rate_limit import InMemoryRateLimiter, RateLimitPolicy
from app.auth.turnstile import TurnstileVerifier
from app.config import Settings
from app.documents.keys import load_keyring
from app.documents.malware import ScanResult
from app.documents.store import EncryptedObjectStore
from app.main import ReadinessChecks, create_app


APPLICATION_A = UUID("82000000-0000-4000-8000-000000000001")
APPLICATION_B = UUID("82000000-0000-4000-8000-000000000002")


class CleanScanner:
    def scan(self, _source: Path) -> ScanResult:
        return ScanResult("synthetic", "CLEAN", datetime.now(UTC))


def _pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def _client(tmp_path: Path) -> tuple[TestClient, DocumentSlotRepository, object, object]:
    credential = tmp_path / "k.json"
    credential.write_text(
        json.dumps(
            {
                "active_key_version": 1,
                "keys": {"1": base64.b64encode(bytes(range(32))).decode("ascii")},
            }
        ),
        encoding="utf-8",
    )
    os.chmod(credential, 0o600)
    slots = DocumentSlotRepository()
    slot = slots.add_slot(APPLICATION_A, "CV", "Curriculum vitae", required=True)
    slot = slots.open_slot(APPLICATION_A, slot.slot_id, "MISSING", "admin", "Missing")
    other_slot = slots.add_slot(APPLICATION_B, "CV", "Other curriculum vitae", required=True)
    document_service = ApplicantDocumentService(
        slots,
        EncryptedObjectStore(tmp_path / "objects", load_keyring(credential)),
        CleanScanner(),
    )
    auth_repository = InMemoryApplicantAuthRepository()
    delivery = CapturingVerificationDelivery()
    auth = ApplicantAuthService(
        auth_repository,
        delivery,
        otp_pepper=b"synthetic-otp-pepper-with-at-least-32-bytes",
        session_pepper=b"synthetic-session-pepper-at-least-32-bytes",
        code_factory=lambda: "654321",
    )
    invitation = new_opaque_token()
    auth_repository.add_invitation(
        APPLICATION_A,
        invitation_token_hash(invitation),
        "documents@example.test",
        datetime.now(UTC) + timedelta(days=1),
    )
    turnstile = TurnstileVerifier(
        "synthetic-secret",
        "localhost",
        lambda _secret, _token, _ip: {
            "success": True,
            "hostname": "localhost",
            "action": "applicant-code-request",
        },
    )
    application = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        applicant_auth_service=auth,
        applicant_turnstile=turnstile,
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=20, window=timedelta(minutes=10))
        ),
        applicant_document_service=document_service,
    )
    client = TestClient(application, base_url="https://localhost")
    client.get(f"/a/{invitation}")
    client.post("/api/applicant/auth/code", json={"turnstileToken": "documents-turnstile"})
    client.post("/api/applicant/auth/verify", json={"code": "654321"})
    return client, slots, slot, other_slot


def test_document_routes_list_only_session_slots_and_accept_one_open_pdf(tmp_path: Path) -> None:
    """Break caught: document API could list another record or bypass CSRF/open-slot checks."""
    client, slots, slot, _other_slot = _client(tmp_path)
    try:
        listed = client.get("/api/applicant/documents")
        assert listed.status_code == 200
        assert [(item["label"], item["uploadMode"]) for item in listed.json()["slots"]] == [
            ("Curriculum vitae", "MISSING")
        ]
        assert "Other curriculum vitae" not in listed.text

        without_csrf = client.post(
            f"/api/applicant/documents/{slot.slot_id}/upload",
            data={"expectedRowVersion": str(slot.row_version)},
            files={"file": ("cv.pdf", _pdf(), "application/pdf")},
        )
        assert without_csrf.status_code == 403

        accepted = client.post(
            f"/api/applicant/documents/{slot.slot_id}/upload",
            data={"expectedRowVersion": str(slot.row_version)},
            files={"file": ("cv.pdf", _pdf(), "application/pdf")},
            headers={"x-csrf-token": client.cookies.get("__Host-ehf_applicant_csrf")},
        )
        assert accepted.status_code == 202
        assert accepted.json() == {"status": "PENDING", "message": "Uploaded for Foundation review."}
        assert len(slots.versions(slot.slot_id)) == 1
    finally:
        client.close()


def test_guessed_other_applicant_slot_has_neutral_not_found_response(tmp_path: Path) -> None:
    """Break caught: upload errors could disclose another applicant's slot identifier."""
    client, _slots, _slot, other_slot = _client(tmp_path)
    try:
        response = client.post(
            f"/api/applicant/documents/{other_slot.slot_id}/upload",
            data={"expectedRowVersion": str(other_slot.row_version)},
            files={"file": ("cv.pdf", _pdf(), "application/pdf")},
            headers={"x-csrf-token": client.cookies.get("__Host-ehf_applicant_csrf")},
        )

        assert response.status_code == 404
        assert response.json() == {"message": "The document slot is unavailable."}
    finally:
        client.close()
