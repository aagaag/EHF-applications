from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from app.auth.applicant import ApplicantSessionContext, NewApplicantSession
from app.auth.rate_limit import InMemoryRateLimiter, RateLimitPolicy
from app.auth.turnstile import TurnstileVerifier
from app.config import Settings
from app.identity import AuthenticatedIdentity
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity, InMemoryPreferenceRepository


APPLICATION_ID = UUID("91000000-0000-4000-8000-000000000001")
ENTRA_ID = UUID("92000000-0000-4000-8000-000000000001")
SESSION_TOKEN = "s" * 43
CSRF_TOKEN = "c" * 43


class StubAuth:
    def __init__(self) -> None:
        self.sessions: dict[str, ApplicantSessionContext] = {}

    def authenticate(self, token: str) -> ApplicantSessionContext | None:
        return self.sessions.get(token)

    def valid_csrf(self, _session: ApplicantSessionContext, token: str) -> bool:
        return token == CSRF_TOKEN

    def establish_entra(self, entra_object_id: UUID) -> NewApplicantSession | None:
        if entra_object_id != ENTRA_ID:
            return None
        now = datetime.now(UTC)
        token = "e" * 43
        self.sessions[token] = ApplicantSessionContext(
            APPLICATION_ID,
            b"e" * 32,
            now + timedelta(minutes=30),
            now + timedelta(hours=24),
            entra_object_id=ENTRA_ID,
        )
        return NewApplicantSession(
            APPLICATION_ID,
            token,
            CSRF_TOKEN,
            now + timedelta(minutes=30),
            now + timedelta(hours=24),
        )


class StubSyntheticWorkspace:
    def __init__(self, auth: StubAuth) -> None:
        self.auth = auth
        self.calls: list[tuple[str, str]] = []

    def create(self, actor: str, actor_group: str) -> NewApplicantSession:
        self.calls.append((actor, actor_group))
        now = datetime.now(UTC)
        self.auth.sessions[SESSION_TOKEN] = ApplicantSessionContext(
            APPLICATION_ID,
            b"c" * 32,
            now + timedelta(minutes=30),
            now + timedelta(hours=24),
            synthetic_actor_identity=actor,
        )
        return NewApplicantSession(
            APPLICATION_ID,
            SESSION_TOKEN,
            CSRF_TOKEN,
            now + timedelta(minutes=30),
            now + timedelta(hours=24),
        )


class UnreachableDocuments:
    def slots(self, _session: ApplicantSessionContext) -> tuple[()]:
        raise AssertionError("synthetic document metadata must be denied before the service")


class UnreachableFinalization:
    def preview(self, _session: ApplicantSessionContext) -> dict[str, object]:
        return {"ready": False, "unresolved": [], "manifest": {}}

    def submit(self, _session: ApplicantSessionContext) -> None:
        raise AssertionError("synthetic final submission must be denied before the service")


def _principal(key: str, group: str, *, entra: UUID | None = None) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        Identity(key, f"{key.split(':')[-1]}@example.test", key),
        frozenset({group}) if group else frozenset(),
        entra_object_id=entra,
    )


def _client(
    current: dict[str, AuthenticatedIdentity | None],
    *,
    portal_enabled: bool = True,
) -> tuple[TestClient, StubAuth, StubSyntheticWorkspace]:
    auth = StubAuth()
    synthetic = StubSyntheticWorkspace(auth)
    settings = replace(
        Settings.from_environment({}), applicant_portal_enabled=portal_enabled
    )
    application = create_app(
        settings,
        readiness_checks=ReadinessChecks(lambda _timeout: None, lambda _timeout: None),
        identity_resolver=lambda _request: current["principal"],
        preference_repository=InMemoryPreferenceRepository(),
        applicant_auth_service=auth,  # type: ignore[arg-type]
        synthetic_applicant_service=synthetic,
        applicant_turnstile=TurnstileVerifier(
            "synthetic-secret",
            "localhost",
            lambda *_args: {"success": True, "hostname": "localhost", "action": "test"},
        ),
        applicant_rate_limiter=InMemoryRateLimiter(
            RateLimitPolicy(limit=20, window=timedelta(minutes=10))
        ),
        applicant_document_service=UnreachableDocuments(),  # type: ignore[arg-type]
        applicant_finalization_service=UnreachableFinalization(),  # type: ignore[arg-type]
    )
    return TestClient(application, base_url="https://localhost"), auth, synthetic


def test_administrator_creates_server_scoped_workspace_with_only_session_cookies() -> None:
    current = {"principal": _principal("cloudflare:creator", INTERNAL_GROUPS.administrators)}
    client, _auth, synthetic = _client(current)
    try:
        response = client.post(
            "/api/internal/synthetic-applicants",
            headers={"origin": "https://localhost"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/applicant/review"
        assert synthetic.calls == [
            ("cloudflare:creator", INTERNAL_GROUPS.administrators)
        ]
        assert "applicationId" not in response.text
        assert "actor" not in response.text
        cookies = response.headers.get_list("set-cookie")
        assert any("__Host-ehf_applicant_session=" in value for value in cookies)
        assert any("__Host-ehf_applicant_csrf=" in value for value in cookies)

        session = client.get("/api/applicant/session")
        assert session.status_code == 200
        assert session.json() == {"authenticated": True, "syntheticAdmin": True}
    finally:
        client.close()


def test_creation_denies_cross_origin_payloads_and_non_administrators_neutrally() -> None:
    current = {"principal": _principal("cloudflare:creator", INTERNAL_GROUPS.administrators)}
    client, _auth, synthetic = _client(current)
    try:
        cross_origin = client.post(
            "/api/internal/synthetic-applicants",
            headers={"origin": "https://attacker.example"},
        )
        selected_record = client.post(
            "/api/internal/synthetic-applicants",
            headers={"origin": "https://localhost"},
            json={"applicationId": str(APPLICATION_ID)},
        )
        for principal in (
            _principal("cloudflare:trustee", INTERNAL_GROUPS.trustees),
            _principal("cloudflare:other", ""),
            None,
        ):
            current["principal"] = principal
            response = client.post(
                "/api/internal/synthetic-applicants",
                headers={"origin": "https://localhost"},
            )
            assert response.status_code == 404

        assert cross_origin.status_code == 404
        assert selected_record.status_code == 404
        assert synthetic.calls == []
    finally:
        client.close()


def test_synthetic_session_requires_the_exact_live_creator_on_pages_and_apis() -> None:
    current = {"principal": _principal("cloudflare:creator", INTERNAL_GROUPS.administrators)}
    client, _auth, _synthetic = _client(current)
    try:
        assert client.post(
            "/api/internal/synthetic-applicants",
            headers={"origin": "https://localhost"},
            follow_redirects=False,
        ).status_code == 303
        assert client.get("/applicant/review").status_code == 200

        current["principal"] = _principal(
            "cloudflare:second-admin", INTERNAL_GROUPS.administrators
        )
        assert client.get("/applicant/review").status_code == 404
        assert client.get("/api/applicant/session").status_code == 404

        current["principal"] = _principal("cloudflare:creator", INTERNAL_GROUPS.trustees)
        assert client.get("/applicant/final-review").status_code == 404
    finally:
        client.close()


def test_injected_synthetic_flow_cannot_bypass_live_identity_revalidation() -> None:
    """Break caught: a test injection could register creation without the live API guard."""
    current = {"principal": _principal("cloudflare:creator", INTERNAL_GROUPS.administrators)}
    client, _auth, _synthetic = _client(current, portal_enabled=False)
    try:
        assert client.post(
            "/api/internal/synthetic-applicants",
            headers={"origin": "https://localhost"},
            follow_redirects=False,
        ).status_code == 303
        current["principal"] = _principal(
            "cloudflare:second-admin", INTERNAL_GROUPS.administrators
        )
        assert client.get("/api/applicant/session").status_code == 404
    finally:
        client.close()


def test_synthetic_documents_and_final_submission_are_denied_server_side() -> None:
    current = {"principal": _principal("cloudflare:creator", INTERNAL_GROUPS.administrators)}
    client, _auth, _synthetic = _client(current)
    try:
        client.post(
            "/api/internal/synthetic-applicants",
            headers={"origin": "https://localhost"},
            follow_redirects=False,
        )
        assert client.get("/api/applicant/documents").status_code == 404
        assert client.get(
            f"/api/applicant/documents/{APPLICATION_ID}/metadata"
        ).status_code == 404
        assert client.post(
            "/api/applicant/finalization",
            headers={"x-csrf-token": CSRF_TOKEN},
        ).status_code == 404
        assert client.get("/api/applicant/finalization").status_code == 200
    finally:
        client.close()


def test_existing_entra_applicant_binding_and_session_probe_remain_exact() -> None:
    current = {
        "principal": _principal(
            "cloudflare:applicant", INTERNAL_GROUPS.applicants, entra=ENTRA_ID
        )
    }
    client, _auth, _synthetic = _client(current)
    try:
        assert client.get("/applicant/sign-in", follow_redirects=False).status_code == 303
        session = client.get("/api/applicant/session")
        assert session.status_code == 200
        assert session.json() == {"authenticated": True, "syntheticAdmin": False}

        current["principal"] = _principal(
            "cloudflare:other-applicant",
            INTERNAL_GROUPS.applicants,
            entra=UUID("92000000-0000-4000-8000-000000000002"),
        )
        assert client.get("/api/applicant/session").status_code == 404
    finally:
        client.close()
