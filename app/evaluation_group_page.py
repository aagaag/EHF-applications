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
<title>{escape(call.display_name)} · Evaluation groups</title>
<style>{_STYLES}</style></head><body><main class="page">
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


_STYLES = """
:root{color-scheme:light;--ink:#17202a;--muted:#5a6875;--line:#dbe2e8;--panel:#fff;--accent:#1d5d7a;--soft:#f4f7f9}
*{box-sizing:border-box}body{margin:0;background:var(--soft);color:var(--ink);font:16px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}.page{width:min(1100px,94vw);margin:0 auto;padding:2rem 0 4rem}.page-header{display:flex;justify-content:space-between;gap:1.5rem;align-items:flex-start;margin-bottom:1.5rem}.eyebrow{color:var(--accent);font-weight:700;letter-spacing:.08em;margin:0;text-transform:uppercase}.page-header h1{font-size:clamp(1.6rem,3vw,2.3rem);margin:.2rem 0}.page-header p{color:var(--muted);margin:.2rem 0}.page-header nav{display:flex;gap:.6rem;flex-wrap:wrap;justify-content:flex-end}.button{background:var(--accent);border-radius:.45rem;color:#fff;display:inline-block;font-weight:650;padding:.65rem .85rem;text-decoration:none}.button.secondary{background:#fff;border:1px solid var(--line);color:var(--accent)}.groups{display:grid;gap:1rem}.group-section{background:var(--panel);border:1px solid var(--line);border-radius:.7rem;overflow:hidden}.group-section h2{background:#edf3f6;border-bottom:1px solid var(--line);font-size:1.05rem;margin:0;padding:.75rem 1rem}.section-count{color:var(--muted);font-size:.9em;font-weight:500}.applicant-list{list-style:none;margin:0;padding:0}.applicant{display:grid;grid-template-columns:minmax(12rem,1fr) minmax(0,2fr);gap:1rem;padding:.8rem 1rem;border-bottom:1px solid var(--line)}.applicant:last-child{border-bottom:0}.applicant-identity{display:flex;flex-direction:column;min-width:0}.applicant-identity strong{overflow-wrap:anywhere}.applicant-identity span,.muted,.empty{color:var(--muted)}.review-grades{display:flex;gap:.6rem;flex-wrap:wrap}.review-grade{align-items:center;background:#f7fafb;border:1px solid var(--line);border-radius:.35rem;display:flex;gap:.45rem;padding:.3rem .5rem;min-width:8.5rem;justify-content:space-between}.review-grade span{overflow-wrap:anywhere}.review-grade strong{color:var(--accent)}.empty,.notice{margin:0;padding:.8rem 1rem}.notice{background:#fff3cd;border:1px solid #e6ce80;border-radius:.5rem;margin-bottom:1rem}@media(max-width:700px){.page{width:min(100% - 1.2rem,1100px);padding-top:1.2rem}.page-header{flex-direction:column}.page-header nav{justify-content:flex-start}.applicant{grid-template-columns:1fr;gap:.5rem}.review-grade{min-width:0;flex:1 1 9rem}}
"""
