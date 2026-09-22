"""Task 6 contract tests for the shared EHF ISAB shell."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import ReadinessChecks, create_app


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
LOGO = PUBLIC / "assets" / "ehf-logo.svg"
EXPECTED_LOGO_SHA256 = "0972369F8843FFF182D231B7A59E120C66E1ABA4AA41878EB920A1A29326CF4B"
EXPECTED_LOGO_BYTES = 19_346
FOUNDATION_LOGO_ALT = 'alt="Ernst Hadorn Foundation"'


def _primary_navigation_labels(source: str) -> list[str]:
    navigation = re.search(
        r'<nav class="app-nav-list" aria-label="(?:Primary navigation|Application sections)">(.*?)</nav>',
        source,
        flags=re.DOTALL,
    )
    assert navigation is not None
    return re.findall(r'(?:<a|<button)[^>]*>([^<]+)</(?:a|button)>', navigation.group(1))


def preview_client() -> TestClient:
    app = create_app(
        Settings.from_environment({"EHF_ALLOWED_HOST": "localhost"}),
        readiness_checks=ReadinessChecks(lambda _: None, lambda _: None),
    )
    return TestClient(app, base_url="http://localhost")


def test_task_six_public_assets_exist_and_preserve_the_official_logo() -> None:
    """Break caught: a substitute, altered, or absent Foundation logo would break the shared shell."""
    assert LOGO.is_file(), "the approved Ernst Hadorn Foundation logo must ship byte-for-byte"
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
    """Break caught: an applicant surface could omit the real workflow or expose internal workspaces."""
    response = preview_client().get("/__preview/internal/administrator/")

    assert response.status_code == 200
    assert "Preview only" in response.text
    assert "Preview surface" not in response.text
    assert "Sign-in is not active" in response.text
    assert "Submission is not active" in response.text

    applicant = preview_client().get("/applicant/")
    assert applicant.status_code == 200
    assert "Your secure applicant workspace" in applicant.text
    assert "Review your application" in applicant.text
    assert "Application documents" in applicant.text
    assert "Final review and submission" in applicant.text
    assert "scientific-contribution statement" in applicant.text
    assert "Preview surface" not in applicant.text
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
    assert tuple(entry.key for entry in administrator_inventory) == ("overview", "review-pending-papers")
    assert tuple(entry.key for entry in trustee_inventory) == ("overview", "review-pending-papers")
    assert unauthorized_inventory == ()


def test_applicant_pages_keep_one_primary_navigation_inventory() -> None:
    """Break caught: opening the form could replace page navigation with field-section buttons."""
    expected = ["Application information", "Documents", "Final review"]

    for filename in ("review.html", "documents.html", "final-review.html"):
        source = (PUBLIC / "applicant" / filename).read_text(encoding="utf-8")
        assert _primary_navigation_labels(source) == expected

    review = (PUBLIC / "applicant" / "review.html").read_text(encoding="utf-8")
    assert 'aria-label="Application information sections"' in review


def test_internal_authorization_indicator_uses_canonical_group_pills_only() -> None:
    """Break caught: group labels could diverge from the access inventory or leak to applicants."""
    from app.navigation import INTERNAL_GROUPS, internal_authorization_groups

    assert internal_authorization_groups() == (
        INTERNAL_GROUPS.administrators,
        INTERNAL_GROUPS.trustees,
    )
    applicant_source = (PUBLIC / "applicant" / "index.html").read_text(encoding="utf-8")
    assert INTERNAL_GROUPS.administrators == "EHF-Administrators"
    assert INTERNAL_GROUPS.trustees == "EHF-Trustees"
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


def test_navigation_top_carries_the_ernst_hadorn_foundation_logo() -> None:
    """Break caught: the navigation could still present the ISAB mark instead of the Foundation logo."""
    sources = {
        path: path.read_text(encoding="utf-8")
        for path in (
            *(PUBLIC / "applicant").glob("*.html"),
            *(PUBLIC / "internal").glob("*.html"),
            ROOT / "app" / "internal_preview.py",
            ROOT / "app" / "applicant" / "admin_preview.py",
        )
    }
    assert sources, "the shell pages must exist to be checked"
    for path, source in sources.items():
        assert "isab-logo.svg" not in source, path
        assert "ehf-logo.svg" in source, path

    applicant = preview_client().get("/applicant/").text
    assert "assets/ehf-logo.svg" in applicant
    assert FOUNDATION_LOGO_ALT in applicant

    internal = preview_client().get("/__preview/internal/administrator/").text
    assert "/assets/ehf-logo.svg" in internal
    assert FOUNDATION_LOGO_ALT in internal
