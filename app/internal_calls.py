"""Server-rendered call portfolio and selected-call workspace."""

from __future__ import annotations

from datetime import datetime
from html import escape

from app.calls import CallContext, CallSummary
from app.identity import AuthenticatedIdentity
from app.navigation import INTERNAL_GROUPS, authorization_groups, filtered_inventory
from app.preferences import CallNavigationPreference


def render_call_inventory(
    principal: AuthenticatedIdentity,
    summaries: tuple[CallSummary, ...],
    *,
    preference: CallNavigationPreference = CallNavigationPreference(),
) -> str:
    return _shell(
        principal,
        summaries,
        current_slug=None,
        title="Application rounds",
        preference=preference,
        body=(
            '<header class="site-hero call-page-heading"><div><h1>Application rounds</h1>'
            '<p>Select an authorized fellowship call or create a new draft call.</p></div></header>'
            f'<section class="call-card-grid" aria-label="Authorized application rounds">'
            f'{"".join(_call_card(summary) for summary in summaries)}'
            "</section>"
            + (_create_form() if INTERNAL_GROUPS.administrators in principal.groups else "")
        ),
    )


def render_call_workspace(
    principal: AuthenticatedIdentity,
    summaries: tuple[CallSummary, ...],
    current: CallContext,
    *,
    preference: CallNavigationPreference = CallNavigationPreference(),
) -> str:
    summary = next(
        (item for item in summaries if item.context.public_slug == current.public_slug), None
    )
    facts = _summary_facts(summary) if summary is not None else ""
    body = (
        '<header class="site-hero call-page-heading"><div>'
        f'<p class="call-code">{escape(current.call_code)}</p>'
        f'<h1>{escape(current.display_name)}</h1>'
        f'<p>Application deadline: {_format_date(current.application_deadline_utc)}</p>'
        '</div><a class="secondary-action" href="/internal/calls/">All rounds</a></header>'
        f'<section class="call-workspace-summary" aria-label="Current application round">{facts}</section>'
    )
    return _shell(
        principal,
        summaries,
        current_slug=current.public_slug,
        title=current.compact_title,
        preference=preference,
        body=body,
    )


def _shell(
    principal: AuthenticatedIdentity,
    summaries: tuple[CallSummary, ...],
    *,
    current_slug: str | None,
    title: str,
    body: str,
    preference: CallNavigationPreference,
) -> str:
    call_links = "".join(
        _call_navigation_link(summary.context, current_slug) for summary in summaries
    )
    groups = authorization_groups(filtered_inventory(principal.groups))
    pills = "".join(
        f'<span class="app-nav-authorization-pill group-pill-{index}">{escape(group)}</span>'
        for index, group in enumerate(groups, start=1)
    )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} — EHF Fellowships</title><link rel="stylesheet" href="/assets/site.css"></head>
<body data-shell><a class="skip-link" href="#main-content">Skip to main content</a>
<button class="app-nav-toggle" type="button" aria-controls="application-navigation" aria-expanded="false" aria-label="Open application navigation"><span aria-hidden="true">☰</span> Menu</button><div class="app-nav-backdrop" hidden></div>
<aside class="app-nav" id="application-navigation" aria-label="Application navigation" data-open="false" inert>
<div class="app-nav-top"><a class="app-nav-home" href="/internal/"><img src="/assets/ehf-logo.svg" alt="Ernst Hadorn Foundation"><span class="app-nav-title">EHF Fellowships</span></a><span class="app-nav-domain">ehf.isab.science</span><span class="app-nav-purpose">Fellowship application rounds and review workspaces.</span></div>
<div class="app-nav-scroll"><nav class="app-nav-list call-nav-list" aria-label="Application rounds"><span class="app-nav-heading">Application rounds</span><a class="app-nav-link" href="/internal/calls/">All rounds</a>{call_links}</nav></div>
<nav class="app-nav-list app-nav-lower" aria-label="Settings and help navigation"><span class="app-nav-heading">Settings</span>{_call_default_control(preference)}<a class="app-nav-link" href="/internal/calls/">Help</a><div class="app-nav-authorizations" aria-label="Groups authorized to use EHF Fellowships"><strong>Authorizations:</strong><span class="app-nav-authorization-pills">{pills}</span></div></nav></aside>
<main class="site-main call-page" id="main-content" tabindex="-1">{body}</main>
<footer class="site-footer">EHF Fellowships · <time data-last-modified></time></footer><script src="/assets/theme.js"></script><script src="/assets/shell.js"></script></body></html>'''


def _call_navigation_link(context: CallContext, current_slug: str | None) -> str:
    current = ' aria-current="page"' if context.public_slug == current_slug else ""
    return (
        f'<a class="app-nav-link call-nav-link" href="/internal/calls/{escape(context.public_slug)}/"{current}>'
        f'<span>{escape(context.compact_title)}</span><small>{escape(context.call_status.title())}</small></a>'
    )


def _call_card(summary: CallSummary) -> str:
    context = summary.context
    return (
        f'<a class="call-card" href="/internal/calls/{escape(context.public_slug)}/">'
        f'<span class="call-code">{escape(context.call_code)}</span>'
        f'<h2>{escape(context.display_name)}</h2>'
        f'<span>{summary.applicant_count} applicants</span>'
        f'<span>Deadline {_format_date(context.application_deadline_utc)}</span>'
        f'<span>Call {escape(context.call_status.title())}</span>'
        f'<span>Review {escape(context.applicant_review_status.title())}</span>'
        f'<span>Selection {escape(context.internal_selection_status.title())}</span>'
        '</a>'
    )


def _call_default_control(preference: CallNavigationPreference) -> str:
    options = (
        ("resume-last-opened", "Last round I used"),
        ("latest-application-deadline", "Latest application deadline"),
    )
    markup = "".join(
        f'<option value="{value}"{(" selected" if preference.mode == value else "")}>{label}</option>'
        for value, label in options
    )
    return (
        '<label class="call-default-setting">Default round'
        f'<select data-call-default-mode>{markup}</select></label>'
        '<span class="call-default-status" data-call-default-status aria-live="polite"></span>'
    )


def _summary_facts(summary: CallSummary) -> str:
    context = summary.context
    values = (
        ("Applicants", str(summary.applicant_count)),
        ("Call", context.call_status.title()),
        ("Applicant review", context.applicant_review_status.title()),
        ("Internal selection", context.internal_selection_status.title()),
        ("Invitations", "Disabled" if not context.invitations_enabled else "Enabled"),
        ("Shortlisters", str(summary.active_shortlister_count)),
        ("Roster", summary.roster_state.replace("_", " ").title()),
    )
    return "".join(
        f'<div class="call-fact"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in values
    )


def _create_form() -> str:
    return (
        '<section class="call-admin-panel" aria-labelledby="create-call-heading">'
        '<h2 id="create-call-heading">Create call</h2>'
        '<p>New rounds start as drafts with review, selection, and invitations disabled.</p>'
        '<form class="call-create-form" data-call-create><label>Code<input name="callCode" required maxlength="50"></label>'
        '<label>URL slug<input name="publicSlug" required maxlength="80" pattern="[a-z0-9]+(?:-[a-z0-9]+)*"></label>'
        '<label>Title<input name="displayName" required maxlength="200"></label>'
        '<label>Navigation title<input name="compactTitle" required maxlength="120"></label>'
        '<label>Application deadline<input name="applicationDeadlineUtc" type="datetime-local" required></label>'
        '<button class="primary-action" type="submit">Create draft call</button></form></section>'
    )


def _format_date(value: datetime) -> str:
    return value.strftime("%d %B %Y")
