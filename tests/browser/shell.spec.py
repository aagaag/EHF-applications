"""Browser-level Task 6 checks for the inspectable shared EHF shell."""

from __future__ import annotations

import os
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
            assert page.locator(".shell-card").count() >= 1
            assert page.locator(".preview-notice").count() == 1
            assert page.locator(".report-table").count() == 1
            assert page.get_by_role("link", name="Download Excel").count() == 1
            assert "Preview only" in page.locator(".preview-notice").inner_text()
            assert page.locator("text=Authorizations:").count() == 1

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
            PreviewApplicantMetric(
                applicant="Applicant One",
                degree="PhD",
                age=36,
                academic_age=8.5,
                gender=None,
                first_author_papers=7,
                last_author_papers=2,
                total_papers=18,
                h_index=12,
                total_citations=640,
                orcid="0000-0002-1825-0097",
                google_scholar_citations=710,
                identity_certainty="High",
            ),
        ),
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
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "shell.js"))

            row = page.locator("[data-report-row]")
            row.dblclick()

            modal = page.locator("[data-report-modal]")
            assert modal.get_attribute("open") == ""
            assert modal.get_by_role("heading", name="Applicant One").count() == 1
            assert modal.locator("dt").count() == 13
            assert modal.locator("dd").count() == 13
            assert modal.locator("dd", has_text="Missing").count() == 1
            assert modal.locator("dd", has_text="0000-0002-1825-0097").count() == 1

            missing = modal.locator(".missing-value")
            assert missing.evaluate("node => getComputedStyle(node).color") == "rgb(180, 35, 24)"
            assert missing.evaluate("node => getComputedStyle(node).fontWeight") == "800"
            assert Axe().run(page).violations_count == 0

            modal.get_by_role("button", name="Close details").click()
            assert modal.get_attribute("open") is None
            assert page.evaluate("document.activeElement === document.querySelector('[data-report-row]')")
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

            assert page.locator("[data-report-sort]").count() == 26
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
