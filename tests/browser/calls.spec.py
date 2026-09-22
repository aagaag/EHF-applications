from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("viewport", [(1440, 900), (390, 844)])
def test_call_inventory_is_responsive_accessible_and_keeps_rounds_in_navigation(
    viewport: tuple[int, int],
) -> None:
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright

    from app.calls import CallContext, CallSummary
    from app.identity import AuthenticatedIdentity
    from app.internal_calls import render_call_inventory
    from app.navigation import INTERNAL_GROUPS
    from app.preferences import CallNavigationPreference, Identity

    def call(year: int) -> CallContext:
        return CallContext(
            fellowship_call_id=UUID(int=year),
            call_code=f"EHF-{year}",
            public_slug=f"ehf-{year}",
            display_name=f"Ernst Hadorn Fellowships with a long title for {year}",
            compact_title=f"EHF {year}",
            call_status="OPEN" if year == 2026 else "DRAFT",
            applicant_review_status="OPEN" if year == 2026 else "DISABLED",
            internal_selection_status="OPEN" if year == 2026 else "DISABLED",
            invitations_enabled=False,
            analysis_profile_code="ehf-standard-v1",
            application_deadline_utc=datetime(year, 12, 31, tzinfo=UTC),
            applicant_review_deadline_utc=None,
            row_version=b"12345678",
        )

    summaries = tuple(
        CallSummary(context, 38 if context.call_code == "EHF-2026" else 0, None, None, 3, "ACTIVE")
        for context in (call(2026), call(2027))
    )
    principal = AuthenticatedIdentity(
        Identity("test:admin", "admin@example.invalid", "Admin"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    html = render_call_inventory(
        principal,
        summaries,
        preference=CallNavigationPreference("resume-last-opened"),
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            page.set_content(
                html.replace("<head>", '<head><base href="https://localhost/">', 1),
                wait_until="domcontentloaded",
            )
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "shell.js"))

            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert page.get_by_role("link", name="EHF 2026 Open").count() == 1
            assert page.get_by_role("link", name="EHF 2027 Draft").count() == 1
            assert page.locator(".call-card").count() == 2
            assert page.locator("[data-call-default-mode]").input_value() == "resume-last-opened"
            if viewport[0] <= 720:
                toggle = page.get_by_role("button", name="Open application navigation")
                toggle.click()
                assert page.locator(".app-nav").get_attribute("data-open") == "true"
            results = Axe().run(page)
            assert results.violations_count == 0, results.generate_report()
        finally:
            browser.close()
