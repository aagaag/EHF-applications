from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from app.applicant.admin_documents import render_applicant_documents
from app.applicant.approval import ApplicantPreviewDocument, ApplicantPreviewDocuments


ROOT = Path(__file__).resolve().parents[2]
APPLICATION_ID = UUID("a7000000-0000-4000-8000-000000000001")


def _page_html() -> str:
    page = render_applicant_documents(
        ApplicantPreviewDocuments(
            APPLICATION_ID,
            "Synthetic Preview Applicant",
            "IMPORTED",
            (
                ApplicantPreviewDocument(
                    UUID("a1000000-0000-4000-8000-000000000001"),
                    "import-3c5d91b88145",
                    "Research plan",
                    "RESEARCH_PLAN",
                    "UNREVIEWED",
                    19,
                    1_115_189,
                    "application/pdf",
                ),
                ApplicantPreviewDocument(
                    UUID("a1000000-0000-4000-8000-000000000002"),
                    "import-088f2b7e4d1a",
                    "Recommendation letter",
                    "RECOMMENDATION_LETTER",
                    "UNREVIEWED",
                    2,
                    101_273,
                    "application/pdf",
                ),
                ApplicantPreviewDocument(
                    UUID("a1000000-0000-4000-8000-000000000003"),
                    "import-fd9ecee62df6",
                    "Curriculum vitae",
                    "CV",
                    "UNREVIEWED",
                    None,
                    None,
                    "application/pdf",
                ),
            ),
        )
    )
    for hosted_asset in (
        '<link rel="stylesheet" href="/assets/site.css">',
        '<script src="/assets/theme.js"></script>',
        '<script src="/assets/shell.js"></script>',
    ):
        page = page.replace(hosted_asset, "")
    return page


def test_proposal_document_page_is_accessible_and_responsive() -> None:
    """Break caught: a dossier PDF control could be unreachable, nested, or overflow the page."""
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import expect, sync_playwright

    html = _page_html()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="domcontentloaded")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "shell.js"))

            documents = page.locator("[data-preview-document]")
            expect(documents).to_have_count(3)
            expect(page.get_by_role("link", name="Research plan (PDF)", exact=False)).to_be_visible()
            expect(
                page.get_by_role("link", name="Recommendation letter (PDF)", exact=False)
            ).to_be_visible()
            expect(page.get_by_role("link", name="Curriculum vitae (PDF)", exact=False)).to_be_visible()
            for index in range(3):
                control = documents.nth(index)
                expect(control).to_have_attribute("target", "_blank")
                expect(control).to_have_attribute("rel", "noopener noreferrer")
                assert control.locator("a, button").count() == 0
            expect(page.get_by_text("19 pages · 1.1 MB · classification UNREVIEWED")).to_be_visible()
            confidential_marker = page.locator("em.preview-document-confidential")
            expect(confidential_marker).to_have_count(1)
            expect(confidential_marker).to_be_visible()
            expect(page.get_by_text("This application has 3 active proposal documents.")).to_be_visible()
            expect(page.get_by_role("link", name="Back to applicant review")).to_be_visible()

            for width, height in ((1440, 900), (1051, 900), (721, 900), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
                container = page.locator(".preview-documents").bounding_box()
                assert container is not None
                for bounds in documents.evaluate_all(
                    "nodes => nodes.map(node => { const box = node.getBoundingClientRect(); "
                    "return { left: box.left, right: box.right }; })"
                ):
                    assert bounds["left"] >= container["x"] - 1
                    assert bounds["right"] <= container["x"] + container["width"] + 1

            results = Axe().run(page)
            assert results.response["violations"] == []
        finally:
            browser.close()


def test_document_page_names_every_active_pdf_with_a_stable_attachment_name() -> None:
    """Break caught: a proposal PDF could be served without a stable, safe attachment name."""
    html = _page_html()

    assert html.count("data-preview-document") == 3
    assert "https://openalex.org" not in html
