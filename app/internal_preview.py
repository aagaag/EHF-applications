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
from app.shortlist import ShortlistState, editable_trustee


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
    validated_published_papers: int | None = None
    application_id: str | None = None
    application_number: str | None = None

def render_internal_preview(
    principal: AuthenticatedIdentity,
    *,
    simulation: bool = False,
    records: tuple[PreviewApplicantMetric, ...] = (),
    shortlist: ShortlistState | None = None,
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
    shortlist_state = shortlist or ShortlistState({}, editable_trustee(principal.entra_object_id))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>EHF Fellowships — internal preview</title><link rel="stylesheet" href="/assets/site.css"></head>
<body data-shell><a class="skip-link" href="#main-content">Skip to main content</a>
<button class="app-nav-toggle" type="button" aria-controls="application-navigation" aria-expanded="false" aria-label="Open application navigation"><span aria-hidden="true">☰</span> Menu</button><div class="app-nav-backdrop" hidden></div>
<aside class="app-nav" id="application-navigation" aria-label="Application navigation" data-open="false" inert>
<div class="app-nav-top"><a class="app-nav-home" href="/internal/"><img src="/assets/ehf-logo.svg" alt="Ernst Hadorn Foundation"><span class="app-nav-title">EHF Fellowships</span></a><span class="app-nav-domain">ehf.isab.science</span><span class="app-nav-purpose">A secure future workspace for the Ernst Hadorn Foundation.</span></div>
<div class="app-nav-scroll"><nav class="app-nav-list" aria-label="Primary navigation">{_navigation_links(navigation)}</nav></div>
<nav class="app-nav-list app-nav-lower" aria-label="Settings and help navigation"><span class="app-nav-heading">Settings</span><a class="app-nav-link" href="#appearance">Appearance</a><button class="app-nav-disclosure" type="button" data-disclosure aria-expanded="false" aria-controls="help-links">Help</button><div class="app-nav-submenu" id="help-links" hidden>{_help_links(help_items)}</div>{_authorization_pills(pills)}</nav></aside>
<main class="site-main" id="main-content" tabindex="-1"><header class="site-hero" id="overview"><h1>Charles Weissmann Fellowships</h1><p>Internal workspace preview for the Ernst Hadorn Foundation.</p></header>
<div class="preview-notice" role="status">Preview only<span>{escape(notice)} Submission is not active. Communication sending is not active. {escape(record_notice)}</span></div>
{_report_section(records, shortlist_state)}{_sections(entries, include=frozenset({"operations"}))}<section id="appearance" aria-labelledby="appearance-heading"><div class="section-heading"><h2 id="appearance-heading">Appearance preview</h2><p>Preferences load and save server-side only after secure sign-in is active.</p></div>{_appearance_controls()}</section></main>
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


def _sections(
    entries: tuple[NavigationEntry, ...], *, include: frozenset[str] = frozenset()
) -> str:
    return "".join(
        f'<section id="{escape(entry.key)}" class="section-heading"><h2>{escape(entry.label)}</h2><p>{escape(entry.help_text)}</p></section>'
        for entry in entries
        if entry.key in include
    )


def _report_section(records: tuple[PreviewApplicantMetric, ...], shortlist: ShortlistState) -> str:
    return (
        '<section id="reports" aria-labelledby="reports-heading"><div class="section-heading">'
        '<h2 id="reports-heading">Reports</h2><p>OpenAlex citations are calculated from each applicant’s verified published works at the 20 September 2026 cutoff; validated publication counts use the same verified set. Applicant-reported publication totals remain separate, while unmatched and non-publication records are excluded from validated statistics and retained for audit.</p><p class="report-interaction-hint">Use the triangles beside any field title to sort ascending or descending. Double-click a row, or focus it and press Enter, to view all details.</p></div>'
        '<div class="report-grid">'
        f'{_scatterplot(records, "Citations by anagraphic age", "age", "Anagraphic age")}'
        f'{_scatterplot(records, "Citations by academic age", "academic_age", "Academic age")}'
        f'{_age_comparison_plot(records)}'
        "</div>"
        '<div class="report-actions"><label class="report-filter" for="report-applicant-filter">Filter applicants'
        '<select id="report-applicant-filter" data-report-filter>'
        '<option value="" selected disabled>Select application status</option>'
        '<option value="completed">Completed applications</option>'
        '<option value="missing">Applications where anything is missing</option>'
        '</select></label><a class="report-download" href="/internal/reports/metrics.xlsx">Download Excel</a></div>'
        f'{_report_table(records, shortlist)}</section>'
    )


def _report_table(records: tuple[PreviewApplicantMetric, ...], shortlist: ShortlistState) -> str:
    headers = (
        ("Applicant", "text"), ("Degree", "text"), ("Age", "number"),
        ("Academic age (years)", "number"), ("Gender", "text"),
        ("First / last author papers", "number"),
        ("Applicant-reported / validated published papers", "number"),
        ("h-index", "number"),
        ("OpenAlex citations (20 Sep 2026)", "number"),
    )
    labels = tuple(label for label, _kind in headers)
    metric_header = "".join(
        _report_header(index, label, kind)
        for index, (label, kind) in enumerate(headers)
    )
    shortlist_header = (
        '<span class="report-shortlist-group" role="columnheader" aria-colspan="3">Shortlist</span>'
        + "".join(
            f'<span class="report-shortlist-heading" role="columnheader"><span>{name}</span>'
            f'<span class="report-shortlist-mode" data-shortlist-mode="{mode}">{label}</span></span>'
            for trustee_code, name in (
                ("ricky", "Ricky"), ("magda", "Magda"), ("adriano", "Adriano")
            )
            for mode, label in (
                ("editable", "Yours")
                if trustee_code == shortlist.editable_trustee
                else ("saved", "Saved"),
            )
        )
    )
    h_indices = tuple(record.h_index for record in records if record.h_index is not None)
    h_index_low = min(h_indices, default=None)
    h_index_high = max(h_indices, default=None)
    rows = "".join(
        _report_row(record, labels, _h_index_saturation(record.h_index, h_index_low, h_index_high), shortlist)
        for record in records
    )
    empty = (
        '<p class="report-empty" role="status">No application metrics are available.</p>'
        if not records else ""
    )
    return (
        '<div class="report-table" role="table" aria-label="2026 applicant metrics">'
        f'<div class="report-header" role="row">{metric_header}{shortlist_header}</div>'
        f'<div class="report-data" role="rowgroup">{rows}</div></div>{empty}'
        '<p class="report-filter-empty" data-report-filter-empty role="status" hidden>No applications match the selected filter.</p>'
        '<dialog class="report-details-modal" data-report-modal aria-labelledby="report-details-title" aria-modal="true">'
        '<div class="report-details-panel"><div class="report-details-header">'
        '<h3 id="report-details-title" data-report-details-title>Application details</h3>'
        '<button type="button" class="report-details-close" data-report-modal-close aria-label="Close details">×</button>'
        '</div><nav class="report-document-actions" aria-label="Applicant documents">'
        '<a class="report-document-action" data-report-artifact="application" target="_blank" rel="noopener noreferrer" aria-disabled="true">Application</a>'
        '<a class="report-document-action" data-report-artifact="curriculum" target="_blank" rel="noopener noreferrer" aria-disabled="true">Curriculum</a>'
        '<a class="report-document-action" data-report-artifact="publications" target="_blank" rel="noopener noreferrer" aria-disabled="true">Publication list</a>'
        '</nav><p class="report-document-status" data-report-artifact-status role="status">Document availability loads when an applicant is opened.</p>'
        '<section aria-label="Track record"><div class="report-details-content" data-report-details></div></section>'
        '</div></dialog><p class="report-shortlist-status" data-shortlist-status role="status" aria-live="polite"></p>'
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


def _report_row(
    record: PreviewApplicantMetric,
    headers: tuple[str, ...],
    h_index_saturation: int | None,
    shortlist: ShortlistState,
) -> str:
    values = (
        (record.applicant, _display_markup(record.applicant), None, None),
        (record.degree, _display_markup(record.degree), None, None),
        (record.age, _display_markup(_number(record.age)), None, None),
        (record.academic_age, _display_markup(_number(record.academic_age)), None, None),
        (record.gender, _display_markup(record.gender), None, None),
        (
            (record.first_author_papers, record.last_author_papers),
            _combined_metric_markup(record.first_author_papers, record.last_author_papers),
            _number(record.first_author_papers),
            None,
        ),
        (
            (record.total_papers, record.validated_published_papers),
            _combined_metric_markup(
                record.total_papers, record.validated_published_papers
            ),
            _number(record.validated_published_papers),
            None,
        ),
        (record.h_index, _display_markup(_number(record.h_index)), None, h_index_saturation),
        (record.verified_citations, _display_markup(_number(record.verified_citations)), None, None),
    )
    cells = "".join(
        _report_cell(label, markup, sort_value=sort_value, h_index_saturation=heat)
        for label, (_raw, markup, sort_value, heat) in zip(headers, values, strict=True)
    )
    application_id_value = record.application_id or ""
    cells += "".join(
        _shortlist_cell(
            application_id_value,
            code,
            name,
            shortlist.group(application_id_value, code),
            shortlist.editable_trustee == code and bool(application_id_value),
        )
        for code, name in (("ricky", "Ricky"), ("magda", "Magda"), ("adriano", "Adriano"))
    )
    status_values = tuple(value[0] for value in values)
    status = "missing" if any(value in (None, "") or (isinstance(value, tuple) and any(part in (None, "") for part in value)) for value in status_values) else "completed"
    detail_attributes = ""
    if record.application_id:
        application_id = escape(record.application_id, quote=True)
        detail_attributes = (
            f' data-application-id="{application_id}"'
            f' data-report-details-url="/api/internal/applicants/{application_id}/metrics-detail"'
        )
    return (
        f'<div class="report-data-row" role="row" data-report-row tabindex="0" data-report-status="{status}"{detail_attributes} '
        f'aria-label="Open full details for {escape(record.applicant)}">{cells}</div>'
    )


def _report_cell(
    label: str,
    markup: str,
    *,
    sort_value: str | None,
    h_index_saturation: int | None = None,
) -> str:
    sort_attribute = (
        f' data-report-sort-value="{escape(sort_value, quote=True)}"'
        if sort_value is not None
        else ""
    )
    heat_attribute = (
        f' data-h-index-heat class="h-index-heat-{h_index_saturation}"'
        if h_index_saturation is not None
        else ""
    )
    return f'<span role="cell" data-label="{escape(label)}"{heat_attribute}{sort_attribute}>{markup}</span>'


def _shortlist_cell(application_id: str, trustee_code: str, name: str, group: str | None, editable: bool) -> str:
    escaped_application_id = escape(application_id, quote=True)
    if not editable:
        assignment = group or "unassigned"
        label = group or "—"
        return (
            f'<span class="report-shortlist-cell" role="cell" data-label="Shortlist — {name}">'
            f'<span class="shortlist-grade-readonly" data-shortlist-owner="{trustee_code}" '
            f'data-shortlist-assignment="{assignment}" aria-label="{escape(name)}: Group {label}">{label}</span></span>'
        )
    buttons = "".join(
        f'<button type="button" class="shortlist-grade" data-shortlist-grade '
        f'data-application-id="{escaped_application_id}" data-shortlist-owner="{trustee_code}" '
        f'data-shortlist-group="{candidate_group}" aria-pressed="{str(group == candidate_group).lower()}" '
        f'aria-label="Assign {escape(name)} to group {candidate_group}">{candidate_group}</button>'
        for candidate_group in ("A", "B", "C")
    )
    return (
        f'<span class="report-shortlist-cell" role="cell" data-label="Shortlist — {name}">'
        f'<span class="shortlist-grade-control" role="group" aria-label="Shortlist group for {escape(name)}: {escape(application_id)}">{buttons}</span></span>'
    )


def _h_index_saturation(
    h_index: int | None, low: int | None, high: int | None
) -> int | None:
    if h_index is None or low is None or high is None:
        return None
    if low == high:
        return 50
    saturation = 10 + (h_index - low) * 80 / (high - low)
    return min(90, max(10, round(saturation / 10) * 10))


def _combined_metric_markup(first: int | None, last: int | None) -> str:
    return f"{_display_markup(_number(first))} / {_display_markup(_number(last))}"


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
            h_index_range=_h_index_range(records),
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
            h_index_range=_h_index_range(records),
        )
    return f'<article class="report-card"><h3>{title}</h3>{plot}</article>'


def _value_plot(
    title: str,
    points: tuple[tuple[CitationPlotPoint, float, float, float], ...],
    *,
    x_label: str,
    y_label: str,
    bubbles: bool = False,
    h_index_range: tuple[int, int] | None = None,
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
            bubble_radius=(
                max(3.0, 16.0 * (citations / largest_citation) ** 0.5)
                if bubbles
                else 6.0
            ),
            bubbles=bubbles,
            x_label=x_label,
            y_label=y_label,
        )
        for (point, x_value, y_value, citations), x, y in positioned
    )
    h_indices = tuple(point[0].h_index for point in points if point[0].h_index is not None)
    h_low = h_index_range[0] if h_index_range is not None else min(h_indices, default=None)
    h_high = h_index_range[1] if h_index_range is not None else max(h_indices, default=None)
    size_explanation = (
        "Bubble area represents OpenAlex citations."
        if bubbles
        else "Equal-sized circles represent candidates."
    )
    callout_explanation = (
        '<li><span class="legend-callout" aria-hidden="true">Aa</span>'
        "Surname labels mark the 15 candidates with the most citations.</li>"
        if bubbles
        else ""
    )
    h_low_text = _number(h_low) if h_low is not None else "unavailable"
    h_high_text = _number(h_high) if h_high is not None else "unavailable"
    legend = (
        '<ul class="chart-legend report-plot-legend" aria-label="Graph legend">'
        f'<li><strong>Horizontal axis:</strong> {escape(x_label)}.</li>'
        f'<li><strong>Vertical axis:</strong> {escape(y_label)}.</li>'
        f'<li><span class="legend-point legend-point--size" aria-hidden="true"></span>{size_explanation}</li>'
        f'<li><span class="legend-swatch legend-swatch--h-low" aria-hidden="true"></span>Light blue: h-index {h_low_text}.</li>'
        f'<li><span class="legend-swatch legend-swatch--h-high" aria-hidden="true"></span>Deep blue: h-index {h_high_text}.</li>'
        '<li><span class="legend-swatch legend-swatch--missing" aria-hidden="true"></span>Red: h-index unavailable.</li>'
        f'{callout_explanation}'
        '<li>Focus a point to read its exact values.</li></ul>'
    )
    return (
        f'<svg viewBox="0 0 640 410" role="img" aria-label="{escape(title)}; {len(points)} candidates">'
        f'{_plot_grid(x_ticks, y_ticks, x_low, x_high, y_low, y_high)}'
        '<path class="plot-axis" d="M78 34V344H558" />'
        f'{circles}{_plot_callouts(positioned, _callout_source_indices(points))}'
        f'<text class="plot-axis-label" x="318" y="398">{escape(x_label)}</text>'
        f'<text class="plot-axis-label" x="19" y="189" transform="rotate(-90 19 189)">{escape(y_label)}</text></svg>{legend}'
    )


def _h_index_range(records: tuple[PreviewApplicantMetric, ...]) -> tuple[int, int] | None:
    values = tuple(record.h_index for record in records if record.h_index is not None)
    return (min(values), max(values)) if values else None


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
    h_index_description = _number(point.h_index) or "Missing"
    description = (
        f"{point.applicant}: {x_label.removesuffix(' (years)').casefold()} "
        f"{_number(x_value)}, {y_label.removesuffix(' (years)').casefold()} "
        f"{_number(y_value)}, {int(point.citations):,} citations"
    )
    if not bubbles:
        description = (
            f"{point.applicant}: {x_label.removesuffix(' (years)').casefold()} "
            f"{_number(x_value)}, {int(point.citations):,} citations, "
            f"h-index {h_index_description}"
        )
    else:
        description = f"{description}, h-index {h_index_description}"
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
