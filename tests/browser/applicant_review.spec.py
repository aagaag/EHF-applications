from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_review_page_has_explicit_sections_confirmation_and_responsive_layout() -> None:
    """Break caught: review UI could hide fields, imply confirmation, or overflow."""
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright

    html = (ROOT / "public" / "applicant" / "review.html").read_text(encoding="utf-8")
    html = html.replace("<head>", '<head><base href="https://localhost/applicant/">', 1)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - installation-specific
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            for width, height in ((1440, 900), (720, 900), (390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height})
                page.set_content(html, wait_until="domcontentloaded")
                page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
                page.add_script_tag(path=str(ROOT / "public" / "assets" / "applicant-review.js"))

                assert page.get_by_role("heading", name="Review your application").is_visible()
                assert page.get_by_role("button", name="Confirm this information").count() >= 1
                assert page.get_by_role("button", name="Correct information").count() >= 1
                assert page.get_by_role("button", name="Blue").is_visible()
                contribution_nav = page.get_by_role("button", name="Scientific contribution")
                contribution_nav.focus()
                page.keyboard.press("Enter")
                statement = page.get_by_label(
                    "What do you consider your most important contribution to scientific advance to date?"
                )
                assert statement.get_attribute("maxlength") == "1000"
                statement.fill("A short contribution")
                assert page.get_by_text("980 characters remaining", exact=True).is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                assert Axe().run(page).violations_count == 0
                page.close()
        finally:
            browser.close()


def test_review_page_prefills_imported_application_values() -> None:
    """Break caught: applicants could see blank fields instead of their imported record."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    html = (ROOT / "public" / "applicant" / "review.html").read_text(encoding="utf-8")
    html = html.replace("<head>", '<head><base href="https://localhost/applicant/">', 1)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page()
            page.route(
                "**/api/applicant/review/*",
                lambda route: route.fulfill(json={"rowVersion": None, "values": {}, "confirmed": False}),
            )
            page.route(
                "**/api/applicant/application",
                lambda route: route.fulfill(json={"applicant": {"fullName": "Imported Applicant"}, "sections": {}, "documents": []}),
            )
            page.route(
                "**/api/applicant/review/fields",
                lambda route: route.fulfill(
                    json={"fields": [{"section": "identity", "code": "fullName", "label": "Full name", "kind": "text", "required": True}]}
                ),
            )
            page.set_content(html, wait_until="domcontentloaded")
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "applicant-review.js"))

            assert page.get_by_label("Full name").input_value() == "Imported Applicant"
        finally:
            browser.close()


def test_review_page_autosaves_changed_fields() -> None:
    """Break caught: changed applicant data could remain only in the browser until a button click."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import expect, sync_playwright

    html = (ROOT / "public" / "applicant" / "review.html").read_text(encoding="utf-8")
    html = html.replace("<head>", '<head><base href="https://localhost/applicant/">', 1)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page()
            console_messages: list[str] = []
            page.on("console", lambda message: console_messages.append(message.text))

            page.route(
                "**/api/applicant/review/*",
                lambda route: route.fulfill(
                    json={"rowVersion": 1, "values": {"fullName": "Imported Applicant"}, "confirmed": False}
                ),
            )
            page.route("**/api/applicant/application", lambda route: route.fulfill(json={"applicant": {"fullName": "Imported Applicant"}, "sections": {}, "documents": []}))
            page.route("**/api/applicant/review/fields", lambda route: route.fulfill(json={"fields": [
                {"section": "identity", "code": "fullName", "label": "Full name", "kind": "text", "required": True},
                {"section": "identity", "code": "telephone", "label": "Telephone number", "kind": "text", "required": True},
            ]}))
            page.set_content(html, wait_until="domcontentloaded")
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "applicant-review.js"))

            full_name = page.get_by_label("Full name")
            expect(full_name).to_have_value("Imported Applicant")
            full_name.fill("Changed Applicant")
            page.wait_for_timeout(1_200)
            assert page.locator('[data-section-status="identity"]').inner_text() == "Saved", console_messages
        finally:
            browser.close()
