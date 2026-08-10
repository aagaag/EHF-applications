"""Focused regression tests for the independent Task 6 review findings."""

from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import ReadinessChecks, create_app
from app.preferences import AppearancePreference, Identity


class MemoryPreferenceRepository:
    def __init__(self) -> None:
        self.values: dict[str, AppearancePreference] = {}

    def load(self, identity: Identity) -> AppearancePreference:
        return self.values.get(identity.key, AppearancePreference())

    def save(self, identity: Identity, preference: AppearancePreference) -> AppearancePreference:
        self.values[identity.key] = preference
        return preference


def _settings() -> Settings:
    return Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"})


def _client(identity: object | None = None, repository: object | None = None) -> TestClient:
    return TestClient(
        create_app(
            _settings(),
            readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
            identity_resolver=(lambda _request: identity) if identity is not None else None,
            preference_repository=repository,
        ),
        base_url="http://localhost",
    )


def _identity(*groups: str) -> object:
    from app.identity import AuthenticatedIdentity

    return AuthenticatedIdentity(
        Identity("entra:person-001", "person@example.org", "Preview Person"), frozenset(groups)
    )


def test_internal_rendering_uses_one_filtered_inventory_for_navigation_help_cards_and_pills() -> None:
    from app.navigation import INTERNAL_GROUPS

    administrator = _client(_identity(INTERNAL_GROUPS.administrators)).get("/internal/")
    assert administrator.status_code == 200
    for text in ("Overview", "Applications", "Reports", "Operations", "Operations help"):
        assert text in administrator.text
    assert INTERNAL_GROUPS.administrators in administrator.text
    assert INTERNAL_GROUPS.trustees in administrator.text

    trustee = _client(_identity(INTERNAL_GROUPS.trustees)).get("/internal/")
    assert trustee.status_code == 200
    assert "Operations" not in trustee.text
    assert "Operations help" not in trustee.text
    assert "Applications" in trustee.text


def test_default_and_production_internal_routes_fail_closed_while_development_simulation_is_explicit() -> None:
    assert _client().get("/internal/").status_code == 404
    assert _client().get("/__preview/internal/administrator/").status_code == 200

    production = replace(_settings(), environment="production", allowed_host="ehf.isab.science")
    client = TestClient(create_app(production), base_url="http://ehf.isab.science")
    assert client.get("/internal/").status_code == 404
    assert client.get("/__preview/internal/administrator/").status_code == 404


def test_authenticated_applicant_preferences_round_trip_through_the_same_origin_server_repository() -> None:
    repository = MemoryPreferenceRepository()
    client = _client(_identity(), repository)

    assert client.get("/api/preferences").json() == {
        "skin": "default", "invert": False, "compact": False, "reduceMotion": False
    }
    saved = client.post(
        "/api/preferences",
        json={"skin": "blue", "invert": True, "compact": True, "reduceMotion": False},
    )
    assert saved.status_code == 200
    assert client.get("/api/preferences").json() == saved.json()
    assert repository.values["entra:person-001"].skin == "blue"
    assert _client().get("/api/preferences").status_code == 401


def test_preferences_csp_and_shared_applicant_assets_do_not_expose_internal_vocabulary() -> None:
    response = _client().get("/applicant/")
    assert "connect-src 'self'" in response.headers["content-security-policy"]

    from pathlib import Path

    assets = Path(__file__).resolve().parents[1] / "public" / "assets"
    shared_source = "\n".join(path.read_text(encoding="utf-8").lower() for path in assets.iterdir())
    for forbidden in ("administrator", "trustee", "recommend", "referee"):
        assert forbidden not in shared_source


def test_preference_read_is_a_narrow_procedure_and_sixth_ordered_migration() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    migration = (root / "database" / "migrations" / "006_user_preference_read.sql").read_text(
        encoding="utf-8"
    )
    validator = (
        root / "database" / "tests" / "006_validate_user_preference_read.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE PROCEDURE dbo.GetUserPreference" in migration
    assert "WHERE IdentityKey = @IdentityKey" in migration
    assert "GRANT EXECUTE ON dbo.GetUserPreference TO EHFApplicationRuntime;" in migration
    assert "SELECT *" not in migration
    assert "ExecIsExecuteAsUser" in validator
