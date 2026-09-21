from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_shortlist_group_control_saves_reverts_on_failure_and_never_opens_row() -> None:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    from app.identity import AuthenticatedIdentity
    from app.internal_preview import PreviewApplicantMetric, render_internal_preview
    from app.navigation import INTERNAL_GROUPS
    from app.preferences import Identity
    from app.shortlist import ADRIANO_ENTRA_OBJECT_ID, ShortlistState

    application_id = "a7000000-0000-4000-8000-000000000001"
    principal = AuthenticatedIdentity(
        Identity("entra:adriano", "adriano@example.org", "Adriano"),
        frozenset({INTERNAL_GROUPS.administrators}),
        ADRIANO_ENTRA_OBJECT_ID,
    )
    html = render_internal_preview(
        principal,
        records=(PreviewApplicantMetric(applicant="Ada", application_id=application_id),),
        shortlist=ShortlistState({}, "adriano"),
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_viewport_size({"width": 1366, "height": 768})
            calls: list[dict[str, object]] = []

            def save(route, request) -> None:
                calls.append(request.post_data_json)
                route.fulfill(status=200, content_type="application/json", body='{"group":"B"}')

            page.route("**/api/internal/applicants/**/shortlist/adriano", save)
            page.set_content(html.replace("<head>", '<head><base href="https://localhost/">', 1), wait_until="domcontentloaded")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "shell.js"))

            assert page.locator('[data-shortlist-owner="ricky"][data-shortlist-assignment="unassigned"]').count() == 1
            assert page.locator('[data-shortlist-owner="magda"][data-shortlist-assignment="unassigned"]').count() == 1
            group_b = page.locator('[data-shortlist-grade][data-shortlist-owner="adriano"][data-shortlist-group="B"]')
            assert group_b.is_enabled()
            group_control = page.locator(".shortlist-grade-control")
            assert group_control.evaluate("node => node.getBoundingClientRect().width") <= 134
            assert group_b.evaluate("node => Number.parseFloat(getComputedStyle(node).fontSize)") == page.locator(
                ".report-data-row"
            ).evaluate("node => Number.parseFloat(getComputedStyle(node).fontSize)")
            group_b.click()
            page.get_by_text("Adriano group B saved.", exact=True).wait_for()
            assert calls == [{"group": "B"}]
            assert group_b.get_attribute("aria-pressed") == "true"
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert not page.locator("[data-report-modal]").evaluate("node => node.open")

            page.unroute("**/api/internal/applicants/**/shortlist/adriano", save)
            page.route(
                "**/api/internal/applicants/**/shortlist/adriano",
                lambda route: route.fulfill(status=500),
            )
            group_c = page.locator('[data-shortlist-grade][data-shortlist-owner="adriano"][data-shortlist-group="C"]')
            group_c.click()
            page.get_by_text("Adriano group C could not be saved; the previous assignment was restored.", exact=True).wait_for()
            assert group_b.get_attribute("aria-pressed") == "true"
            assert group_c.get_attribute("aria-pressed") == "false"
        finally:
            browser.close()
