"""Server rendering for the protected, inspectable internal shell."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from textwrap import wrap

from app.citation_plots import CitationPlotPoint, citation_plot_points
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
        '<h2 id="reports-heading">Reports</h2><p>Source citation counts plotted against the age observations in the 2026 register. The graph uses total citations where recorded and otherwise the Google Scholar count.</p><p class="report-interaction-hint">Use the triangles beside any field title to sort ascending or descending. Double-click a row, or focus it and press Enter, to view all details.</p></div>'
        '<div class="report-actions"><label class="report-filter" for="report-applicant-filter">Filter applicants'
        '<select id="report-applicant-filter" data-report-filter>'
        '<option value="" selected disabled>Select application status</option>'
        '<option value="completed">Completed applications</option>'
        '<option value="missing">Applications where anything is missing</option>'
        '</select></label><a class="report-download" href="/internal/reports/metrics.xlsx">Download Excel</a></div>'
        f'{_report_table(records)}'
        '<div class="report-grid">'
        f'{_scatterplot(records, "Citations by anagraphic age", "age")}'
        f'{_scatterplot(records, "Citations by academic age", "academic_age")}'
        "</div></section>"
    )


def _report_table(records: tuple[PreviewApplicantMetric, ...]) -> str:
    headers = (
        ("Applicant", "text"), ("Degree", "text"), ("Age", "number"),
        ("Academic age (years)", "number"), ("Gender", "text"),
        ("First-author papers", "number"), ("Last-author papers", "number"),
        ("Total papers", "number"), ("h-index", "number"),
        ("Total citations", "number"), ("ORCID", "text"),
        ("Google Scholar citations", "number"), ("GS identity certainty", "text"),
    )
    labels = tuple(label for label, _kind in headers)
    header = "".join(
        _report_header(index, label, kind)
        for index, (label, kind) in enumerate(headers)
    )
    rows = "".join(_report_row(record, labels) for record in records)
    empty = (
        '<p class="report-empty" role="status">No application metrics are available.</p>'
        if not records else ""
    )
    return (
        '<div class="report-table" role="table" aria-label="2026 applicant metrics">'
        f'<div class="report-header" role="row">{header}</div>'
        f'<div class="report-data" role="rowgroup">{rows}</div></div>{empty}'
        '<p class="report-filter-empty" data-report-filter-empty role="status" hidden>No applications match the selected filter.</p>'
        '<dialog class="report-details-modal" data-report-modal aria-labelledby="report-details-title" aria-modal="true">'
        '<div class="report-details-panel"><div class="report-details-header">'
        '<h3 id="report-details-title" data-report-details-title>Application details</h3>'
        '<button type="button" class="report-details-close" data-report-modal-close aria-label="Close details">×</button>'
        '</div><p>All source observations for this application.</p>'
        '<dl class="report-details-list" data-report-details></dl></div></dialog>'
    )


def _report_header(index: int, label: str, kind: str) -> str:
    escaped_label = escape(label)
    buttons = "".join(
        f'<button type="button" class="report-sort-button" data-report-sort '
        f'data-report-sort-index="{index}" data-report-sort-kind="{kind}" '
        f'data-report-sort-direction="{direction}" aria-label="Sort {escaped_label} {direction}" '
        f'aria-pressed="false"><span aria-hidden="true">{triangle}</span></button>'
        for direction, triangle in (("ascending", "▲"), ("descending", "▼"))
    )
    return (
        f'<span role="columnheader" data-report-column="{escaped_label}">'
        f'<span class="report-column-label">{escaped_label}</span>'
        f'<span class="report-sort-buttons">{buttons}</span></span>'
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
    status = "missing" if any(value in (None, "") for value in values) else "completed"
    return (
        f'<div class="report-data-row" role="row" data-report-row tabindex="0" data-report-status="{status}" '
        f'aria-label="Open full details for {escape(record.applicant)}">{cells}</div>'
    )


def _scatterplot(
    records: tuple[PreviewApplicantMetric, ...], title: str, age_field: str
) -> str:
    points = citation_plot_points(records, age_field)
    if not points:
        plot = '<p class="report-empty">Not enough complete values to draw this report.</p>'
    else:
        xs = tuple(point.age for point in points)
        ys = tuple(point.citations for point in points)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = 0.0, max(ys) or 1.0
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        positioned = tuple(
            (
                point,
                120 + ((point.age - min_x) / span_x) * 360,
                330 - ((point.citations - min_y) / span_y) * 300,
            )
            for point in points
        )
        circles = "".join(
            _plot_point(point, x, y) for point, x, y in positioned
        )
        plot = (
            f'<svg viewBox="0 0 600 400" role="img" aria-label="{escape(title)}; {len(points)} candidates">'
            '<path class="plot-axis" d="M120 30V330H480" />'
            f'{circles}{_plot_callouts(positioned)}'
            '<text x="300" y="386">Age (years)</text>'
            '<text x="18" y="180" transform="rotate(-90 18 180)">Total citations</text></svg>'
        )
    return f'<article class="report-card"><h3>{escape(title)}</h3>{plot}</article>'


def _plot_point(point: CitationPlotPoint, x: float, y: float) -> str:
    description = (
        f"{point.applicant}: age {_number(point.age)}, "
        f"{int(point.citations):,} citations"
    )
    escaped_description = escape(description)
    return (
        f'<circle class="plot-point" tabindex="0" '
        f'aria-label="{escaped_description}" cx="{x:.1f}" cy="{y:.1f}" r="6" '
        f'fill="{point.color}"><title>{escaped_description}</title></circle>'
    )


def _plot_callouts(
    positioned: tuple[tuple[CitationPlotPoint, float, float], ...]
) -> str:
    labelled = sorted(
        (position for position in positioned if position[0].labelled),
        key=lambda position: (position[1], position[2], position[0].source_index),
    )
    split_at = (len(labelled) + 1) // 2
    sides = (("left", labelled[:split_at]), ("right", labelled[split_at:]))
    callouts: list[str] = []
    for side, side_points in sides:
        ordered = sorted(
            side_points, key=lambda position: (position[2], position[0].source_index)
        )
        for slot, (point, x, y) in enumerate(ordered):
            label_y = _callout_y(slot, len(ordered))
            if side == "left":
                path = f"M{x:.1f} {y:.1f} L116 {y:.1f} L112 {label_y:.1f}"
                label_x = 106
            else:
                path = f"M{x:.1f} {y:.1f} L484 {y:.1f} L488 {label_y:.1f}"
                label_x = 494
            callouts.append(
                f'<g class="plot-callout"><path class="plot-callout-halo" '
                f'd="{path}" /><path class="plot-callout-line" '
                f'stroke="{point.color}" d="{path}" />'
                f'{_plot_callout_label(point.surname, side, label_x, label_y)}</g>'
            )
    return "".join(callouts)


def _plot_callout_label(surname: str, side: str, x: int, y: float) -> str:
    lines = wrap(
        surname,
        width=16,
        break_long_words=True,
        break_on_hyphens=True,
    ) or ["Applicant"]
    attributes = (
        f'class="plot-callout-label" data-side="{side}" '
        f'x="{x}" y="{y:.1f}" aria-label="{escape(surname)}"'
    )
    if len(lines) == 1:
        line = lines[0]
        width = min(100.0, max(8.0, len(line) * 7.2))
        return (
            f'<text {attributes} textLength="{width:.1f}" '
            f'lengthAdjust="spacingAndGlyphs">{escape(line)}</text>'
        )
    offset = -((len(lines) - 1) * 6.5)
    tspans = "".join(
        f'<tspan x="{x}" y="{y + offset + index * 13:.1f}" '
        f'textLength="{min(100.0, max(8.0, len(line) * 7.2)):.1f}" '
        f'lengthAdjust="spacingAndGlyphs">{escape(line)}</tspan>'
        for index, line in enumerate(lines)
    )
    return f'<text {attributes}>{tspans}</text>'


def _callout_y(slot: int, total: int) -> float:
    return 180.0 if total <= 1 else 42.0 + slot * (276.0 / (total - 1))


def _display_markup(value: object | None) -> str:
    if value in (None, ""):
        return '<strong class="missing-value">Missing</strong>'
    return escape(str(value))


def _number(value: float | int | None) -> str | None:
    if value is None:
        return None
    numeric = float(value)
    return str(int(numeric)) if numeric.is_integer() else f"{numeric:.1f}"


def _authorization_pills(groups: tuple[str, ...]) -> str:
    pills = "".join(
        f'<span class="app-nav-authorization-pill group-pill-{index}">{escape(group)}</span>'
        for index, group in enumerate(groups, start=1)
    )
    return '<div class="app-nav-authorizations" aria-label="Groups authorized to use EHF Fellowships"><strong>Authorizations:</strong><span class="app-nav-authorization-pills">' + pills + "</span></div>"


def _appearance_controls() -> str:
    return """<div class="appearance-controls"><div class="appearance-control-row"><button type="button" data-skin-choice="default" aria-pressed="true">Production default</button><button type="button" data-skin-choice="high-contrast" aria-pressed="false">High contrast</button><button type="button" data-skin-choice="soft-earth" aria-pressed="false">Soft green/brown</button><button type="button" data-skin-choice="blue" aria-pressed="false">Blue</button></div><div class="appearance-control-row"><button type="button" data-appearance-flag="invert" aria-pressed="false">Invert colours</button><button type="button" data-appearance-flag="compact" aria-pressed="false">Compact spacing</button><button type="button" data-appearance-flag="reduceMotion" aria-pressed="false">Reduce motion</button></div></div>"""
