from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_documents_page_explains_controlled_pdf_slots_without_confidential_status() -> None:
    """Break caught: document UI could imply unrestricted replacement or disclose recommendations."""
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright

    html = (ROOT / "public" / "applicant" / "documents.html").read_text(encoding="utf-8")
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.set_content(html, wait_until="domcontentloaded")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "applicant-documents.js"))

            assert page.get_by_role("heading", name="Your application documents").is_visible()
            assert page.get_by_text("PDF files only", exact=False).is_visible()
            assert "recommendation" not in page.locator("main").inner_text().casefold()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert Axe().run(page).violations_count == 0
        finally:
            browser.close()


def test_available_document_has_a_session_scoped_download_control() -> None:
    """Break caught: applicants could be unable to download their visible documents."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    html = (ROOT / "public" / "applicant" / "documents.html").read_text(encoding="utf-8")
    html = html.replace("<head>", '<head><base href="https://localhost/applicant/">', 1)
    slot_id = "82000000-0000-4000-8000-000000000010"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.route(
                "**/api/applicant/documents",
                lambda route: route.fulfill(json={"slots": [{
                    "slotId": slot_id, "code": "CV", "label": "Curriculum vitae",
                    "required": True, "uploadMode": "CLOSED", "rowVersion": 3,
                    "status": "Available", "downloadAvailable": True,
                }]}),
            )
            page.set_content(html, wait_until="domcontentloaded")
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "applicant-documents.js"))

            download = page.get_by_role("link", name="Download Curriculum vitae")
            assert download.get_attribute("href") == f"/api/applicant/documents/{slot_id}/download"
        finally:
            browser.close()
