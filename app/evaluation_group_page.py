"""Standalone HTML for an authenticated call's grouped evaluations."""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from app.calls import CallContext
from app.evaluation_groups import BUCKET_ORDER, EvaluationApplicant, EvaluationGroups


def render_evaluation_group_page(
    call: CallContext,
    groups: EvaluationGroups,
    roster: Sequence[tuple[str, str]],
) -> str:
    reviewers = tuple(roster)
    sections = [
        _group_section(key, groups.buckets.get(key, ()), reviewers)
        for key in BUCKET_ORDER
    ]
    sections.append(_group_section("discrepancy", groups.strong_discrepancy, reviewers, "Strong discrepancy"))
    sections.append(_group_section("awaiting", groups.awaiting_reviews, reviewers, "Awaiting reviews"))
    reviewer_notice = "" if reviewers else '<p class="notice" role="status">Reviewers not configured</p>'
    download = f'/internal/calls/{escape(call.public_slug, quote=True)}/evaluations.docx'
    overview = f'/internal/calls/{escape(call.public_slug, quote=True)}/'
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(call.display_name)} · Evaluation groups</title><link rel="stylesheet" href="/assets/site.css"></head><body class="evaluation-groups-page"><main class="page">
<header class="page-header"><div><p class="eyebrow">{escape(call.call_code)}</p><h1>{escape(call.display_name)}</h1><p>Authenticated evaluation overview</p></div>
<nav aria-label="Page actions"><a class="button secondary" href="{overview}">Back to call overview</a><a class="button" href="{download}">Download Word report</a></nav></header>
{reviewer_notice}<div class="groups">{"".join(sections)}</div></main></body></html>'''


def _group_section(
    key: str,
    applicants: Sequence[EvaluationApplicant],
    reviewers: Sequence[tuple[str, str]],
    label: str | None = None,
) -> str:
    title = label or key
    heading_id = f"group-{key}-heading"
    rows = "".join(_applicant_card(applicant, reviewers) for applicant in applicants)
    empty = '<p class="empty">No applicants</p>' if not rows else f'<ul class="applicant-list">{rows}</ul>'
    return f'<section class="group-section" aria-labelledby="{heading_id}"><h2 id="{heading_id}">{escape(title)} <span class="section-count">({len(applicants)})</span></h2>{empty}</section>'


def _applicant_card(applicant: EvaluationApplicant, reviewers: Sequence[tuple[str, str]]) -> str:
    grades = "".join(
        f'<span class="review-grade"><span>{escape(display_name)}</span><strong>{escape(applicant.grades.get(key) or "Awaiting")}</strong>'
        + (f'<details class="review-comment"><summary>Comment</summary><p>{escape(applicant.comments[key])}</p></details>' if applicant.comments.get(key) else "")
        + '</span>'
        for key, display_name in reviewers
    )
    return f'<li class="applicant"><div class="applicant-identity"><strong>{escape(applicant.name)}</strong><span>{escape(applicant.number)}</span></div><div class="review-grades" aria-label="Reviewer grades">{grades or "<span class=\"muted\">No reviewers configured</span>"}</div></li>'
