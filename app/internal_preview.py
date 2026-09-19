"""Server rendering for the protected, inspectable internal shell."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from math import ceil, floor, isfinite, log10

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
    verified_citations: int | None = None
    verified_citation_source: str | None = None
    verified_citation_profile_url: str | None = None

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
        '<h2 id="reports-heading">Reports</h2><p>Source citation counts plotted against the age observations in the 2026 register. Source-attributed profile totals take precedence; applicant-reported and historic Google Scholar values remain visible for comparison.</p><p class="report-interaction-hint">Use the triangles beside any field title to sort ascending or descending. Double-click a row, or focus it and press Enter, to view all details.</p></div>'
        '<div class="report-actions"><label class="report-filter" for="report-applicant-filter">Filter applicants'
        '<select id="report-applicant-filter" data-report-filter>'
        '<option value="" selected disabled>Select application status</option>'
        '<option value="completed">Completed applications</option>'
        '<option value="missing">Applications where anything is missing</option>'
        '</select></label><a class="report-download" href="/internal/reports/metrics.xlsx">Download Excel</a></div>'
        f'{_report_table(records)}'
        '<div class="report-grid">'
        f'{_scatterplot(records, "Citations by anagraphic age", "age", "Anagraphic age")}'
        f'{_scatterplot(records, "Citations by academic age", "academic_age", "Academic age")}'
        f'{_age_comparison_plot(records)}'
        "</div></section>"
    )


def _report_table(records: tuple[PreviewApplicantMetric, ...]) -> str:
    headers = (
        ("Applicant", "text"), ("Degree", "text"), ("Age", "number"),
        ("Academic age (years)", "number"), ("Gender", "text"),
        ("First-author papers", "number"), ("Last-author papers", "number"),
        ("Total papers", "number"), ("h-index", "number"),
        ("Verified citations", "number"), ("Citation source", "text"),
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
        record.total_papers, record.h_index, record.verified_citations,
        _profile_source_markup(record), record.total_citations, record.orcid,
        record.google_scholar_citations, record.identity_certainty,
    )
    cells = "".join(
        f'<span role="cell" data-label="{escape(label)}">'
        f'{value if label == "Citation source" else _display_markup(value)}</span>'
        for label, value in zip(headers, values, strict=True)
    )
    status = "missing" if any(value in (None, "") for value in values) else "completed"
    return (
        f'<div class="report-data-row" role="row" data-report-row tabindex="0" data-report-status="{status}" '
        f'aria-label="Open full details for {escape(record.applicant)}">{cells}</div>'
    )


def _profile_source_markup(record: PreviewApplicantMetric) -> str:
    source = record.verified_citation_source
    profile_url = record.verified_citation_profile_url
    if source in (None, ""):
        return _display_markup(None)
    if profile_url and profile_url.startswith("https://"):
        return f'<a href="{escape(profile_url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(source)}</a>'
    return escape(source)


def _scatterplot(
    records: tuple[PreviewApplicantMetric, ...],
    title: str,
    age_field: str,
    age_label: str,
) -> str:
    points = citation_plot_points(records, age_field)
    if not points:
        plot = '<p class="report-empty">Not enough complete values to draw this report.</p>'
    else:
        plot = _value_plot(
            title,
            tuple(
                (point, point.age, point.citations, point.citations)
                for point in points
            ),
            x_label=f"{age_label} (years)",
            y_label="Total citations",
        )
    return f'<article class="report-card"><h3>{escape(title)}</h3>{plot}</article>'


def _age_comparison_plot(records: tuple[PreviewApplicantMetric, ...]) -> str:
    citation_points = citation_plot_points(records, "age")
    points = tuple(
        (point, point.age, academic_age, point.citations)
        for point in citation_points
        if (academic_age := _finite_number(records[point.source_index].academic_age))
        is not None
    )
    title = "Academic age versus anagraphic age"
    if not points:
        plot = '<p class="report-empty">Not enough complete values to draw this report.</p>'
    else:
        plot = _value_plot(
            title,
            points,
            x_label="Anagraphic age (years)",
            y_label="Academic age (years)",
            bubbles=True,
        )
    return f'<article class="report-card"><h3>{title}</h3>{plot}</article>'


def _value_plot(
    title: str,
    points: tuple[tuple[CitationPlotPoint, float, float, float], ...],
    *,
    x_label: str,
    y_label: str,
    bubbles: bool = False,
) -> str:
    x_low, x_high, x_ticks = _axis_domain(tuple(point[1] for point in points))
    y_low, y_high, y_ticks = _axis_domain(
        tuple(point[2] for point in points), zero_based=not bubbles
    )
    largest_citation = max(point[3] for point in points) or 1.0
    positioned = tuple(
        (
            point,
            _plot_coordinate(point[1], x_low, x_high, 78.0, 558.0),
            _plot_coordinate(point[2], y_low, y_high, 344.0, 34.0),
        )
        for point in points
    )
    circles = "".join(
        _plot_point(
            point,
            x,
            y,
            x_value=x_value,
            y_value=y_value,
            bubble_radius=16.0 * (citations / largest_citation) ** 0.5 if bubbles else 6.0,
            bubbles=bubbles,
            x_label=x_label,
            y_label=y_label,
        )
        for (point, x_value, y_value, citations), x, y in positioned
    )
    return (
        f'<svg viewBox="0 0 640 410" role="img" aria-label="{escape(title)}; {len(points)} candidates">'
        f'{_plot_grid(x_ticks, y_ticks, x_low, x_high, y_low, y_high)}'
        '<path class="plot-axis" d="M78 34V344H558" />'
        f'{circles}{_plot_callouts(positioned, _callout_source_indices(points))}'
        f'<text class="plot-axis-label" x="318" y="398">{escape(x_label)}</text>'
        f'<text class="plot-axis-label" x="19" y="189" transform="rotate(-90 19 189)">{escape(y_label)}</text></svg>'
    )


def _axis_domain(
    values: tuple[float, ...], *, zero_based: bool = False
) -> tuple[float, float, tuple[float, ...]]:
    minimum = 0.0 if zero_based else min(values)
    maximum = max(values)
    if maximum == minimum:
        padding = max(abs(maximum) * 0.1, 1.0)
        minimum = 0.0 if zero_based else minimum - padding
        maximum += padding
    raw_step = (maximum - minimum) / 5.0
    magnitude = 10.0 ** floor(log10(raw_step))
    normalized = raw_step / magnitude
    multiplier = (
        1.0
        if normalized <= 1
        else 2.0
        if normalized <= 2
        else 5.0
        if normalized <= 5
        else 10.0
    )
    step = multiplier * magnitude
    lower = 0.0 if zero_based else floor(minimum / step) * step
    upper = ceil(maximum / step) * step
    ticks = tuple(
        lower + index * step
        for index in range(round((upper - lower) / step) + 1)
    )
    return lower, upper, ticks


def _plot_coordinate(
    value: float, lower: float, upper: float, start: float, end: float
) -> float:
    return start + ((value - lower) / (upper - lower)) * (end - start)


def _plot_grid(
    x_ticks: tuple[float, ...],
    y_ticks: tuple[float, ...],
    x_low: float,
    x_high: float,
    y_low: float,
    y_high: float,
) -> str:
    vertical = "".join(
        f'<path class="plot-gridline" d="M{x:.1f} 34V344" />'
        f'<text class="plot-tick-label" x="{x:.1f}" y="361">{_number(tick)}</text>'
        for tick in x_ticks
        if (x := _plot_coordinate(tick, x_low, x_high, 78.0, 558.0))
    )
    horizontal = "".join(
        f'<path class="plot-gridline" d="M78 {y:.1f}H558" />'
        f'<text class="plot-tick-label" x="68" y="{y + 4:.1f}">{_number(tick)}</text>'
        for tick in y_ticks
        if (y := _plot_coordinate(tick, y_low, y_high, 344.0, 34.0))
    )
    return f'<g aria-hidden="true">{vertical}{horizontal}</g>'


def _plot_point(
    point: CitationPlotPoint,
    x: float,
    y: float,
    *,
    x_value: float,
    y_value: float,
    bubble_radius: float,
    bubbles: bool,
    x_label: str,
    y_label: str,
) -> str:
    description = (
        f"{point.applicant}: {x_label.removesuffix(' (years)').casefold()} "
        f"{_number(x_value)}, {y_label.removesuffix(' (years)').casefold()} "
        f"{_number(y_value)}, {int(point.citations):,} citations"
    )
    if not bubbles:
        description = (
            f"{point.applicant}: {x_label.removesuffix(' (years)').casefold()} "
            f"{_number(x_value)}, {int(point.citations):,} citations"
        )
    escaped_description = escape(description)
    classes = "plot-point plot-bubble" if bubbles else "plot-point"
    return (
        f'<circle class="{classes}" tabindex="0" '
        f'aria-label="{escaped_description}" data-plot-x="{_number(x_value)}" '
        f'data-plot-y="{_number(y_value)}" data-citations="{_number(point.citations)}" '
        f'cx="{x:.1f}" cy="{y:.1f}" r="{bubble_radius:.1f}" '
        f'fill="{point.color}"><title>{escaped_description}</title></circle>'
    )


def _plot_callouts(
    positioned: tuple[
        tuple[tuple[CitationPlotPoint, float, float, float], float, float], ...
    ],
    callout_source_indices: frozenset[int],
) -> str:
    plotted_points = tuple((x, y) for _point, x, y in positioned)
    occupied: list[tuple[float, float, float, float]] = []
    callouts: list[str] = []
    labelled = sorted(
        (position for position in positioned if position[0][0].source_index in callout_source_indices),
        key=lambda position: (
            -position[0][3], position[0][0].applicant.casefold(), position[0][0].source_index
        ),
    )
    for (point, _x_value, _y_value, _citations), x, y in labelled:
        placement = _callout_placement(point.surname, x, y, plotted_points, occupied)
        if placement is None:
            continue
        side, label_x, label_y, rectangle = placement
        occupied.append(rectangle)
        path = f"M{x:.1f} {y:.1f} L{label_x:.1f} {label_y:.1f}"
        callouts.append(
            f'<g class="plot-callout"><path class="plot-callout-line" '
            f'stroke="{point.color}" d="{path}" />'
            f'{_plot_callout_label(point.surname, side, label_x, label_y)}</g>'
        )
    return "".join(callouts)


def _callout_source_indices(
    points: tuple[tuple[CitationPlotPoint, float, float, float], ...]
) -> frozenset[int]:
    ranked = sorted(
        points,
        key=lambda item: (-item[3], item[0].applicant.casefold(), item[0].source_index),
    )
    return frozenset(item[0].source_index for item in ranked[:15])


def _callout_placement(
    surname: str,
    point_x: float,
    point_y: float,
    plotted_points: tuple[tuple[float, float], ...],
    occupied: list[tuple[float, float, float, float]],
) -> tuple[str, float, float, tuple[float, float, float, float]] | None:
    label_width = _callout_label_width(surname)
    for distance in (14.0, 28.0, 42.0):
        for horizontal, vertical in ((1, -1), (1, 1), (-1, -1), (-1, 1), (0, -1), (0, 1)):
            side = "left" if horizontal < 0 else "right"
            label_x = point_x + horizontal * distance
            label_y = point_y + vertical * distance
            rectangle = _callout_rectangle(side, label_x, label_y, label_width)
            if not _callout_rectangle_is_clear(rectangle, plotted_points, occupied):
                continue
            return side, label_x, label_y, rectangle
    return None


def _callout_rectangle(
    side: str, x: float, y: float, width: float
) -> tuple[float, float, float, float]:
    left, right = (x - width, x) if side == "left" else (x, x + width)
    return left, y - 10.0, right, y + 2.0


def _callout_rectangle_is_clear(
    rectangle: tuple[float, float, float, float],
    plotted_points: tuple[tuple[float, float], ...],
    occupied: list[tuple[float, float, float, float]],
) -> bool:
    left, top, right, bottom = rectangle
    if left < 78.0 or right > 558.0 or top < 34.0 or bottom > 344.0:
        return False
    if any(_rectangles_overlap(rectangle, other) for other in occupied):
        return False
    return not any(
        max(left - x, 0.0, x - right) ** 2 + max(top - y, 0.0, y - bottom) ** 2 < 400.0
        for x, y in plotted_points
    )


def _rectangles_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return not (
        first[2] <= second[0]
        or second[2] <= first[0]
        or first[3] <= second[1]
        or second[3] <= first[1]
    )


def _plot_callout_label(surname: str, side: str, x: float, y: float) -> str:
    attributes = (
        f'class="plot-callout-label" data-side="{side}" '
        f'x="{x}" y="{y:.1f}" aria-label="{escape(surname)}"'
    )
    width = _callout_label_width(surname)
    return (
        f'<text {attributes} textLength="{width:.1f}" '
        f'lengthAdjust="spacingAndGlyphs">{escape(surname)}</text>'
    )


def _callout_label_width(surname: str) -> float:
    return min(88.0, max(10.0, len(surname) * 5.6))


def _finite_number(value: object | None) -> float | None:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


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
