from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


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
                        ]
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
