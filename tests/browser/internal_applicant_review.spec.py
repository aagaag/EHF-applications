from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
APPLICATION_ID = "a7000000-0000-4000-8000-000000000001"
DOCUMENTS_URL = (
    f"https://localhost/internal/applicant-previews/{APPLICATION_ID}/documents"
)
PREVIEW_URL = f"https://localhost/internal/applicant-previews/{APPLICATION_ID}"


def _payload() -> dict[str, object]:
    return {
        "applications": [
            {
                "applicationId": APPLICATION_ID,
                "applicantName": "Synthetic Preview Applicant",
                "applicationStatus": "IMPORTED",
                "academicAgeYears": 4.5,
                "hIndex": 12,
                "citationCount": 734,
                "citationSource": "OPENALEX",
                "citationProfileUrl": "https://openalex.org/A123",
                "researchArea": "Synthetic neurodegeneration",
                "documentCount": 2,
                "href": f"/internal/applicant-previews/{APPLICATION_ID}",
                "documentsHref": (
                    f"/internal/applicant-previews/{APPLICATION_ID}/documents"
                ),
            },
            {
                "applicationId": "a7000000-0000-4000-8000-000000000002",
                "applicantName": "Synthetic Sparse Applicant",
                "applicationStatus": "IMPORTED",
                "academicAgeYears": None,
                "hIndex": None,
                "citationCount": None,
                "citationSource": None,
                "citationProfileUrl": None,
                "researchArea": None,
                "documentCount": 0,
                "href": "/internal/applicant-previews/a7000000-0000-4000-8000-000000000002",
                "documentsHref": (
                    "/internal/applicant-previews/"
                    "a7000000-0000-4000-8000-000000000002/documents"
                ),
            },
        ]
    }


def _load(page: object) -> None:
    html = (ROOT / "public" / "internal" / "applicant-review.html").read_text(
        encoding="utf-8"
    )
    html = html.replace("<head>", '<head><base href="https://localhost/internal/">', 1)
    for hosted_asset in (
        '<link rel="stylesheet" href="/assets/site.css">',
        '<script src="/assets/theme.js"></script>',
        '<script src="/assets/shell.js"></script>',
        '<script src="/assets/internal-applicant-review.js"></script>',
    ):
        html = html.replace(hosted_asset, "")
    page.route(
        "**/api/internal/applicant-access-requests",
        lambda route: route.fulfill(json={"requests": []}),
    )
    page.route(
        "**/api/internal/applicant-document-submissions",
        lambda route: route.fulfill(json={"submissions": []}),
    )
    page.route(
        "**/api/internal/applicant-submissions",
        lambda route: route.fulfill(json={"capabilities": {}, "submissions": []}),
    )
    page.route(
        "**/api/internal/applicant-previews",
        lambda route: route.fulfill(json=_payload()),
    )
    page.route(
        "**/documents",
        lambda route: route.fulfill(
            body="<!doctype html><title>proposal documents</title>"
        ),
    )
    page.route(
        "**/applicant-previews/a7000000-0000-4000-8000-000000000001",
        lambda route: route.fulfill(body="<!doctype html><title>applicant preview</title>"),
    )
    page.set_content(html, wait_until="domcontentloaded")
    page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
    page.add_script_tag(path=str(ROOT / "public" / "assets" / "shell.js"))
    page.add_script_tag(
        path=str(ROOT / "public" / "assets" / "internal-applicant-review.js")
    )


@pytest.fixture()
def browser_page():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            yield browser
        finally:
            browser.close()


def test_applicant_review_cards_show_the_review_metrics_and_the_pdf_gesture(
    browser_page: object,
) -> None:
    """Break caught: a card could hide the review metrics or promise a gesture it does not honour."""
    from playwright.sync_api import expect

    page = browser_page.new_page()
    _load(page)

    card = page.locator("a.preview-applicant-card").first
    expect(card).to_contain_text("Synthetic Preview Applicant")
    expect(card).to_contain_text("Academic age: 4.5 years")
    expect(card).to_contain_text("h-index: 12")
    expect(card).to_contain_text("Citations: 734 (OpenAlex)")
    expect(card).to_contain_text("Area of work: Synthetic neurodegeneration")
    expect(card).to_contain_text("2 proposal PDFs")
    assert card.get_attribute("data-documents-href") == (
        f"/internal/applicant-previews/{APPLICATION_ID}/documents"
    )

    sparse = page.locator("a.preview-applicant-card").nth(1)
    expect(sparse).to_contain_text("Academic age: Missing")
    expect(sparse).to_contain_text("h-index: Missing")
    expect(sparse).to_contain_text("Citations: Missing")
    expect(sparse).to_contain_text("Area of work: Missing")
    expect(sparse).to_contain_text("0 proposal PDFs")

    expect(page.get_by_text("Double-click a card, or focus it and press Ctrl+Enter")).to_be_visible()

    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.close()


def test_single_click_opens_the_application_and_double_click_opens_the_proposal_pdfs(
    browser_page: object,
) -> None:
    """Break caught: the double-click gesture could be swallowed by the single-click navigation."""
    page = browser_page.new_page()
    _load(page)
    card = page.locator("a.preview-applicant-card").first

    card.click()
    page.wait_for_url(PREVIEW_URL)
    assert page.url == PREVIEW_URL
    page.close()

    double = browser_page.new_page()
    _load(double)
    double.locator("a.preview-applicant-card").first.dblclick()
    double.wait_for_url(DOCUMENTS_URL)
    assert double.url == DOCUMENTS_URL
    double.close()


def test_keyboard_users_reach_the_proposal_pdfs_with_ctrl_enter(browser_page: object) -> None:
    """Break caught: the proposal PDFs were reachable by mouse only."""
    page = browser_page.new_page()
    _load(page)
    card = page.locator("a.preview-applicant-card").first

    card.focus()
    card.press("Control+Enter")

    page.wait_for_url(DOCUMENTS_URL)
    assert page.url == DOCUMENTS_URL
    page.close()


def test_internal_approval_renders_degree_and_publication_lists_readably() -> None:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import expect, sync_playwright

    html = (ROOT / "public" / "internal" / "applicant-review.html").read_text(
        encoding="utf-8"
    )
    html = html.replace("<head>", '<head><base href="https://localhost/internal/">', 1)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page()
            page.route(
                "**/api/internal/applicant-access-requests",
                lambda route: route.fulfill(json={"requests": []}),
            )
            page.route(
                "**/api/internal/applicant-document-submissions",
                lambda route: route.fulfill(json={"submissions": []}),
            )
            page.route(
                "**/api/internal/applicant-previews",
                lambda route: route.fulfill(
                    json={
                        "applications": [
                            {
                                "applicationId": "a7000000-0000-4000-8000-000000000001",
                                "applicantName": "Synthetic Preview Applicant",
                                "applicationStatus": "IMPORTED",
                                "href": "/internal/applicant-previews/a7000000-0000-4000-8000-000000000001",
                            }
                        ]
                    }
                ),
            )

            page.route(
                "**/api/internal/applicant-submissions/confirmation-1",
                lambda route: route.fulfill(
                    json={
                        "baseline": {
                            "applicant": {"degrees": [], "publications": []}
                        },
                        "drafts": {
                            "qualifications": {
                                "degrees": [
                                    {
                                        "degreeType": "PhD",
                                        "conferralDate": "2020-01-15",
                                    }
                                ]
                            },
                            "publications": {
                                "publications": [
                                    {"doi": "10.1000/one", "confirmed": True}
                                ]
                            },
                        },
                    }
                ),
            )
            page.route(
                "**/api/internal/applicant-submissions",
                lambda route: route.fulfill(
                    json={
                        "capabilities": {"returnForCorrection": True},
                        "submissions": [
                            {
                                "applicationId": "application-1",
                                "confirmationId": "confirmation-1",
                                "submittedAtUtc": "2026-08-18T10:00:00Z",
                            }
                        ],
                    }
                ),
            )
            page.set_content(html, wait_until="domcontentloaded")
            page.add_script_tag(
                path=str(ROOT / "public" / "assets" / "internal-applicant-review.js")
            )

            preview = page.get_by_role("link", name="Synthetic Preview Applicant")
            expect(preview).to_be_visible()
            assert preview.get_attribute("href") == (
                "/internal/applicant-previews/a7000000-0000-4000-8000-000000000001"
            )

            page.get_by_role("button", name="Inspect changes").click()

            expect(page.get_by_text("PhD — 2020-01-15", exact=False)).to_be_visible()
            expect(page.get_by_text("10.1000/one", exact=False)).to_be_visible()
            assert "[object Object]" not in page.locator("main").inner_text()

            returned: list[dict[str, object]] = []
            page.route(
                "**/api/internal/applicant-submissions/confirmation-1/return-for-correction",
                lambda route: (
                    returned.append(route.request.post_data_json),
                    route.fulfill(json={"status": "REJECTED"}),
                )[-1],
            )
            answers = iter(
                ["employment", "Please answer the clarified employment question."]
            )
            page.on("dialog", lambda dialog: dialog.accept(next(answers)))
            page.get_by_role("button", name="Return one section for correction").click()

            expect(page.get_by_text("Review decision recorded.")).to_be_visible()
            assert returned == [
                {
                    "section": "employment",
                    "reason": "Please answer the clarified employment question.",
                }
            ]
        finally:
            browser.close()
