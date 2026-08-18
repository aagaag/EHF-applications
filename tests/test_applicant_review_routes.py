from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from app.applicant.confirmations import SectionConfirmationService
from app.applicant.drafts import InMemoryDraftRepository
from app.applicant.review import ApplicantReviewService
from app.applicant.publications import (
    PublicationLookupReceipts,
    PublicationLookupUnavailable,
    PublicationNotFound,
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
from app.preferences import InMemoryPreferenceRepository


class FakePublicationLookup:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.error: Exception | None = None

    def lookup(self, doi: object) -> dict[str, object]:
        self.calls.append(doi)
        if self.error is not None:
            raise self.error
        return {
            "doi": "10.1000/example",
            "title": "A synthetic publication",
            "authors": ["Ada Lovelace"],
            "journal": "Synthetic Journal",
            "publicationDate": "2025-07-04",
            "type": "journal-article",
            "url": "https://doi.org/10.1000/example",
        }


def _client(
    publication_lookup: FakePublicationLookup | None = None,
    review_override: object | None = None,
) -> tuple[TestClient, CapturingVerificationDelivery]:
    application_id = UUID("71000000-0000-4000-8000-000000000001")
    repository = InMemoryApplicantAuthRepository()
    delivery = CapturingVerificationDelivery()
    auth = ApplicantAuthService(
        repository,
        delivery,
        otp_pepper=b"synthetic-otp-pepper-with-at-least-32-bytes",
        session_pepper=b"synthetic-session-pepper-at-least-32-bytes",
        code_factory=lambda: "654321",
    )
    token = new_opaque_token()
    repository.add_invitation(
        application_id,
        invitation_token_hash(token),
        "review@example.test",
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
    review = review_override or ApplicantReviewService(
        InMemoryDraftRepository(),
        SectionConfirmationService(),
        PublicationLookupReceipts(
            b"synthetic-publication-receipt-secret-at-least-32-bytes"
        ),
    )
    app = create_app(
        Settings.from_environment({}),
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        applicant_auth_service=auth,
        applicant_turnstile=turnstile,
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=20, window=timedelta(minutes=10))
        ),
        applicant_review_service=review,
        applicant_publication_lookup=publication_lookup,
        preference_repository=InMemoryPreferenceRepository(),
    )
    client = TestClient(app, base_url="https://localhost")
    client.get(f"/a/{token}")
    client.post("/api/applicant/auth/code", json={"turnstileToken": "review-turnstile"})
    client.post("/api/applicant/auth/verify", json={"code": "654321"})
    return client, delivery


def test_returned_section_exposes_the_admin_reason_and_is_not_current() -> None:
    application_id = UUID("71000000-0000-4000-8000-000000000001")

    class ReturnedReview:
        def metadata(self):
            return ()

        def load(self, _session, section):
            from app.applicant.drafts import DraftSnapshot

            return DraftSnapshot(
                application_id,
                section,
                {"postdoctoralEmploymentStatus": None},
                9,
                return_reason="Please answer the clarified employment question.",
                returned_at_utc=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
            )

        def is_current(self, _session, _section, _snapshot):
            return False

    client, _delivery = _client(review_override=ReturnedReview())
    try:
        response = client.get("/api/applicant/review/employment")
    finally:
        client.close()

    assert response.status_code == 200
    assert response.json()["confirmed"] is False
    assert response.json()["returnedForCorrection"] == {
        "reason": "Please answer the clarified employment question.",
        "returnedAtUtc": "2026-08-18T12:00:00+00:00",
    }


def test_doi_lookup_requires_applicant_session_and_csrf_then_returns_metadata() -> None:
    lookup = FakePublicationLookup()
    client, _delivery = _client(lookup)
    try:
        rejected = client.post(
            "/api/applicant/review/publications/lookup",
            json={"doi": "10.1000/example"},
        )
        assert rejected.status_code == 403
        assert lookup.calls == []

        csrf = client.cookies.get("__Host-ehf_applicant_csrf")
        response = client.post(
            "/api/applicant/review/publications/lookup",
            json={"doi": "10.1000/example"},
            headers={"x-csrf-token": csrf},
        )
        assert response.status_code == 200
        assert response.json()["publication"]["title"] == "A synthetic publication"
        assert response.json()["publication"]["lookupReceipt"]
        assert lookup.calls == ["10.1000/example"]

        client.cookies.clear()
        assert client.post(
            "/api/applicant/review/publications/lookup",
            json={"doi": "10.1000/example"},
        ).status_code == 401
    finally:
        client.close()


def test_publication_save_requires_a_successful_application_bound_lookup() -> None:
    lookup = FakePublicationLookup()
    client, _delivery = _client(lookup)
    try:
        csrf = client.cookies.get("__Host-ehf_applicant_csrf")
        bypass = client.put(
            "/api/applicant/review/publications",
            json={
                "values": {
                    "publications": [
                        {"doi": "10.1000/example", "confirmed": True}
                    ]
                },
                "expectedRowVersion": None,
            },
            headers={"x-csrf-token": csrf},
        )
        assert bypass.status_code == 422
        assert "publications" in bypass.json()["errors"]

        found = client.post(
            "/api/applicant/review/publications/lookup",
            json={"doi": "10.1000/example"},
            headers={"x-csrf-token": csrf},
        )
        publication = found.json()["publication"]
        saved = client.put(
            "/api/applicant/review/publications",
            json={
                "values": {
                    "publications": [
                        {
                            "doi": publication["doi"],
                            "confirmed": True,
                            "lookupReceipt": publication["lookupReceipt"],
                        }
                    ]
                },
                "expectedRowVersion": None,
            },
            headers={"x-csrf-token": csrf},
        )

        assert saved.status_code == 200
        assert saved.json()["values"]["publications"] == [
            {"doi": "10.1000/example", "confirmed": True}
        ]
        assert "lookupReceipt" not in saved.text
    finally:
        client.close()


def test_doi_lookup_returns_stable_not_found_and_unavailable_errors() -> None:
    lookup = FakePublicationLookup()
    client, _delivery = _client(lookup)
    try:
        csrf = client.cookies.get("__Host-ehf_applicant_csrf")
        lookup.error = PublicationNotFound("provider detail")
        missing = client.post(
            "/api/applicant/review/publications/lookup",
            json={"doi": "10.1000/missing"},
            headers={"x-csrf-token": csrf},
        )
        assert missing.status_code == 404
        assert missing.json() == {"message": "No publication was found for this DOI."}
        assert "provider detail" not in missing.text

        lookup.error = PublicationLookupUnavailable("provider detail")
        unavailable = client.post(
            "/api/applicant/review/publications/lookup",
            json={"doi": "10.1000/down"},
            headers={"x-csrf-token": csrf},
        )
        assert unavailable.status_code == 503
        assert unavailable.json() == {
            "message": "Publication lookup is temporarily unavailable."
        }
        assert "provider detail" not in unavailable.text
    finally:
        client.close()


def test_doi_lookup_has_a_dedicated_limit_large_enough_for_the_publication_list() -> None:
    lookup = FakePublicationLookup()
    client, _delivery = _client(lookup)
    try:
        csrf = client.cookies.get("__Host-ehf_applicant_csrf")
        for index in range(21):
            response = client.post(
                "/api/applicant/review/publications/lookup",
                json={"doi": f"10.1000/example-{index}"},
                headers={"x-csrf-token": csrf},
            )
            assert response.status_code == 200
        assert len(lookup.calls) == 21
    finally:
        client.close()


def test_review_routes_require_csrf_then_save_and_explicitly_confirm() -> None:
    """Break caught: cross-site writes or navigation could save/confirm applicant data."""
    client, _delivery = _client()
    try:
        rejected = client.put(
            "/api/applicant/review/contribution",
            json={"values": {"contributionStatement": "A synthetic contribution."}, "expectedRowVersion": None},
        )
        assert rejected.status_code == 403

        csrf = client.cookies.get("__Host-ehf_applicant_csrf")
        saved = client.put(
            "/api/applicant/review/contribution",
            json={"values": {"contributionStatement": "A synthetic contribution."}, "expectedRowVersion": None},
            headers={"x-csrf-token": csrf},
        )
        assert saved.status_code == 200
        assert saved.json() == {
            "saved": True,
            "rowVersion": 1,
            "values": {"contributionStatement": "A synthetic contribution."},
            "confirmed": False,
        }

        confirmed = client.post(
            "/api/applicant/review/contribution/confirm",
            json={"rowVersion": 1},
            headers={"x-csrf-token": csrf},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["confirmed"] is True
        assert len(confirmed.json()["canonicalSha256"]) == 64
    finally:
        client.close()


def test_review_route_returns_current_version_on_stale_autosave() -> None:
    """Break caught: stale writes could overwrite data or return no reconciliation state."""
    client, _delivery = _client()
    try:
        csrf = client.cookies.get("__Host-ehf_applicant_csrf")
        client.put(
            "/api/applicant/review/contribution",
            json={"values": {"contributionStatement": "Current contribution."}, "expectedRowVersion": None},
            headers={"x-csrf-token": csrf},
        )
        stale = client.put(
            "/api/applicant/review/contribution",
            json={"values": {"contributionStatement": "Stale contribution."}, "expectedRowVersion": 0},
            headers={"x-csrf-token": csrf},
        )

        assert stale.status_code == 409
        assert stale.json()["current"]["values"] == {
            "contributionStatement": "Current contribution."
        }
        assert stale.json()["current"]["rowVersion"] == 1
    finally:
        client.close()


def test_applicant_appearance_preferences_are_session_scoped_and_csrf_protected() -> None:
    """Break caught: applicant appearance could be unsaved or writable cross-site."""
    client, _delivery = _client()
    try:
        current = client.get("/api/preferences")
        assert current.status_code == 200
        assert current.json()["skin"] == "default"

        payload = {"skin": "blue", "invert": False, "compact": True, "reduceMotion": True}
        assert client.post("/api/preferences", json=payload).status_code == 403
        saved = client.post(
            "/api/preferences",
            json=payload,
            headers={"x-csrf-token": client.cookies.get("__Host-ehf_applicant_csrf")},
        )
        assert saved.status_code == 200
        assert saved.json() == payload
        assert client.get("/api/preferences").json() == payload
    finally:
        client.close()
