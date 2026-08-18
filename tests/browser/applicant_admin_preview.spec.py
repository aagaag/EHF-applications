from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from app.applicant.admin_preview import render_applicant_preview
from app.applicant.approval import ApplicantPreviewBundle


ROOT = Path(__file__).resolve().parents[2]


def test_applicant_admin_preview_is_read_only_accessible_and_responsive() -> None:
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import expect, sync_playwright

    html = render_applicant_preview(
        ApplicantPreviewBundle(
            UUID("a7000000-0000-4000-8000-000000000001"),
            "Synthetic Preview Applicant",
            "IMPORTED",
            {
                "applicant": {
                    "fullName": "Synthetic Preview Applicant",
                    "registeredEmail": "preview@example.test",
                    "postdoctoralEmploymentStatus": True,
                    "degrees": [
                        {"degreeType": "PhD", "conferralDate": "2020-06-30"}
                    ],
                    "publications": [
                        {"doi": "10.1000/example", "confirmed": True}
                    ],
                }
            },
            {},
        )
    )

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
            page.add_script_tag(
                path=str(ROOT / "public" / "assets" / "applicant-preview.js")
            )

            expect(page.get_by_text("Read-only administrator preview")).to_be_visible()
            expect(page.get_by_role("button", name="Identity and contact")).to_have_attribute(
                "aria-current", "page"
            )
            expect(page.get_by_role("link", name="Appearance")).to_be_visible()
            for label in (
                "Production default",
                "High contrast",
                "Soft green/brown",
                "Blue",
            ):
                expect(page.get_by_role("button", name=label)).to_be_visible()
            expect(page.get_by_label("Registered email address")).to_have_value(
                "preview@example.test"
            )
            assert page.locator("input:not([readonly]), textarea:not([readonly])").count() == 0
            assert page.get_by_role("button", name="Save changes").count() == 0

            page.get_by_role("button", name="Qualifications and academic age").click()
            expect(
                page.get_by_role("button", name="Qualifications and academic age")
            ).to_have_attribute("aria-current", "page")
            expect(page.get_by_label("Degree")).to_have_value("PhD")
            expect(page.get_by_label("Date of conferral")).to_have_value("2020-06-30")

            for width, height in ((1440, 900), (721, 900), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )

            results = Axe().run(page)
            assert results.response["violations"] == []
        finally:
            browser.close()
