"""Applicant upload failure contract: distinct, actionable outcomes per failure class."""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.applicant.documents import (
    ApplicantDocumentService,
    ApplicantDocumentSlot,
    DocumentAlreadySubmitted,
    DocumentScannerUnavailable,
    DocumentUnavailable,
    DocumentUploadRejected,
)
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
from app.main import ReadinessChecks, create_app

APPLICATION_A = UUID("82000000-0000-4000-8000-000000000001")
SLOT_ID = UUID("83000000-0000-4000-8000-000000000001")


class FailingDocumentService(ApplicantDocumentService):
    """Minimal document service whose upload always fails in one defined way."""

    def __init__(self, failure: Exception) -> None:  # noqa: D107 - test double
        self._failure = failure

    def slots(self, session):  # type: ignore[no-untyped-def]
        return (
            ApplicantDocumentSlot(
                slot_id=SLOT_ID,
                application_id=session.application_id,
                code="CV",
                label="Curriculum vitae",
                required=True,
                applicant_visible=True,
                upload_mode="MISSING",
                row_version=1,
                active_version_id=None,
                document_id=None,
                document_type="CV",
            ),
        )

    def upload(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise self._failure


def _client(tmp_path: Path, failure: Exception) -> TestClient:
    credential = tmp_path / "keyring.json"
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
    repository = InMemoryApplicantAuthRepository()
    auth = ApplicantAuthService(
        repository,
        CapturingVerificationDelivery(),
        otp_pepper=b"synthetic-otp-pepper-with-at-least-32-bytes",
        session_pepper=b"synthetic-session-pepper-at-least-32-bytes",
        code_factory=lambda: "654321",
    )
    invitation = new_opaque_token()
    repository.add_invitation(
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
        applicant_document_service=FailingDocumentService(failure),
    )
    client = TestClient(application, base_url="https://localhost")
    client.get(f"/a/{invitation}")
    client.post("/api/applicant/auth/code", json={"turnstileToken": "documents-turnstile"})
    client.post("/api/applicant/auth/verify", json={"code": "654321"})
    return client


def _upload(client: TestClient):
    return client.post(
        f"/api/applicant/documents/{SLOT_ID}/upload",
        data={"expectedRowVersion": "1"},
        files={"file": ("cv.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers={"x-csrf-token": client.cookies.get("__Host-ehf_applicant_csrf")},
    )


@pytest.mark.parametrize(
    ("failure", "status", "message"),
    [
        (
            DocumentScannerUnavailable("Document scanning is unavailable."),
            503,
            "Document scanning is temporarily unavailable. Please try again later.",
        ),
        (
            DocumentAlreadySubmitted("An identical document is already registered."),
            409,
            "This document is already part of your application.",
        ),
        (
            DocumentUploadRejected("The PDF could not be accepted."),
            422,
            "The PDF could not be accepted. Your existing document is unchanged.",
        ),
        (
            DocumentUnavailable("The document slot is unavailable."),
            404,
            "The document slot is unavailable.",
        ),
    ],
)
def test_upload_failures_keep_their_distinct_outcome(
    tmp_path: Path, failure: Exception, status: int, message: str
) -> None:
    """Break caught: a missing scanner, a duplicate and a broken PDF could be indistinguishable."""
    client = _client(tmp_path, failure)
    try:
        response = _upload(client)
        assert response.status_code == status
        assert response.json() == {"message": message}
        if status == 503:
            assert response.headers["retry-after"] == "300"
    finally:
        client.close()


def test_upload_slot_identifier_never_leaks_through_a_failure(tmp_path: Path) -> None:
    """Break caught: an upload failure could echo the requested slot identifier."""
    client = _client(tmp_path, DocumentUploadRejected("The PDF could not be accepted."))
    try:
        response = _upload(client)
        assert str(SLOT_ID) not in response.text
        assert str(uuid4()) not in response.text
    finally:
        client.close()
