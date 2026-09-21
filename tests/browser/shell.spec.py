"""Browser-level Task 6 checks for the inspectable shared EHF shell."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest


ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def preview_server() -> Iterator[str]:
    """Run the actual ASGI preview on an ephemeral loopback port."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        import httpx

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health/live", timeout=0.2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            raise AssertionError("preview server did not become ready")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.parametrize("viewport", [(1440, 900), (1024, 768), (720, 900), (390, 844)])
def test_shared_shell_is_responsive_keyboard_accessible_and_has_no_horizontal_overflow(
    viewport: tuple[int, int],
) -> None:
    """Break caught: the shared shell could clip, fail as a drawer, or lose keyboard access."""
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright

    with preview_server() as base_url, sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - environment-specific browser installation
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(f"{base_url}/__preview/internal/administrator/", wait_until="domcontentloaded")
            page.locator("html[data-preferences-ready='true']").wait_for()
            assert not page_errors, page_errors
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert page.locator(".shell-card").count() == 0
            assert page.locator(".preview-notice").count() == 1
            assert page.locator(".report-table").count() == 1
            assert page.get_by_role("link", name="Download Excel").count() == 1
            assert "Preview only" in page.locator(".preview-notice").inner_text()
            assert page.locator("text=Authorizations:").count() == 1
            if viewport[0] >= 1280:
                cards = page.locator(".report-grid .report-card")
                assert cards.count() == 3
                top_edges = cards.evaluate_all(
                    "nodes => nodes.map(node => node.getBoundingClientRect().top)"
                )
                assert max(top_edges) - min(top_edges) < 1
                assert page.locator(".report-header [role='columnheader']").count() == 13
                header_columns = page.locator(".report-header").evaluate(
                    "node => getComputedStyle(node).gridTemplateColumns.split(' ').length"
                )
                assert header_columns == 4

            if viewport[0] <= 720:
                assert page.evaluate("matchMedia('(max-width: 720px)').matches")
                toggle = page.get_by_role("button", name="Open application navigation")
                toggle.focus()
                toggle.press("Enter")
                assert page.get_by_role("complementary", name="Application navigation").get_attribute("data-open") == "true"
                assert page.locator(".app-nav").evaluate("node => !node.inert")
                assert page.evaluate("document.activeElement.closest('#application-navigation') !== null")
                page.locator(".app-nav-backdrop").click(
                    position={"x": viewport[0] - 10, "y": 100}
                )
                assert toggle.get_attribute("aria-expanded") == "false"
                assert page.evaluate("document.activeElement === document.querySelector('.app-nav-toggle')")
                toggle.press("Enter")
                page.get_by_role("button", name="Help").click()
                assert page.locator("#help-links").is_visible()
                page.keyboard.press("Escape")
                assert toggle.get_attribute("aria-expanded") == "false"
                assert page.evaluate("document.activeElement === document.querySelector('.app-nav-toggle')")

            results = Axe().run(page)
            assert results.violations_count == 0, results.generate_report()
        finally:
            browser.close()


def test_applicant_preview_is_accessible_and_closed_mobile_drawer_is_not_tabbable() -> None:
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright

    with preview_server() as base_url, sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - environment-specific browser installation
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(f"{base_url}/applicant/", wait_until="domcontentloaded")
            page.locator("html[data-preferences-ready='true']").wait_for()
            assert page.locator(".app-nav").evaluate("node => node.inert")
            page.get_by_role("button", name="Open application navigation").focus()
            page.keyboard.press("Tab")
            assert page.evaluate("document.activeElement.closest('#application-navigation') === null")
            assert page.evaluate("document.activeElement === document.querySelector('.shell-card')")
            assert Axe().run(page).violations_count == 0
        finally:
            browser.close()


def test_report_row_double_click_opens_all_details_and_emphasizes_missing_values() -> None:
    """Break caught: report rows could stop opening details or hide incomplete fields."""
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import expect, sync_playwright

    from app.identity import AuthenticatedIdentity
    from app.internal_preview import PreviewApplicantMetric, render_internal_preview
    from app.navigation import INTERNAL_GROUPS
    from app.preferences import Identity

    principal = AuthenticatedIdentity(
        Identity("development:administrator", "preview@example.invalid", "Preview"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    html = render_internal_preview(
        principal,
        simulation=True,
        records=(
            PreviewApplicantMetric(
                applicant="Applicant One",
                degree="PhD",
                age=36,
                academic_age=8.5,
                gender=None,
                first_author_papers=7,
                last_author_papers=2,
                total_papers=18,
                validated_published_papers=16,
                h_index=12,
                total_citations=640,
                orcid="0000-0002-1825-0097",
                google_scholar_citations=710,
                identity_certainty="High",
                verified_citations=705,
                verified_citation_source="OpenAlex",
            ),
        ),
    )

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - environment-specific browser installation
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.set_content(html, wait_until="domcontentloaded")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
            page.evaluate(
                """window.fetch = async url => {
                    const target = String(url);
                    if (target.endsWith('/review-artifacts')) {
                      return {ok: true, json: async () => ({available: ['publications']})};
                    }
                    if (target.endsWith('/documents/package/view')) {
                      return {ok: true, blob: async () => new Blob(['%PDF-1.7'], {type: 'application/pdf'})};
                    }
                    return {ok: false};
                  };
                  window.open = (url, target, features) => {
                    window.reportArtifactOpen = {url, target, features};
                    return null;
                  };"""
            )
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "shell.js"))

            row = page.locator("[data-report-row]")
            row.evaluate(
                "node => { node.dataset.applicationId = 'a7000000-0000-4000-8000-000000000001'; }"
            )
            row.dblclick()

            modal = page.locator("[data-report-modal]")
            assert modal.get_attribute("open") == ""
            assert modal.get_by_role("heading", name="Applicant One").count() == 1
            assert modal.locator("dt").count() == 9
            assert modal.locator("dd").count() == 9
            assert modal.locator("dd", has_text="Missing").count() == 1
            assert modal.locator("dd", has_text="0000-0002-1825-0097").count() == 0

            application = modal.get_by_role("link", name="Application")
            curriculum = modal.locator('[data-report-artifact="curriculum"]')
            publications = modal.get_by_role("link", name="Publication list")
            expect(application).to_have_attribute("target", "_blank")
            expect(application).to_have_attribute("rel", "noopener noreferrer")
            expect(application).to_have_attribute("aria-disabled", "false")
            expect(application).to_have_attribute(
                "href",
                "/api/internal/applicants/a7000000-0000-4000-8000-000000000001/documents/package/view",
            )
            assert application.evaluate(
                "node => !node.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}))"
            )
            page.wait_for_function("() => Boolean(window.reportArtifactOpen)")
            opened = page.evaluate("window.reportArtifactOpen")
            assert opened["target"] == "_blank"
            assert opened["features"] == "noopener,noreferrer"
            assert str(opened["url"]).startswith("blob:")
            expect(curriculum).to_have_attribute("aria-disabled", "true")
            expect(curriculum).not_to_have_attribute("href", re.compile(".+"))
            expect(publications).to_have_attribute("aria-disabled", "false")
            expect(
                modal.get_by_text(
                    "Full application PDF is available. 1 reviewed supporting PDF is available.",
                    exact=False,
                )
            ).to_be_visible()

            missing = modal.locator(".missing-value")
            assert missing.evaluate("node => getComputedStyle(node).color") == "rgb(180, 35, 24)"
            assert missing.evaluate("node => getComputedStyle(node).fontWeight") == "800"
            assert Axe().run(page).violations_count == 0

            modal.get_by_role("button", name="Close details").click()
            assert modal.get_attribute("open") is None
            assert page.evaluate("document.activeElement === document.querySelector('[data-report-row]')")
        finally:
            browser.close()


def test_applicant_detail_keeps_three_charts_side_by_side_and_colours_lead_authors_red() -> None:
    """Break caught: the compact modal could stack the new chart or lose author emphasis."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    from app.applicant_detail import ApplicantDetail, Publication, render_applicant_detail

    html = render_applicant_detail(
        ApplicantDetail(
            application_number="EHF-2026-007",
            name="Ada Researcher",
            publications=(
                Publication(
                    title="Lead work",
                    year=2025,
                    citation_count=4,
                    authors_text="Ada Researcher; Ben Biologist",
                    citations_by_year=((2025, 4),),
                    journal_openalex_name="Example Journal",
                    journal_two_year_mean_citedness=3.0,
                ),
                Publication(
                    title="Collaborative work",
                    year=2024,
                    citation_count=2,
                    authors_text="Ben Biologist; Ada Researcher; Cara Chemist",
                    journal_openalex_name="Other Journal",
                    journal_two_year_mean_citedness=1.5,
                ),
            ),
        ),
        current_year=2026,
    )

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - environment-specific browser installation
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": 1024, "height": 768})
            page.set_content(html, wait_until="domcontentloaded")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))

            charts = page.locator(".applicant-detail-chart")
            first_chart, second_chart, third_chart = (
                charts.nth(0).bounding_box(),
                charts.nth(1).bounding_box(),
                charts.nth(2).bounding_box(),
            )
            assert first_chart is not None and second_chart is not None and third_chart is not None
            assert second_chart["x"] > first_chart["x"]
            assert third_chart["x"] > second_chart["x"]
            assert max(abs(chart["y"] - first_chart["y"]) for chart in (second_chart, third_chart)) < 1

            lead = page.locator('[data-publication-row][data-author-position="first"]')
            assert lead.evaluate("node => getComputedStyle(node).color") == "rgb(180, 35, 24)"
            bubble = page.locator(".journal-scatter-point--lead-author").first
            assert bubble.evaluate("node => getComputedStyle(node).fill") == "rgb(180, 35, 24)"
            assert page.locator(".journal-scatter-point--other-author").evaluate(
                "node => getComputedStyle(node).fill"
            ) == "rgb(34, 111, 181)"
            assert bubble.evaluate("node => { node.focus(); return document.activeElement === node }")
        finally:
            browser.close()


@pytest.mark.parametrize("viewport", [(1920, 1080), (1366, 768), (720, 900), (390, 844)])
def test_journal_scatter_is_responsive_focusable_and_visible_in_every_skin(
    viewport: tuple[int, int],
) -> None:
    """Break caught: a new chart could overflow, lose point focus, or lose role emphasis by skin."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    from app.applicant_detail import ApplicantDetail, Publication, render_applicant_detail

    html = render_applicant_detail(
        ApplicantDetail(
            application_number="EHF-2026-007",
            name="Ada Researcher",
            publications=(
                Publication(
                    title="Lead journal paper",
                    journal="Example Journal",
                    year=2025,
                    citation_count=7,
                    authors_text="Ada Researcher; Ben Biologist",
                    journal_openalex_name="Example Journal",
                    journal_two_year_mean_citedness=5.0,
                ),
                Publication(
                    title="Unavailable source paper",
                    journal="Repository",
                    year=2024,
                    citation_count=None,
                ),
            ),
        ),
        current_year=2026,
    )

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - environment-specific browser installation
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            page.set_content(html, wait_until="domcontentloaded")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))

            charts = page.locator(".applicant-detail-chart")
            boxes = [charts.nth(index).bounding_box() for index in range(3)]
            assert all(box is not None for box in boxes)
            first, second, third = boxes
            assert first is not None and second is not None and third is not None
            if viewport[0] <= 800:
                assert second["y"] > first["y"] and third["y"] > second["y"]
            else:
                assert first["y"] == second["y"] == third["y"]
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

            bubbles = page.locator("[data-journal-scatter-point]")
            assert bubbles.count() == 1
            assert page.locator(".journal-scatter-na-lane").count() == 0
            for index in range(bubbles.count()):
                assert bubbles.nth(index).evaluate(
                    "node => { node.focus(); return document.activeElement === node && node.getAttribute('aria-label').length > 20 }"
                )
            for skin in (None, "high-contrast", "soft-earth", "blue"):
                page.evaluate(
                    "skin => skin ? document.documentElement.setAttribute('data-skin', skin) : document.documentElement.removeAttribute('data-skin')",
                    skin,
                )
                assert page.locator(".journal-scatter-point--lead-author").evaluate(
                    "node => getComputedStyle(node).fill"
                ) == "rgb(180, 35, 24)"
        finally:
            browser.close()


def test_modal_chart_opens_as_a_full_page_graph_in_a_new_tab() -> None:
    """Break caught: modal chart clicks could not expand into a reviewable graph."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import expect, sync_playwright

    from app.applicant_detail import ApplicantDetail, Publication, render_applicant_detail
    from app.identity import AuthenticatedIdentity
    from app.internal_preview import PreviewApplicantMetric, render_internal_preview
    from app.navigation import INTERNAL_GROUPS
    from app.preferences import Identity

    application_id = "a7000000-0000-4000-8000-000000000001"
    principal = AuthenticatedIdentity(
        Identity("development:administrator", "preview@example.invalid", "Preview"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    page_html = render_internal_preview(
        principal,
        simulation=True,
        records=(PreviewApplicantMetric(applicant="Applicant One", application_id=application_id),),
    )
    detail_html = render_applicant_detail(
        ApplicantDetail(
            application_number="EHF-2026-001",
            name="Applicant One",
            publications=(Publication(title="A paper", year=2025, citation_count=2),),
        ),
        current_year=2026,
    )

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page()
            full_page_html = """<!doctype html><html lang=\"en\"><head><link rel=\"stylesheet\" href=\"/assets/site.css\"></head><body class=\"chart-page\"><main class=\"site-main\"><h1>Papers by year</h1><figure class=\"applicant-detail-chart\" data-full-page-chart><figcaption>Papers by year</figcaption></figure></main></body></html>"""
            css = (ROOT / "public" / "assets" / "site.css").read_text(encoding="utf-8")

            def route(route):  # type: ignore[no-untyped-def]
                if route.request.url == "https://ehf.test/internal/":
                    route.fulfill(
                        content_type="text/html",
                        body=page_html,
                    )
                elif route.request.url == "https://ehf.test/assets/site.css":
                    route.fulfill(content_type="text/css", body=css)
                elif route.request.url == f"https://ehf.test/api/internal/applicants/{application_id}/metrics-detail?full_page_chart=0":
                    route.fulfill(
                        content_type="text/html",
                        body=full_page_html,
                        headers={"Content-Security-Policy": "default-src 'none'; style-src 'self'; base-uri 'none'"},
                    )
                else:
                    route.fulfill(status=404)

            page.context.route("https://ehf.test/**", route)
            page.goto("https://ehf.test/internal/")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
            page.evaluate(
                """detail => { window.fetch = async url => String(url).endsWith('/review-artifacts')
                    ? {ok: true, json: async () => ({available: []})}
                    : {ok: true, text: async () => detail}; }""",
                detail_html,
            )
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "shell.js"))
            page.locator("[data-report-row]").dblclick()

            chart = page.locator("[data-full-page-chart]").first
            expect(chart).to_be_visible()
            with page.expect_popup() as popup_info:
                chart.click()
            popup = popup_info.value
            popup.wait_for_load_state()
            assert popup.url == f"https://ehf.test/api/internal/applicants/{application_id}/metrics-detail?full_page_chart=0", popup.url
            expect(popup.get_by_role("heading", name="Papers by year")).to_be_visible()
            expect(popup.locator("[data-full-page-chart]")).to_have_count(1)
            assert popup.locator(".applicant-detail-chart").evaluate(
                "node => getComputedStyle(node).borderTopWidth"
            ) == "1px"
        finally:
            browser.close()


def test_modal_identity_items_stay_compact_on_one_desktop_line() -> None:
    """Break caught: identity fields could expand into unused modal width."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import expect, sync_playwright

    from app.applicant_detail import ApplicantDetail, render_applicant_detail
    from app.identity import AuthenticatedIdentity
    from app.internal_preview import PreviewApplicantMetric, render_internal_preview
    from app.navigation import INTERNAL_GROUPS
    from app.preferences import Identity

    application_id = "a7000000-0000-4000-8000-000000000001"
    principal = AuthenticatedIdentity(
        Identity("development:administrator", "preview@example.invalid", "Preview"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    page_html = render_internal_preview(
        principal,
        simulation=True,
        records=(PreviewApplicantMetric(applicant="Applicant One", application_id=application_id),),
    )
    detail_html = render_applicant_detail(
        ApplicantDetail(
            application_number="EHF-2026-001",
            name="Applicant One",
            age=34,
            academic_age=4.8,
        )
    )

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.set_content(page_html, wait_until="domcontentloaded")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
            page.evaluate(
                """detail => { window.fetch = async url => String(url).endsWith('/review-artifacts')
                    ? {ok: true, json: async () => ({available: []})}
                    : {ok: true, text: async () => detail}; }""",
                detail_html,
            )
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "shell.js"))
            page.locator("[data-report-row]").dblclick()

            identity = page.locator(".applicant-detail-identity")
            items = identity.locator(":scope > span")
            expect(items).to_have_count(4)
            boxes = [item.bounding_box() for item in items.all()]
            assert all(box is not None for box in boxes)
            assert len({round(box["y"]) for box in boxes if box is not None}) == 1
            assert identity.evaluate("node => getComputedStyle(node).flexWrap") == "nowrap"
            assert boxes[1] is not None and boxes[1]["width"] < identity.bounding_box()["width"] * 0.4
            page.set_viewport_size({"width": 390, "height": 844})
            assert identity.evaluate("node => getComputedStyle(node).flexWrap") == "wrap"
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        finally:
            browser.close()


def test_modal_publication_citations_sort_numerically_with_missing_values_last() -> None:
    """Break caught: citation counts could sort lexically or move missing values ahead."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import expect, sync_playwright

    from app.applicant_detail import ApplicantDetail, Publication, render_applicant_detail
    from app.identity import AuthenticatedIdentity
    from app.internal_preview import PreviewApplicantMetric, render_internal_preview
    from app.navigation import INTERNAL_GROUPS
    from app.preferences import Identity

    application_id = "a7000000-0000-4000-8000-000000000001"
    principal = AuthenticatedIdentity(
        Identity("development:administrator", "preview@example.invalid", "Preview"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    page_html = render_internal_preview(
        principal,
        simulation=True,
        records=(PreviewApplicantMetric(applicant="Applicant One", application_id=application_id),),
    )
    detail_html = render_applicant_detail(
        ApplicantDetail(
            application_number="EHF-2026-001",
            name="Applicant One",
            publications=(
                Publication(title="First ten", year=2025, citation_count=10),
                Publication(title="Missing", year=2024, citation_count=None),
                Publication(title="Two", year=2023, citation_count=2),
                Publication(title="Second ten", year=2022, citation_count=10),
            ),
        ),
        current_year=2026,
    )

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.set_content(page_html, wait_until="domcontentloaded")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
            page.evaluate(
                """detail => { window.fetch = async url => String(url).endsWith('/review-artifacts')
                    ? {ok: true, json: async () => ({available: []})}
                    : {ok: true, text: async () => detail}; }""",
                detail_html,
            )
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "shell.js"))
            page.locator("[data-report-row]").dblclick()

            rows = page.locator("[data-publication-row]")
            expect(rows).to_have_count(4)
            page.get_by_role("button", name="Sort citations ascending").click()
            assert rows.locator(".publication-title").all_inner_texts() == [
                "Two", "First ten", "Second ten", "Missing"
            ]
            page.get_by_role("button", name="Sort citations descending").click()
            assert rows.locator(".publication-title").all_inner_texts() == [
                "First ten", "Second ten", "Two", "Missing"
            ]
            expect(page.locator("[data-publication-citation-header]")).to_have_attribute(
                "aria-sort", "descending"
            )
        finally:
            browser.close()


def test_report_field_triangles_sort_text_and_numbers_with_missing_values_last() -> None:
    """Break caught: field sort controls could disappear or order numeric and missing values incorrectly."""
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright

    from app.identity import AuthenticatedIdentity
    from app.internal_preview import PreviewApplicantMetric, render_internal_preview
    from app.navigation import INTERNAL_GROUPS
    from app.preferences import Identity

    principal = AuthenticatedIdentity(
        Identity("development:administrator", "preview@example.invalid", "Preview"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    html = render_internal_preview(
        principal,
        simulation=True,
        records=(
            PreviewApplicantMetric(applicant="Applicant Z", age=41),
            PreviewApplicantMetric(applicant="Applicant A", age=29),
            PreviewApplicantMetric(applicant="Applicant M", age=None),
        ),
    )

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - environment-specific browser installation
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.set_content(html, wait_until="domcontentloaded")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "shell.js"))

            def applicant_order() -> list[str]:
                return page.locator("[data-report-row] [role='cell']:first-child").all_inner_texts()

            assert page.locator("[data-report-sort]").count() == 18
            assert page.get_by_role("button", name="Sort Applicant ascending").is_visible()

            page.get_by_role("button", name="Sort Applicant ascending").click()
            assert applicant_order() == ["Applicant A", "Applicant M", "Applicant Z"]
            assert page.locator('[data-report-column="Applicant"]').get_attribute("aria-sort") == "ascending"

            page.get_by_role("button", name="Sort Applicant descending").click()
            assert applicant_order() == ["Applicant Z", "Applicant M", "Applicant A"]
            assert page.locator('[data-report-column="Applicant"]').get_attribute("aria-sort") == "descending"

            page.get_by_role("button", name="Sort Age ascending").click()
            assert applicant_order() == ["Applicant A", "Applicant Z", "Applicant M"]

            page.get_by_role("button", name="Sort Age descending").click()
            assert applicant_order() == ["Applicant Z", "Applicant A", "Applicant M"]
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert Axe().run(page).violations_count == 0
        finally:
            browser.close()


def test_report_dropdown_filters_completed_and_missing_applications_only() -> None:
    """Break caught: the completeness filter could misclassify rows or expose extra categories."""
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright

    from app.identity import AuthenticatedIdentity
    from app.internal_preview import PreviewApplicantMetric, render_internal_preview
    from app.navigation import INTERNAL_GROUPS
    from app.preferences import Identity

    principal = AuthenticatedIdentity(
        Identity("development:administrator", "preview@example.invalid", "Preview"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    complete = PreviewApplicantMetric(
        applicant="Complete Applicant",
        degree="PhD",
        age=36,
        academic_age=8.5,
        gender="Female",
        first_author_papers=7,
        last_author_papers=2,
        total_papers=18,
        validated_published_papers=16,
        h_index=12,
        total_citations=640,
        orcid="0000-0002-1825-0097",
        google_scholar_citations=710,
        identity_certainty="High",
        verified_citations=705,
        verified_citation_source="OpenAlex",
    )
    incomplete = PreviewApplicantMetric(
        applicant="Missing Applicant",
        degree="MD",
        age=41,
        academic_age=10,
        gender=None,
        first_author_papers=6,
        last_author_papers=3,
        total_papers=20,
        h_index=14,
        total_citations=800,
        orcid="0000-0001-5109-3700",
        google_scholar_citations=850,
        identity_certainty="High",
    )
    html = render_internal_preview(principal, simulation=True, records=(complete, incomplete))

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - environment-specific browser installation
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.set_content(html, wait_until="domcontentloaded")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "shell.js"))

            dropdown = page.get_by_label("Filter applicants")
            selectable = dropdown.locator("option:not([disabled])").all_inner_texts()
            assert selectable == [
                "Completed applications",
                "Applications where anything is missing",
            ]
            assert page.locator("[data-report-row]:visible").count() == 2

            dropdown.select_option("completed")
            assert page.locator('[data-report-row][data-report-status="completed"]:visible').count() == 1
            assert page.locator('[data-report-row][data-report-status="missing"]:visible').count() == 0
            assert page.get_by_text("Complete Applicant", exact=True).is_visible()

            dropdown.select_option("missing")
            assert page.locator('[data-report-row][data-report-status="completed"]:visible').count() == 0
            assert page.locator('[data-report-row][data-report-status="missing"]:visible').count() == 1
            assert page.get_by_text("Missing Applicant", exact=True).is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert Axe().run(page).violations_count == 0
        finally:
            browser.close()


def test_citation_plot_callouts_remain_distinct_accessible_and_responsive() -> None:
    """Break caught: colored call-outs could overlap the page or lose accessible identity."""
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright

    from app.identity import AuthenticatedIdentity
    from app.internal_preview import PreviewApplicantMetric, render_internal_preview
    from app.navigation import INTERNAL_GROUPS
    from app.preferences import Identity

    principal = AuthenticatedIdentity(
        Identity("development:administrator", "preview@example.invalid", "Preview"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    records = tuple(
        PreviewApplicantMetric(
            applicant=f"Given Exceptionally-Long-Hyphenated-Surname{index:02d}",
            age=40,
            academic_age=8,
            verified_citations=index,
            h_index=index,
        )
        for index in range(18)
    )
    html = render_internal_preview(principal, simulation=True, records=records)

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - environment-specific browser installation
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            for width, height in ((1024, 768), (390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height})
                page.set_content(html, wait_until="domcontentloaded")
                page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))

                assert page.locator(".report-card").count() == 3
                assert page.locator(".plot-point").count() == 54
                assert page.locator(".plot-bubble").count() == 18
                assert 0 < page.locator(".plot-callout").count() <= 45
                assert page.locator(".plot-callout-line").count() == page.locator(
                    ".plot-callout"
                ).count()
                assert page.locator(".plot-callout-halo").count() == 0
                assert page.locator(".plot-callout-label tspan").count() == 0
                assert page.locator(".plot-callout-line").evaluate_all(
                    "nodes => nodes.every(node => node.getTotalLength() <= 60)"
                )
                first_chart_colors = page.locator(
                    ".report-card:first-child .plot-point"
                ).evaluate_all(
                    "nodes => nodes.map(node => getComputedStyle(node).fill)"
                )
                assert len(set(first_chart_colors)) == 18
                assert page.locator(
                    '.plot-point[aria-label="Given Exceptionally-Long-Hyphenated-Surname17: anagraphic age 40, 17 citations, h-index 17"]'
                ).count() == 1
                assert page.locator(".plot-callout-label").evaluate_all(
                    """nodes => nodes.every(node => {
                        const label = node.getBoundingClientRect();
                        const svg = node.ownerSVGElement.getBoundingClientRect();
                        return label.left >= svg.left - 0.5
                            && label.right <= svg.right + 0.5
                            && label.left >= -0.5
                            && label.right <= window.innerWidth + 0.5;
                    })"""
                )
                assert page.locator(".plot-callout-label").evaluate_all(
                    """nodes => nodes.every((label, index) => {
                        const first = label.getBoundingClientRect();
                        return nodes.slice(index + 1).every(other => {
                            const second = other.getBoundingClientRect();
                            return first.right <= second.left || second.right <= first.left
                                || first.bottom <= second.top || second.bottom <= first.top;
                        });
                    })"""
                )
                for skin in ("default", "high-contrast", "soft-earth", "blue"):
                    page.evaluate(
                        "skin => document.documentElement.dataset.skin = skin", skin
                    )
                    contrast = page.locator(".report-card:first-child").evaluate(
                        """card => {
                            const channels = value => value.match(/[0-9.]+/g)
                                .slice(0, 3).map(Number);
                            const luminance = value => {
                                const rgb = channels(value).map(channel => {
                                    const normalized = channel / 255;
                                    return normalized <= 0.04045
                                        ? normalized / 12.92
                                        : ((normalized + 0.055) / 1.055) ** 2.4;
                                });
                                return 0.2126 * rgb[0] + 0.7152 * rgb[1]
                                    + 0.0722 * rgb[2];
                            };
                            const ratio = (first, second) => {
                                const values = [luminance(first), luminance(second)]
                                    .sort((a, b) => b - a);
                                return (values[0] + 0.05) / (values[1] + 0.05);
                            };
                            const surface = getComputedStyle(card).backgroundColor;
                            return {
                                point: ratio(
                                    getComputedStyle(card.querySelector('.plot-point')).stroke,
                                    surface
                                ),
                                label: ratio(
                                    getComputedStyle(card.querySelector('.plot-callout-label')).fill,
                                    surface
                                ),
                            };
                        }"""
                    )
                    assert contrast["point"] >= 3
                    assert contrast["label"] >= 3
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
                assert Axe().run(page).violations_count == 0
                page.close()
        finally:
            browser.close()
