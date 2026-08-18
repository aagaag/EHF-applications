from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_final_review_page_lists_completeness_and_has_one_consequential_submit_action() -> None:
    """Break caught: final submission could be ambiguous, inaccessible, or leak hidden data."""
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright

    html = (ROOT / "public" / "applicant" / "final-review.html").read_text(encoding="utf-8")
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.set_content(html, wait_until="domcontentloaded")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "applicant-finalize.js"))

            assert page.get_by_role("heading", name="Final review and submission").is_visible()
            assert page.get_by_role("button", name="Submit completed application").count() == 1
            main = page.locator("main").inner_text().casefold()
            assert "recommendation" not in main
            assert "internal" not in main
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert Axe().run(page).violations_count == 0
        finally:
            browser.close()


def test_final_review_renders_allowlisted_values_statement_and_visible_documents() -> None:
    """Break caught: applicants could submit without seeing the actual values and documents bound to confirmation."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import expect, sync_playwright

    html = (ROOT / "public" / "applicant" / "final-review.html").read_text(encoding="utf-8")
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
            page.route("**/api/applicant/review/*", lambda route: route.fulfill(json={"rowVersion": 1, "values": {}, "confirmed": True}))
            page.route("**/api/applicant/review/fields", lambda route: route.fulfill(json={"fields": [
                {"section": "identity", "code": "fullName", "label": "Full name", "kind": "text"},
                {"section": "qualifications", "code": "degrees", "label": "Degrees", "kind": "degree_list"},
                {"section": "publications", "code": "publications", "label": "Publications by DOI", "kind": "publication_list"},
                {"section": "contribution", "code": "contributionStatement", "label": "Scientific contribution", "kind": "textarea"},
            ]}))
            page.route("**/api/applicant/application", lambda route: route.fulfill(json={
                "applicant": {
                    "fullName": "Reviewed Applicant",
                    "degrees": [
                        {"degreeType": "BSc", "conferralDate": "2014-06-30"},
                        {"degreeType": "PhD", "conferralDate": "2020-01-15"},
                    ],
                    "publications": [
                        {"doi": "10.1000/one", "confirmed": True},
                        {"doi": "10.1000/two", "confirmed": True},
                    ],
                    "contributionStatement": "My reviewed contribution.",
                },
                "sections": {},
                "documents": [{"slotCode": "CV", "displayName": "curriculum-vitae.pdf"}],
            }))
            page.route("**/api/applicant/finalization", lambda route: route.fulfill(json={"ready": True, "unresolved": [], "manifest": {}}))
            page.set_content(html, wait_until="domcontentloaded")
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "applicant-finalize.js"))

            page.wait_for_timeout(500)
            assert page.get_by_text("Reviewed Applicant", exact=True).is_visible(), console_messages
            expect(page.get_by_text("My reviewed contribution.", exact=True)).to_be_visible()
            expect(page.get_by_text("BSc — 2014-06-30; PhD — 2020-01-15", exact=True)).to_be_visible()
            expect(page.get_by_text("10.1000/one; 10.1000/two", exact=True)).to_be_visible()
            assert "[object Object]" not in page.locator("main").inner_text()
            expect(page.get_by_text("curriculum-vitae.pdf", exact=True)).to_be_visible()
        finally:
            browser.close()
