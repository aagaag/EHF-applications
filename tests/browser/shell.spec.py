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
