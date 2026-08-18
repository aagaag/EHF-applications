from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "public"
BANNER = "Synthetic test — administrator session"


def _content(path: str) -> str:
    html = (PUBLIC / path).read_text(encoding="utf-8")
    return html.replace("<head>", '<head><base href="https://ehf.example/">', 1)


def _prepare_origin(page) -> None:  # type: ignore[no-untyped-def]
    page.route(
        "https://ehf.example/__test_origin",
        lambda route: route.fulfill(body="<!doctype html><title>test</title>"),
    )
    page.goto("https://ehf.example/__test_origin")


def _fulfill_applicant(route) -> None:  # type: ignore[no-untyped-def]
    path = route.request.url.split("ehf.example", 1)[-1]
    if path == "/api/applicant/session":
        route.fulfill(json={"authenticated": True, "syntheticAdmin": True})
    elif path == "/api/applicant/review/fields":
        route.fulfill(json={"fields": []})
    elif path == "/api/applicant/application":
        route.fulfill(json={"applicant": {}, "documents": []})
    elif path.startswith("/api/applicant/review/"):
        route.fulfill(
            json={
                "values": {},
                "rowVersion": None,
                "confirmed": False,
                "returnedForCorrection": None,
            }
        )
    elif path == "/api/applicant/finalization":
        route.fulfill(json={"ready": False, "unresolved": [], "manifest": {}})
    else:
        route.fulfill(status=404, json={})


def test_administrator_action_is_one_keyboard_card_and_is_hidden_from_trustees() -> None:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": 1024, "height": 768})
            page.set_default_timeout(5000)
            page.set_default_navigation_timeout(5000)
            _prepare_origin(page)
            page.route(
                "**/api/internal/applicant-previews",
                lambda route: route.fulfill(json={"applications": []}),
            )
            page.route(
                "**/api/internal/applicant-access-requests",
                lambda route: route.fulfill(json={"requests": []}),
            )
            page.route(
                "**/api/internal/applicant-submissions",
                lambda route: route.fulfill(
                    json={"submissions": [], "capabilities": {}}
                ),
            )
            page.route(
                "**/api/internal/applicant-document-submissions",
                lambda route: route.fulfill(json={"submissions": []}),
            )
            submitted: list[tuple[str, str | None]] = []

            def create(route) -> None:  # type: ignore[no-untyped-def]
                submitted.append((route.request.method, route.request.post_data))
                route.fulfill(
                    status=303,
                    headers={"Location": "/applicant/review"},
                    body="",
                )

            page.route("**/api/internal/synthetic-applicants", create)
            page.route(
                "**/applicant/review",
                lambda route: route.fulfill(body="<h1>Review your application</h1>"),
            )
            page.set_content(_content("internal/applicant-review.html"))
            page.add_script_tag(
                path=str(PUBLIC / "assets" / "internal-applicant-review.js")
            )

            action = page.get_by_role(
                "button", name="Create synthetic applicant and open form"
            )
            action.wait_for(state="visible")
            assert action.locator("xpath=ancestor::form").count() == 1
            action.focus()
            action.press("Enter")
            assert submitted and submitted[0][0] == "POST"
            assert submitted[0][1] in (None, "")

            trustee = browser.new_page(viewport={"width": 1024, "height": 768})
            trustee.set_default_timeout(5000)
            _prepare_origin(trustee)
            trustee.route(
                "**/api/internal/applicant-previews",
                lambda route: route.fulfill(status=404, json={}),
            )
            trustee.route(
                "**/api/internal/**",
                lambda route: route.fulfill(json={"requests": [], "submissions": []}),
            )
            trustee.set_content(_content("internal/applicant-review.html"))
            trustee.add_script_tag(
                path=str(PUBLIC / "assets" / "internal-applicant-review.js")
            )
            assert trustee.get_by_role(
                "button", name="Create synthetic applicant and open form"
            ).is_hidden()
            trustee.close()
        finally:
            browser.close()


@pytest.mark.parametrize(
    ("html_path", "script_name"),
    (
        ("applicant/review.html", "applicant-review.js"),
        ("applicant/documents.html", "applicant-documents.js"),
        ("applicant/final-review.html", "applicant-finalize.js"),
    ),
)
def test_synthetic_banner_persists_in_four_skins_without_horizontal_overflow(
    html_path: str, script_name: str
) -> None:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            for width, height in ((1440, 900), (390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height})
                page.set_default_timeout(5000)
                _prepare_origin(page)
                page.route("https://ehf.example/**", _fulfill_applicant)
                page.set_content(_content(html_path))
                page.add_style_tag(path=str(PUBLIC / "assets" / "site.css"))
                page.add_script_tag(path=str(PUBLIC / "assets" / script_name))
                banner = page.get_by_text(BANNER, exact=True)
                banner.wait_for(state="visible")
                assert banner.evaluate(
                    "node => Boolean(node.compareDocumentPosition(document.querySelector('h1')) & Node.DOCUMENT_POSITION_FOLLOWING)"
                )
                for skin in ("default", "high-contrast", "soft-earth", "blue"):
                    page.evaluate(
                        "skin => document.documentElement.dataset.skin = skin", skin
                    )
                    assert banner.is_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                if script_name == "applicant-documents.js":
                    assert page.get_by_text(
                        "Documents are unavailable in a synthetic test workspace.",
                        exact=True,
                    ).is_visible()
                if script_name == "applicant-finalize.js":
                    assert page.get_by_role(
                        "button", name="Submit completed application"
                    ).is_disabled()
                page.close()
        finally:
            browser.close()
