"""Task 6 contract tests for the shared EHF ISAB shell."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import ReadinessChecks, create_app


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
LOGO = PUBLIC / "assets" / "isab-logo.svg"
EXPECTED_LOGO_SHA256 = "D70B7722957A3ACCD8D4E16BB6BFCD8E48A153DE82C3C496CC34EE183645CC0E"
EXPECTED_LOGO_BYTES = 19_932


def preview_client() -> TestClient:
    app = create_app(
        Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
        readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
    )
    return TestClient(app, base_url="http://localhost")


def test_task_six_public_assets_exist_and_preserve_the_official_logo() -> None:
    """Break caught: a substitute, altered, or absent ISAB logo would break the shared shell."""
    assert LOGO.is_file(), "Task 6 must copy the approved ISAB logo byte-for-byte"
    assert LOGO.stat().st_size == EXPECTED_LOGO_BYTES
    assert hashlib.sha256(LOGO.read_bytes()).hexdigest().upper() == EXPECTED_LOGO_SHA256
    for relative_path in (
        "assets/site.css",
        "assets/shell.js",
        "assets/theme.js",
        "applicant/index.html",
    ):
        assert (PUBLIC / relative_path).is_file(), relative_path


def test_preview_routes_are_honest_and_keep_internal_and_applicant_markup_separate() -> None:
    """Break caught: a preview could imply active sign-in/submission or expose internal workspaces."""
    response = preview_client().get("/__preview/internal/administrator/")

    assert response.status_code == 200
    assert "Preview only" in response.text
    assert "Sign-in is not active" in response.text
    assert "Submission is not active" in response.text

    applicant = preview_client().get("/applicant/")
    assert applicant.status_code == 200
    assert "Preview only" in applicant.text
    assert "internal" not in applicant.text.lower()
    assert "recommend" not in applicant.text.lower()
    assert "referee" not in applicant.text.lower()

    for file_path in (PUBLIC / "applicant").rglob("*"):
        if file_path.is_file():
            source = file_path.read_text(encoding="utf-8").lower()
            assert "recommend" not in source
            assert "referee" not in source


def test_authorized_navigation_and_help_share_one_filtered_inventory() -> None:
    """Break caught: a visible page could lack help, or an unauthorized page could leak into navigation."""
    from app.navigation import INTERNAL_GROUPS, filtered_inventory, help_entries, navigation_entries

    administrator_inventory = filtered_inventory({INTERNAL_GROUPS.administrators})
    trustee_inventory = filtered_inventory({INTERNAL_GROUPS.trustees})
    unauthorized_inventory = filtered_inventory(set())

    assert navigation_entries(administrator_inventory) == help_entries(administrator_inventory)
    assert navigation_entries(trustee_inventory) == help_entries(trustee_inventory)
    assert all(entry.key != "operations" for entry in trustee_inventory)
    assert unauthorized_inventory == ()


def test_internal_authorization_indicator_uses_canonical_group_pills_only() -> None:
    """Break caught: group labels could diverge from the access inventory or leak to applicants."""
    from app.navigation import INTERNAL_GROUPS, internal_authorization_groups

    assert internal_authorization_groups() == (
        INTERNAL_GROUPS.administrators,
        INTERNAL_GROUPS.trustees,
    )
    applicant_source = (PUBLIC / "applicant" / "index.html").read_text(encoding="utf-8")
    assert INTERNAL_GROUPS.administrators == "EHF-Applications-Administrators"
    assert INTERNAL_GROUPS.trustees == "EHF-Applications-Trustees"
    assert "Authorizations:" not in applicant_source


def test_shell_uses_no_browser_persistence_and_has_required_accessible_structure() -> None:
    """Break caught: a browser cache could become authoritative or the drawer could lose keyboard semantics."""
    assets = "\n".join(path.read_text(encoding="utf-8") for path in (PUBLIC / "assets").glob("*.js"))
    stylesheet = (PUBLIC / "assets" / "site.css").read_text(encoding="utf-8")
    internal = preview_client().get("/__preview/internal/administrator/").text

    assert "localStorage" not in assets
    assert "sessionStorage" not in assets
    assert 'aria-controls="application-navigation"' in internal
    assert "data-skin=\"high-contrast\"" in stylesheet
    assert "data-skin=\"soft-earth\"" in stylesheet
    assert "data-skin=\"blue\"" in stylesheet
    assert "@media (max-width: 720px)" in stylesheet
    assert "width: 94%" in stylesheet
    assert "margin-inline: 3%" in stylesheet
