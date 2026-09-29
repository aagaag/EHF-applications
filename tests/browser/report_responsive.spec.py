"""Responsive layout checks for the internal applicant report."""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("viewport", [(1366, 768), (1024, 768), (720, 900), (390, 844)])
def test_report_metrics_stay_aligned_and_records_reflow_without_page_overflow(viewport):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    from app.identity import AuthenticatedIdentity, Identity
    from app.internal_preview import PreviewApplicantMetric, render_internal_preview
    from app.navigation import INTERNAL_GROUPS

    principal = AuthenticatedIdentity(
        Identity("development:administrator", "preview@example.invalid", "Preview"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    html = render_internal_preview(
        principal,
        simulation=True,
        records=(
            PreviewApplicantMetric(
                applicant="Long Surname Example",
                age=40,
                academic_age=8,
                verified_citations=123,
                h_index=19,
            ),
        ),
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

            table = page.locator(".report-table")
            header = page.locator(".report-header")
            row = page.locator(".report-data-row").first
            assert table.count() == 1
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

            if viewport[0] > 720:
                assert header.is_visible()
                assert header.locator("[role='columnheader']").count() == 6
                assert row.locator(":scope > [role='cell']").count() == 6
                alignment = page.evaluate(
                    """() => {
                        const h = [...document.querySelectorAll('.report-header [role=columnheader]')];
                        const r = [...document.querySelector('.report-data-row').children]
                            .filter(node => node.matches('[role=cell]'));
                        return h.map((node, i) => Math.abs(
                            node.getBoundingClientRect().left - r[i].getBoundingClientRect().left
                        ));
                    }"""
                )
                assert max(alignment) < 2
            else:
                assert not header.is_visible()
                assert row.locator(":scope > [role='cell']").evaluate_all(
                    "nodes => nodes.every(node => getComputedStyle(node, '::before').content !== 'none')"
                )

            assert table.evaluate(
                "node => node.getBoundingClientRect().width / node.parentElement.getBoundingClientRect().width > .99"
            )
            assert page.locator(".site-main").evaluate(
                "node => { const body = getComputedStyle(document.body); const usable = document.body.clientWidth - parseFloat(body.paddingLeft) - parseFloat(body.paddingRight); return Math.abs(node.getBoundingClientRect().width / usable - .94) < .03; }"
            )
        finally:
            browser.close()


@pytest.mark.parametrize("viewport", [(1024, 768), (390, 844)])
def test_second_stage_history_spans_record_and_opens_without_overflow(viewport):
    pytest.importorskip("playwright.sync_api")
    from datetime import UTC, datetime
    from uuid import UUID

    from playwright.sync_api import sync_playwright

    from app.calls import CallContext
    from app.identity import AuthenticatedIdentity, Identity
    from app.internal_preview import PreviewApplicantMetric, render_internal_preview
    from app.navigation import INTERNAL_GROUPS
    from app.second_stage import SecondStageState
    from app.shortlist import ShortlistState

    application_id = str(UUID(int=101))
    principal = AuthenticatedIdentity(
        Identity("development:administrator", "preview@example.invalid", "Preview"),
        frozenset({INTERNAL_GROUPS.administrators}),
    )
    current_call = CallContext(
        UUID(int=3), "EHF-2026", "ehf-2026", "EHF Fellowships", "EHF 2026",
        "CLOSED", "CLOSED", "OPEN", False, "ehf-standard-v1",
        datetime(2026, 1, 1, tzinfo=UTC), None, b"12345678",
    )
    html = render_internal_preview(
        principal,
        records=(PreviewApplicantMetric("Long Surname Example", academic_age=10,
                                        verified_citations=20, application_id=application_id),),
        current_call=current_call,
        shortlist=ShortlistState({application_id.casefold(): {"ricky": "B"}}, "adriano"),
        second_stage=SecondStageState(frozenset({application_id})),
        stage_two=True,
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
            assert page.locator(".report-table[data-selection-stage='second']").count() == 1
            assert page.locator(".report-review-strip, [data-advancement-checkbox], [data-shortlist-grade]").count() == 0
            assert page.locator(".report-shortlist-history").count() == 1
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

            history = page.locator(".report-shortlist-history")
            row = page.locator(".report-data-row")
            bounds = page.evaluate(
                """() => {
                    const history = document.querySelector('.report-shortlist-history').getBoundingClientRect();
                    const rowNode = document.querySelector('.report-data-row');
                    const row = rowNode.getBoundingClientRect();
                    const style = getComputedStyle(rowNode);
                    return {historyLeft: history.left, historyRight: history.right,
                            rowLeft: row.left + parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft),
                            rowRight: row.right - parseFloat(style.borderRightWidth) - parseFloat(style.paddingRight)};
                }"""
            )
            assert abs(bounds["historyLeft"] - bounds["rowLeft"]) < 2
            assert abs(bounds["historyRight"] - bounds["rowRight"]) < 2
            history.locator("summary").click()
            assert history.locator("ul").is_visible()
            assert "Ricky: B" in history.inner_text()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        finally:
            browser.close()
