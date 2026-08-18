from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_review_page_has_explicit_sections_confirmation_and_responsive_layout() -> None:
    """Break caught: review UI could hide fields, imply confirmation, or overflow."""
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import expect, sync_playwright

    html = (ROOT / "public" / "applicant" / "review.html").read_text(encoding="utf-8")
    html = html.replace("<head>", '<head><base href="https://localhost/applicant/">', 1)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - installation-specific
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            for width, height in ((1440, 900), (720, 900), (390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height})
                page.set_content(html, wait_until="domcontentloaded")
                page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
                page.add_script_tag(path=str(ROOT / "public" / "assets" / "applicant-review.js"))

                assert page.get_by_role("heading", name="Review your application").is_visible()
                assert page.get_by_role("button", name="Confirm this information").count() >= 1
                assert page.get_by_role("button", name="Correct information").count() >= 1
                assert page.get_by_role("button", name="Blue").is_visible()
                contribution_nav = page.get_by_role("button", name="Scientific contribution")
                contribution_nav.focus()
                page.keyboard.press("Enter")
                statement = page.get_by_label(
                    "What do you consider your most important contribution to scientific advance to date?"
                )
                assert statement.get_attribute("maxlength") == "1000"
                statement.fill("A short contribution")
                assert page.get_by_text("980 characters remaining", exact=True).is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                assert Axe().run(page).violations_count == 0
                page.close()
        finally:
            browser.close()


def test_review_page_prefills_imported_application_values() -> None:
    """Break caught: applicants could see blank fields instead of their imported record."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import expect, sync_playwright

    html = (ROOT / "public" / "applicant" / "review.html").read_text(encoding="utf-8")
    html = html.replace("<head>", '<head><base href="https://localhost/applicant/">', 1)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page()
            page.route(
                "**/api/applicant/review/*",
                lambda route: route.fulfill(json={"rowVersion": None, "values": {}, "confirmed": False}),
            )
            page.route(
                "**/api/applicant/application",
                lambda route: route.fulfill(json={"applicant": {"fullName": "Imported Applicant"}, "sections": {}, "documents": []}),
            )
            page.route(
                "**/api/applicant/review/fields",
                lambda route: route.fulfill(
                    json={"fields": [{"section": "identity", "code": "fullName", "label": "Full name", "kind": "text", "required": True}]}
                ),
            )
            page.set_content(html, wait_until="domcontentloaded")
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "applicant-review.js"))

            expect(page.get_by_label("Full name")).to_have_value("Imported Applicant")
        finally:
            browser.close()


def test_review_page_autosaves_changed_fields() -> None:
    """Break caught: changed applicant data could remain only in the browser until a button click."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import expect, sync_playwright

    html = (ROOT / "public" / "applicant" / "review.html").read_text(encoding="utf-8")
    html = html.replace("<head>", '<head><base href="https://localhost/applicant/">', 1)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page()
            console_messages: list[str] = []
            page.on("console", lambda message: console_messages.append(message.text))

            page.route(
                "**/api/applicant/review/*",
                lambda route: route.fulfill(
                    json={"rowVersion": 1, "values": {"fullName": "Imported Applicant"}, "confirmed": False}
                ),
            )
            page.route("**/api/applicant/application", lambda route: route.fulfill(json={"applicant": {"fullName": "Imported Applicant"}, "sections": {}, "documents": []}))
            page.route("**/api/applicant/review/fields", lambda route: route.fulfill(json={"fields": [
                {"section": "identity", "code": "fullName", "label": "Full name", "kind": "text", "required": True},
                {"section": "identity", "code": "telephone", "label": "Telephone number", "kind": "text", "required": True},
            ]}))
            page.set_content(html, wait_until="domcontentloaded")
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "applicant-review.js"))

            full_name = page.get_by_label("Full name")
            expect(full_name).to_have_value("Imported Applicant")
            full_name.fill("Changed Applicant")
            page.wait_for_timeout(1_200)
            assert page.locator('[data-section-status="identity"]').inner_text() == "Saved", console_messages
        finally:
            browser.close()


def test_simplified_form_uses_repeatable_degrees_conditional_scholar_and_doi_confirmation() -> None:
    """Break caught: the simplified controls could render as long flat inputs or save unconfirmed metadata."""
    pytest.importorskip("playwright.sync_api")
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import expect, sync_playwright

    html = (ROOT / "public" / "applicant" / "review.html").read_text(encoding="utf-8")
    html = html.replace("<head>", '<head><base href="https://localhost/applicant/">', 1)
    fields = [
        {"section": "identity", "code": "fullName", "label": "Full name", "kind": "text", "required": True},
        {"section": "identity", "code": "telephone", "label": "Telephone number", "kind": "text", "required": True},
        {"section": "identity", "code": "birthMonth", "label": "Birth month", "kind": "integer", "required": True},
        {"section": "identity", "code": "birthYear", "label": "Birth year", "kind": "integer", "required": True},
        {"section": "identity", "code": "gender", "label": "Gender (optional)", "kind": "choice", "options": ["Female", "Male", "Non-binary", "Prefer not to say"]},
        {"section": "employment", "code": "institute", "label": "Current UZH institute or department", "kind": "text", "required": True},
        {"section": "employment", "code": "principalInvestigator", "label": "Current principal investigator", "kind": "text", "required": True},
        {"section": "employment", "code": "positionTitle", "label": "Current position title", "kind": "text", "required": True},
        {"section": "employment", "code": "postdoctoralEmploymentStatus", "label": "Are you currently employed in a postdoctoral position?", "kind": "boolean", "required": True, "help": "Select Yes only if your present UZH appointment is a postdoctoral position."},
        {"section": "qualifications", "code": "degrees", "label": "Degrees", "kind": "degree_list", "required": True, "options": ["BSc", "MA", "MD", "PhD"]},
        {"section": "publications", "code": "hasGoogleScholarProfile", "label": "Do you have a public Google Scholar profile?", "kind": "boolean", "required": True},
        {"section": "publications", "code": "googleScholarProfileUrl", "label": "Google Scholar profile URL", "kind": "scholar_url"},
        {"section": "publications", "code": "publications", "label": "Publications by DOI", "kind": "publication_list"},
    ]
    saved_payloads: list[dict[str, object]] = []

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover
            pytest.skip(f"Pinned Playwright Chromium runtime unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})

            def api(route) -> None:
                request = route.request
                if request.url.endswith("/api/applicant/review/fields"):
                    route.fulfill(json={"fields": fields})
                elif request.url.endswith("/api/applicant/application"):
                    route.fulfill(json={"applicant": {"hasGoogleScholarProfile": False, "degrees": []}, "sections": {}, "documents": []})
                elif request.url.endswith("/api/applicant/review/publications/lookup"):
                    route.fulfill(json={"publication": {
                        "doi": "10.1000/example",
                        "title": "A synthetic publication",
                        "authors": ["Ada Lovelace"],
                        "journal": "Synthetic Journal",
                        "publicationDate": "2025-07-04",
                        "type": "journal-article",
                        "url": "https://doi.org/10.1000/example",
                        "lookupReceipt": "synthetic-application-bound-receipt",
                    }})
                elif request.method == "GET" and request.url.endswith("/api/applicant/review/employment"):
                    route.fulfill(json={
                        "rowVersion": 9,
                        "values": {"postdoctoralEmploymentStatus": None},
                        "confirmed": False,
                        "returnedForCorrection": {
                            "reason": "Please answer the clarified employment question.",
                            "returnedAtUtc": "2026-08-18T12:00:00Z",
                        },
                    })
                elif request.method == "PUT":
                    saved_payloads.append(request.post_data_json)
                    returned = (
                        {
                            "reason": "Please answer the clarified employment question.",
                            "returnedAtUtc": "2026-08-18T12:00:00Z",
                        }
                        if request.url.endswith("/api/applicant/review/employment")
                        else None
                    )
                    route.fulfill(json={
                        "saved": True,
                        "rowVersion": len(saved_payloads),
                        "values": request.post_data_json["values"],
                        "confirmed": False,
                        **({"returnedForCorrection": returned} if returned else {}),
                    })
                else:
                    route.fulfill(json={"rowVersion": None, "values": {}, "confirmed": False})

            page.route("**/api/applicant/**", api)
            page.set_content(html, wait_until="domcontentloaded")
            page.add_style_tag(path=str(ROOT / "public" / "assets" / "site.css"))
            page.add_script_tag(path=str(ROOT / "public" / "assets" / "applicant-review.js"))
            expect(page.get_by_label("Full name")).to_be_visible()

            identity_columns = page.locator('[data-generated-fields="identity"]').evaluate(
                "node => getComputedStyle(node).gridTemplateColumns.split(' ').length"
            )
            assert identity_columns >= 4
            assert page.get_by_label("Gender self-description").count() == 0

            page.get_by_role("button", name="UZH employment and eligibility").click(force=True)
            employment_columns = page.locator('[data-generated-fields="employment"]').evaluate(
                "node => getComputedStyle(node).gridTemplateColumns.split(' ').length"
            )
            assert employment_columns == 3
            expect(page.get_by_text("present UZH appointment", exact=False)).to_be_visible()
            expect(page.get_by_text("Please answer the clarified employment question.", exact=False)).to_be_visible()
            employment = page.locator('[data-review-section="employment"]')
            employment_confirm = employment.get_by_role("button", name="Confirm this information")
            expect(employment_confirm).to_be_disabled()
            page.get_by_label("Are you currently employed in a postdoctoral position?").select_option("false")
            expect(employment.get_by_text("Saved", exact=True)).to_be_visible()
            expect(employment_confirm).to_be_enabled()
            employment_confirm.click()
            expect(employment.get_by_text("Confirmed", exact=True)).to_be_visible()
            expect(employment.get_by_text("requested correction has been saved and confirmed", exact=False)).to_be_visible()

            page.get_by_role("button", name="Qualifications and academic age").click()
            page.get_by_role("button", name="Add degree").click()
            degree_row = page.locator("[data-degree-row]")
            expect(degree_row).to_have_count(1)
            degree_row.get_by_label("Degree type").select_option("PhD")
            degree_row.get_by_label("Date of conferral").fill("2019-05-20")

            page.get_by_role("button", name="Publications and identifiers").click()
            scholar_url = page.get_by_label("Google Scholar profile URL")
            expect(scholar_url).to_be_hidden()
            page.get_by_label("Do you have a public Google Scholar profile?").select_option("true")
            expect(scholar_url).to_be_visible()
            assert scholar_url.get_attribute("required") is not None
            assert scholar_url.get_attribute("aria-required") == "true"

            page.get_by_label("Publication DOI").fill("10.1000/example")
            page.get_by_role("button", name="Look up DOI").click()
            expect(page.get_by_text("A synthetic publication", exact=True)).to_be_visible()
            page.get_by_role("button", name="Confirm and add publication").click()
            expect(page.locator("[data-publication-row]")).to_have_count(1)
            expect(page.get_by_label("Publication DOI")).to_be_focused()
            page.wait_for_timeout(1_100)
            assert any(
                payload["values"].get("publications")
                == [{
                    "doi": "10.1000/example",
                    "confirmed": True,
                    "lookupReceipt": "synthetic-application-bound-receipt",
                }]
                for payload in saved_payloads
            )
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert Axe().run(page).violations_count == 0

            page.get_by_role("button", name="Remove publication").focus()
            page.get_by_role("button", name="Remove publication").press("Enter")
            expect(page.get_by_label("Publication DOI")).to_be_focused()
            expect(page.locator("[data-publication-row]")).to_have_count(0)

            page.set_viewport_size({"width": 721, "height": 900})
            page.get_by_role("button", name="Qualifications and academic age").evaluate(
                "button => button.click()"
            )
            assert page.locator("[data-degree-row]").evaluate(
                """row => {
                  const bounds = row.parentElement.parentElement.getBoundingClientRect();
                  return [...row.children].every(child => {
                    const item = child.getBoundingClientRect();
                    return item.left >= bounds.left && item.right <= bounds.right;
                  });
                }"""
            )
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="UZH employment and eligibility").click(force=True)
            mobile_columns = page.locator('[data-generated-fields="employment"]').evaluate(
                "node => getComputedStyle(node).gridTemplateColumns.split(' ').length"
            )
            assert mobile_columns == 1, mobile_columns
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert Axe().run(page).violations_count == 0

            page.get_by_role("button", name="Qualifications and academic age").evaluate(
                "button => button.click()"
            )
            page.get_by_role("button", name="Remove degree").focus()
            page.get_by_role("button", name="Remove degree").press("Enter")
            expect(page.get_by_role("button", name="Add degree")).to_be_focused()
        finally:
            browser.close()
