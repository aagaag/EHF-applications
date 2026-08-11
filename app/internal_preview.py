"""Server rendering for the protected, inspectable internal shell."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from math import isfinite

from app.identity import AuthenticatedIdentity
from app.navigation import (
    NavigationEntry,
    authorization_groups,
    filtered_inventory,
    help_entries,
    navigation_entries,
)


@dataclass(frozen=True, slots=True)
class PreviewApplicantMetric:
    """Administrator-only source observations used by the development preview."""

    applicant: str
    degree: str | None = None
    age: float | None = None
    academic_age: float | None = None
    gender: str | None = None
    first_author_papers: int | None = None
    last_author_papers: int | None = None
    total_papers: int | None = None
    h_index: int | None = None
    total_citations: int | None = None
    orcid: str | None = None
    google_scholar_citations: int | None = None
    identity_certainty: str | None = None

def render_internal_preview(
    principal: AuthenticatedIdentity,
    *,
    simulation: bool = False,
    records: tuple[PreviewApplicantMetric, ...] = (),
) -> str:
    """Render every visible internal element from one group-filtered inventory."""
    entries = filtered_inventory(principal.groups)
    navigation = navigation_entries(entries)
    help_items = help_entries(entries)
    pills = authorization_groups(entries)
    notice = (
        "Sign-in is not active. This is a development-only administrator simulation."
        if simulation
        else "Secure sign-in is active through the configured identity boundary."
    )
    record_notice = (
        "Applicant source data is loaded for internal inspection. Documents remain unreviewed "
        "and applicant visibility is disabled."
        if records
        else "No application records are loaded."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>EHF Fellowships — internal preview</title><link rel="stylesheet" href="/assets/site.css"></head>
<body data-shell><a class="skip-link" href="#main-content">Skip to main content</a>
<button class="app-nav-toggle" type="button" aria-controls="application-navigation" aria-expanded="false" aria-label="Open application navigation"><span aria-hidden="true">☰</span> Menu</button><div class="app-nav-backdrop" hidden></div>
<aside class="app-nav" id="application-navigation" aria-label="Application navigation" data-open="false" inert>
<div class="app-nav-top"><a class="app-nav-home" href="/internal/"><img src="/assets/isab-logo.svg" alt="ISAB"><span class="app-nav-title">EHF Fellowships</span></a><span class="app-nav-domain">ehf.isab.science</span><span class="app-nav-purpose">A secure future workspace for the Ernst Hadorn Foundation.</span></div>
<div class="app-nav-scroll"><nav class="app-nav-list" aria-label="Primary navigation">{_navigation_links(navigation)}</nav></div>
<nav class="app-nav-list app-nav-lower" aria-label="Settings and help navigation"><span class="app-nav-heading">Settings</span><a class="app-nav-link" href="#appearance">Appearance</a><button class="app-nav-disclosure" type="button" data-disclosure aria-expanded="false" aria-controls="help-links">Help</button><div class="app-nav-submenu" id="help-links" hidden>{_help_links(help_items)}</div>{_authorization_pills(pills)}</nav></aside>
<main class="site-main" id="main-content" tabindex="-1"><header class="site-hero" id="overview"><h1>Charles Weissmann Fellowships</h1><p>Internal workspace preview for the Ernst Hadorn Foundation.</p></header>
<div class="preview-notice" role="status">Preview only<span>{escape(notice)} Submission is not active. Communication sending is not active. {escape(record_notice)}</span></div>
<section aria-labelledby="workspaces-heading"><div class="section-heading"><h2 id="workspaces-heading">Workspaces</h2><p>The current application register is available below for administrator inspection.</p></div><div class="shell-grid">{_cards(entries)}</div></section>
{_report_section(records)}{_sections(entries, exclude=frozenset({"reports"}))}<section id="appearance" aria-labelledby="appearance-heading"><div class="section-heading"><h2 id="appearance-heading">Appearance preview</h2><p>Preferences load and save server-side only after secure sign-in is active.</p></div>{_appearance_controls()}</section></main>
<footer class="site-footer">EHF Fellowships · internal preview · Page last modified: <time data-last-modified></time></footer><script src="/assets/theme.js"></script><script src="/assets/shell.js"></script></body></html>"""


def _navigation_links(entries: tuple[NavigationEntry, ...]) -> str:
    return "".join(
        f'<a class="app-nav-link" href="{escape(entry.href)}">{escape(entry.label)}</a>'
        for entry in entries
    )


def _help_links(entries: tuple[NavigationEntry, ...]) -> str:
    return "".join(
        f'<a class="app-nav-link" href="{escape(entry.href)}">{escape(entry.label)} help</a>'
        for entry in entries
    )


def _cards(entries: tuple[NavigationEntry, ...]) -> str:
    return "".join(
        f'<a class="shell-card" href="{escape(entry.href)}"><strong>{escape(entry.label)}</strong><span>{escape(entry.help_text)}</span></a>'
        for entry in entries
    )


def _sections(
    entries: tuple[NavigationEntry, ...], *, exclude: frozenset[str] = frozenset()
) -> str:
    return "".join(
        f'<section id="{escape(entry.key)}" class="section-heading"><h2>{escape(entry.label)}</h2><p>{escape(entry.help_text)}</p></section>'
        for entry in entries
        if entry.key not in exclude
    )


def _report_section(records: tuple[PreviewApplicantMetric, ...]) -> str:
    return (
        '<section id="reports" aria-labelledby="reports-heading"><div class="section-heading">'
        '<h2 id="reports-heading">Reports</h2><p>Source citation counts plotted against the age observations in the 2026 register. The graph uses total citations where recorded and otherwise the Google Scholar count.</p><p class="report-interaction-hint">Double-click a row, or focus it and press Enter, to view all details.</p></div>'
        '<div class="report-actions"><a class="report-download" href="/internal/reports/metrics.xlsx">Download Excel</a></div>'
        f'{_report_table(records)}'
        '<div class="report-grid">'
        f'{_scatterplot(records, "Citations by anagraphic age", "age")}'
        f'{_scatterplot(records, "Citations by academic age", "academic_age")}'
        "</div></section>"
    )


def _report_table(records: tuple[PreviewApplicantMetric, ...]) -> str:
    headers = (
        "Applicant", "Degree", "Age", "Academic age (years)", "Gender",
        "First-author papers", "Last-author papers", "Total papers", "h-index",
        "Total citations", "ORCID", "Google Scholar citations", "GS identity certainty",
    )
    header = "".join(f'<span role="columnheader">{escape(label)}</span>' for label in headers)
    rows = "".join(_report_row(record, headers) for record in records)
    empty = (
        '<p class="report-empty" role="status">No application metrics are available.</p>'
        if not records else ""
    )
    return (
        '<div class="report-table" role="table" aria-label="2026 applicant metrics">'
        f'<div class="report-header" role="row">{header}</div>'
        f'<div class="report-data" role="rowgroup">{rows}</div></div>{empty}'
        '<dialog class="report-details-modal" data-report-modal aria-labelledby="report-details-title" aria-modal="true">'
        '<div class="report-details-panel"><div class="report-details-header">'
        '<h3 id="report-details-title" data-report-details-title>Application details</h3>'
        '<button type="button" class="report-details-close" data-report-modal-close aria-label="Close details">×</button>'
        '</div><p>All source observations for this application.</p>'
        '<dl class="report-details-list" data-report-details></dl></div></dialog>'
    )


def _report_row(record: PreviewApplicantMetric, headers: tuple[str, ...]) -> str:
    values = (
        record.applicant, record.degree, _number(record.age), _number(record.academic_age),
        record.gender, record.first_author_papers, record.last_author_papers,
        record.total_papers, record.h_index, record.total_citations, record.orcid,
        record.google_scholar_citations, record.identity_certainty,
    )
    cells = "".join(
        f'<span role="cell" data-label="{escape(label)}">{_display_markup(value)}</span>'
        for label, value in zip(headers, values, strict=True)
    )
    return (
        f'<div class="report-data-row" role="row" data-report-row tabindex="0" '
        f'aria-label="Open full details for {escape(record.applicant)}">{cells}</div>'
    )


def _scatterplot(
    records: tuple[PreviewApplicantMetric, ...], title: str, age_field: str
) -> str:
    points = [
        (float(getattr(record, age_field)), float(_citation_count(record)), record.applicant)
        for record in records
        if _finite(getattr(record, age_field)) and _finite(_citation_count(record))
    ]
    if not points:
        plot = '<p class="report-empty">Not enough complete values to draw this report.</p>'
    else:
        xs, ys = zip(*((point[0], point[1]) for point in points))
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = 0.0, max(ys) or 1.0
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        circles = "".join(
            f'<circle cx="{42 + ((x - min_x) / span_x) * 516:.1f}" cy="{256 - ((y - min_y) / span_y) * 218:.1f}" r="5"><title>{escape(name)}: age {_number(x)}, {int(y):,} citations</title></circle>'
            for x, y, name in points
        )
        plot = (
            f'<svg viewBox="0 0 600 300" role="img" aria-label="{escape(title)}; {len(points)} candidates">'
            '<path class="plot-axis" d="M42 26V256H570" />'
            f'{circles}<text x="306" y="290">Age (years)</text><text x="14" y="150" transform="rotate(-90 14 150)">Total citations</text></svg>'
        )
    return f'<article class="report-card"><h3>{escape(title)}</h3>{plot}</article>'


def _display_markup(value: object | None) -> str:
    if value in (None, ""):
        return '<strong class="missing-value">Missing</strong>'
    return escape(str(value))


def _number(value: float | int | None) -> str | None:
    if value is None:
        return None
    numeric = float(value)
    return str(int(numeric)) if numeric.is_integer() else f"{numeric:.1f}"


def _finite(value: object | None) -> bool:
    try:
        return value is not None and isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _citation_count(record: PreviewApplicantMetric) -> int | None:
    return (
        record.total_citations
        if record.total_citations is not None
        else record.google_scholar_citations
    )


def _authorization_pills(groups: tuple[str, ...]) -> str:
    pills = "".join(
        f'<span class="app-nav-authorization-pill group-pill-{index}">{escape(group)}</span>'
        for index, group in enumerate(groups, start=1)
    )
    return '<div class="app-nav-authorizations" aria-label="Groups authorized to use EHF Fellowships"><strong>Authorizations:</strong><span class="app-nav-authorization-pills">' + pills + "</span></div>"


def _appearance_controls() -> str:
    return """<div class="appearance-controls"><div class="appearance-control-row"><button type="button" data-skin-choice="default" aria-pressed="true">Production default</button><button type="button" data-skin-choice="high-contrast" aria-pressed="false">High contrast</button><button type="button" data-skin-choice="soft-earth" aria-pressed="false">Soft green/brown</button><button type="button" data-skin-choice="blue" aria-pressed="false">Blue</button></div><div class="appearance-control-row"><button type="button" data-appearance-flag="invert" aria-pressed="false">Invert colours</button><button type="button" data-appearance-flag="compact" aria-pressed="false">Compact spacing</button><button type="button" data-appearance-flag="reduceMotion" aria-pressed="false">Reduce motion</button></div></div>"""
