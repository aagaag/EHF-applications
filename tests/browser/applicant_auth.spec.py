from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_verification_page_is_identity_neutral_accessible_and_phone_responsive() -> None:
    """Break caught: pre-auth UI could expose identity or overflow on a phone."""
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright

    html = (ROOT / "public" / "applicant" / "verify.html").read_text(encoding="utf-8")
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - installation-specific
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.set_content(html, wait_until="domcontentloaded")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "applicant-auth.js"))

            assert page.get_by_role("heading", name="Verify your invitation").is_visible()
            assert page.get_by_label("One-time verification code").is_visible()
            assert page.get_by_role("button", name="Continue securely").is_visible()
            request_code = page.get_by_role("button", name="Request verification code")
            assert request_code.is_disabled()
            page.evaluate("window.ehfApplicantTurnstileVerified('synthetic-browser-token')")
            assert request_code.is_enabled()
            assert "@" not in page.locator("main").inner_text()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert Axe().run(page).violations_count == 0
        finally:
            browser.close()
