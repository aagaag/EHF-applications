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
                lambda route: route.fulfill(
                    json={
                        "submissions": [
                            {
                                "submissionId": "submission-1",
                                "applicationId": "a7000000-0000-4000-8000-000000000001",
                                "slotId": "a8000000-0000-4000-8000-000000000001",
                                "versionId": "a9000000-0000-4000-8000-000000000001",
                                "displayName": "Curriculum vitae",
                                "submittedAtUtc": "2026-08-18T10:00:00Z",
                                "status": "PENDING",
                            }
                        ]
                    }
                ),
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
            submitted_pdf = page.get_by_role("link", name="View submitted PDF")
            expect(submitted_pdf).to_have_attribute(
                "href",
                "/api/internal/applicants/a7000000-0000-4000-8000-000000000001/documents/a9000000-0000-4000-8000-000000000001/view",
            )
            expect(submitted_pdf).to_have_attribute("target", "_blank")

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
            page.get_by_role("button", name="Return one section for correction").click()
            review_dialog = page.get_by_role("dialog", name="Return section for correction")
            expect(review_dialog).to_be_visible()
            review_dialog.get_by_label("Application section").select_option("employment")
            review_dialog.get_by_label("Correction requested").fill(
                "Please answer the clarified employment question."
            )
            review_dialog.get_by_role("button", name="Return for correction").click()

            expect(page.get_by_text("Review decision recorded.")).to_be_visible()
            assert returned == [
                {
                    "section": "employment",
                    "reason": "Please answer the clarified employment question.",
                }
            ]
        finally:
            browser.close()


def test_applicant_list_filters_persist_in_url_and_detail_back_link() -> None:
    """Break caught: reviewers lost their list context after opening an applicant."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import expect, sync_playwright

    html = (ROOT / "public" / "internal" / "applicant-review.html").read_text(
        encoding="utf-8"
    )
    for script in (
        '<script src="/assets/theme.js"></script>',
        '<script src="/assets/shell.js"></script>',
        '<script src="/assets/internal-applicant-review.js"></script>',
    ):
        html = html.replace(script, "")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.route(
                "https://localhost/internal/applicant-previews*",
                lambda route: route.fulfill(body=html, content_type="text/html"),
            )
            for endpoint, payload in (
                ("applicant-access-requests", {"requests": []}),
                (
                    "applicant-submissions",
                    {"capabilities": {"returnForCorrection": True}, "submissions": []},
                ),
                ("applicant-document-submissions", {"submissions": []}),
            ):
                page.route(
                    f"**/api/internal/{endpoint}",
                    lambda route, _request, response=payload: route.fulfill(json=response),
                )
            page.route(
                "**/api/internal/applicant-previews",
                lambda route: route.fulfill(
                    json={
                        "applications": [
                            {
                                "applicationId": "a7000000-0000-4000-8000-000000000001",
                                "applicantName": "Ada Applicant",
                                "applicationStatus": "SUBMITTED",
                                "href": "/internal/applicant-previews/a7000000-0000-4000-8000-000000000001",
                            },
                            {
                                "applicationId": "b7000000-0000-4000-8000-000000000001",
                                "applicantName": "Ben Applicant",
                                "applicationStatus": "IMPORTED",
                                "href": "/internal/applicant-previews/b7000000-0000-4000-8000-000000000001",
                            },
                        ]
                    }
                ),
            )
            page.goto("https://localhost/internal/applicant-previews")
            page.add_script_tag(
                path=str(ROOT / "public" / "assets" / "internal-applicant-review.js")
            )

            page.get_by_label("Search applicants").fill("Ada")
            page.get_by_label("Application status").select_option("SUBMITTED")

            expect(page.get_by_role("link", name="Ada Applicant")).to_be_visible()
            expect(page.get_by_role("link", name="Ben Applicant")).to_be_hidden()
            assert "q=Ada" in page.url
            assert "status=SUBMITTED" in page.url
            ada_href = page.get_by_role("link", name="Ada Applicant").get_attribute("href")
            assert ada_href is not None
            assert ada_href.startswith(
                "/internal/applicant-previews/a7000000-0000-4000-8000-000000000001?return="
            )
            assert "%2Finternal%2Fapplicant-previews%3Fq%3DAda%26status%3DSUBMITTED" in ada_href
        finally:
            browser.close()


def test_review_dialog_keeps_entered_values_and_exposes_submission_errors() -> None:
    """A failed review action must remain recoverable inside the open dialog."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(
                """
                <main>
                  <div data-access-queue></div>
                  <div data-change-queue></div>
                  <div data-document-queue>
                    <button type="button" data-action="document-reject" data-value="submission-1">Reject document</button>
                  </div>
                  <p data-review-status role="status" aria-live="polite"></p>
                  <dialog aria-labelledby="review-dialog-title" data-review-dialog>
                    <form data-review-dialog-form>
                      <h2 id="review-dialog-title" data-review-dialog-title>Review action</h2>
                      <div data-review-dialog-fields></div>
                      <button type="submit" data-review-dialog-submit>Continue</button>
                    </form>
                  </dialog>
                </main>
                """
            )
            page.route(
                "**/api/internal/applicant-access-requests",
                lambda route: route.fulfill(json={"requests": []}),
            )
            page.route(
                "**/api/internal/applicant-submissions",
                lambda route: route.fulfill(json={"submissions": []}),
            )
            page.route(
                "**/api/internal/applicant-document-submissions",
                lambda route: route.fulfill(json={"submissions": []}),
            )
            page.route(
                "**/api/internal/applicant-document-submissions/submission-1/reject",
                lambda route: route.fulfill(status=500),
            )
            page.add_script_tag(
                path=str(ROOT / "public" / "assets" / "internal-applicant-review.js")
            )

            page.get_by_role("button", name="Reject document").click()
            dialog = page.get_by_role("dialog", name="Reject submitted document")
            expect(dialog.locator("[data-review-dialog-error]")).to_be_hidden()
            reason = dialog.get_by_label("Reason for rejection")
            reason.fill("The uploaded file is unreadable.")
            dialog.get_by_role("button", name="Reject document").click()

            expect(dialog).to_be_visible()
            expect(dialog.get_by_role("alert")).to_have_text(
                "The review decision could not be recorded. Please check the entered values and try again."
            )
            expect(reason).to_have_value("The uploaded file is unreadable.")
            expect(dialog.get_by_role("button", name="Reject document")).to_be_enabled()
        finally:
            browser.close()
