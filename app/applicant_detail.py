"""Small, data-only applicant detail renderer for internal review surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape
import math
import unicodedata
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class Publication:
    """Canonical publication fields needed by the applicant detail view."""

    title: str
    journal: str | None = None
    year: int | None = None
    doi: str | None = None
    journal_url: str | None = None
    repository_url: str | None = None
    source_url: str | None = None
    citation_count: int | None = None
    citations_by_year: tuple[tuple[int, int], ...] = ()
    authors_text: str | None = None
    journal_openalex_id: str | None = None
    journal_openalex_name: str | None = None
    journal_two_year_mean_citedness: float | None = None
    journal_metric_observed_at_utc: str | None = None


@dataclass(frozen=True, slots=True)
class ApplicantDetail:
    """Read-only applicant detail data; no database or framework dependency."""

    application_number: str
    name: str
    age: int | float | None = None
    academic_age: int | float | None = None
    publications: tuple[Publication, ...] = ()


def render_applicant_detail(
    detail: ApplicantDetail, *, current_year: int | None = None
) -> str:
    """Render an accessible, escaped HTML detail component."""
    end_year = current_year if current_year is not None else date.today().year
    years = [publication.year for publication in detail.publications if _valid_year(publication.year)]
    start_year = min(years, default=end_year)
    if start_year > end_year:
        end_year = start_year
    span = tuple(range(start_year, end_year + 1))
    papers = {year: 0 for year in span}
    citations = {year: 0 for year in span}
    for publication in detail.publications:
        if publication.year in papers:
            papers[publication.year] += 1
        for year, count in publication.citations_by_year:
            if year in citations and isinstance(count, int) and count >= 0:
                citations[year] += count

    identity = (
        f'<div class="applicant-detail-identity" aria-label="Applicant identity">'
        f'<span class="application-number">{_text(detail.application_number)}</span>'
        f'<span class="applicant-name">{_text(detail.name)}</span>'
        f'<span>Age: {_text(_number(detail.age))}</span>'
        f'<span>Academic age: {_text(_number(detail.academic_age))}</span></div>'
    )
    ordered = sorted(detail.publications, key=lambda item: item.year or 0, reverse=True)
    rows = "".join(_publication_row(publication, detail.name) for publication in ordered)
    empty = '<p class="applicant-detail-empty">No publications are available.</p>' if not rows else ""
    return (
        '<section class="applicant-detail" aria-label="Applicant detail">'
        f"{identity}"
        '<div class="applicant-detail-charts">'
        f'{_bar_chart("Papers by year", "Papers", papers, start_year, end_year)}'
        f'{_bar_chart("Citations by year", "Citations", citations, start_year, end_year)}'
        f'{_journal_scatter_chart(detail.publications, detail.name)}'
        '</div>'
        '<section class="applicant-publications" aria-labelledby="applicant-publications-heading">'
        '<h2 id="applicant-publications-heading">Publications</h2>'
        '<div class="applicant-publication-list" role="table" aria-label="Applicant publications" data-publication-table>'
        '<div class="applicant-publication-header" role="row">'
        '<span role="columnheader">Title</span><span role="columnheader">Journal / year</span>'
        '<span role="columnheader" data-publication-citation-header><span>Citations</span>'
        '<span class="publication-sort-buttons">'
        '<button type="button" data-publication-sort data-publication-sort-direction="ascending" aria-label="Sort citations ascending" aria-pressed="false">▲</button>'
        '<button type="button" data-publication-sort data-publication-sort-direction="descending" aria-label="Sort citations descending" aria-pressed="false">▼</button>'
        '</span></span></div>'
        f'<div class="applicant-publication-body" role="rowgroup">{rows}</div></div>{empty}'
        '</section></section>'
    )


def _bar_chart(
    title: str,
    axis_label: str,
    values: dict[int, int],
    start_year: int,
    end_year: int,
) -> str:
    maximum = max(values.values(), default=0)
    width, height, left, right, top, baseline = 720, 180, 52, 708, 18, 145
    plot_height = baseline - top
    slot = (right - left) / max(1, len(values))
    bars: list[str] = []
    for index, (year, value) in enumerate(values.items()):
        bar_height = 0 if maximum == 0 else max(2, round((value / maximum) * plot_height))
        x = round(left + index * slot + slot * 0.15, 2)
        bar_width = round(slot * 0.7, 2)
        y = baseline - bar_height
        bars.append(
            f'<rect x="{x}" y="{y}" width="{bar_width}" height="{bar_height}" '
            f'role="img" aria-label="{_text(year)}: {_text(value)}" tabindex="0">'
            f'<title>{_text(year)}: {_text(value)}</title></rect>'
        )
    labels = "".join(
        f'<text x="{round(left + index * slot + slot / 2, 2)}" y="165" text-anchor="middle">{_text(year)}</text>'
        for index, year in enumerate(values)
    )
    ticks = _axis_ticks(maximum)
    tick_markup = "".join(
        f'<line x1="{left - 5}" y1="{round(baseline - (value / max(ticks)) * plot_height, 2)}" '
        f'x2="{left}" y2="{round(baseline - (value / max(ticks)) * plot_height, 2)}" />'
        f'<text class="chart-y-axis-tick" x="{left - 8}" '
        f'y="{round(baseline - (value / max(ticks)) * plot_height + 3, 2)}" text-anchor="end">{_text(value)}</text>'
        for value in ticks
    )
    label = f'{title}, {start_year} through {end_year}'
    return (
        f'<figure class="applicant-detail-chart" data-full-page-chart role="link" tabindex="0" aria-label="Open full-page graph: {_text(label)}">'
        f'<figcaption>{_text(title)}</figcaption>'
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{_text(label)}" '
        f'xmlns="http://www.w3.org/2000/svg"><line x1="{left}" y1="{top}" x2="{left}" y2="{baseline}" />'
        f'<line x1="{left}" y1="{baseline}" x2="{right}" y2="{baseline}" />'
        f'{tick_markup}<text class="chart-y-axis-label" x="15" y="82" text-anchor="middle" '
        f'transform="rotate(-90 15 82)">{_text(axis_label)}</text>{"".join(bars)}{labels}</svg></figure>'
    )


def _axis_ticks(maximum: int) -> tuple[int, ...]:
    if maximum <= 1:
        return (0, 1)
    return (0, (maximum + 1) // 2, maximum)


def _journal_scatter_chart(
    publications: tuple[Publication, ...], applicant_name: str
) -> str:
    title = "Papers by year and journal citedness"
    plotted = [publication for publication in publications if _valid_year(publication.year)]
    omitted = [publication for publication in publications if not _valid_year(publication.year)]
    omitted_markup = "".join(
        f'<li>{_text(publication.title)}: omitted because its publication year is unavailable.</li>'
        for publication in omitted
    )
    omitted_summary = (
        f"{len(plotted)} papers plotted; {len(omitted)} omitted because its publication year is unavailable."
        if omitted
        else f"{len(plotted)} papers plotted."
    )
    if not plotted:
        return (
            '<figure class="applicant-detail-chart applicant-detail-chart--journal-scatter" '
            f'data-full-page-chart role="link" tabindex="0" aria-label="Open full-page graph: {_text(title)}"><figcaption>{_text(title)}</figcaption>'
            '<p class="journal-scatter-empty">No publications have a valid publication year for this chart.</p>'
            f'<ul class="journal-scatter-omitted">{omitted_markup}</ul></figure>'
        )

    width, height = 720, 220
    left, right, top, numeric_bottom, na_y = 62, 700, 18, 138, 184
    years = [publication.year for publication in plotted if publication.year is not None]
    first_year, last_year = min(years), max(years)
    metrics = [_journal_metric(publication.journal_two_year_mean_citedness) for publication in plotted]
    numeric_metrics = [metric for metric in metrics if metric is not None]
    maximum_metric = max(numeric_metrics, default=0.0)
    scale_maximum = maximum_metric if maximum_metric > 0 else 1.0
    citation_values = [
        publication.citation_count
        for publication in plotted
        if isinstance(publication.citation_count, int) and publication.citation_count >= 0
    ]
    maximum_citations = max(citation_values, default=0)
    points: list[dict[str, object]] = []
    for index, publication in enumerate(plotted):
        year = publication.year
        assert year is not None
        citedness = _journal_metric(publication.journal_two_year_mean_citedness)
        citation_count = (
            publication.citation_count
            if isinstance(publication.citation_count, int) and publication.citation_count >= 0
            else None
        )
        citation_ratio = (
            0.0
            if citation_count is None or maximum_citations == 0
            else citation_count / maximum_citations
        )
        area = 36.0 + 900.0 * citation_ratio
        radius = round(math.sqrt(area / math.pi), 2)
        x = round(
            (left + right) / 2
            if first_year == last_year
            else left + (year - first_year) / (last_year - first_year) * (right - left),
            2,
        )
        y = na_y if citedness is None else round(
            numeric_bottom - (citedness / scale_maximum) * (numeric_bottom - top), 2
        )
        position = _author_position(publication.authors_text, applicant_name)
        source_name = publication.journal_openalex_name or publication.journal or "Journal unavailable"
        citedness_text = (
            "OpenAlex 2-year journal citedness unavailable"
            if citedness is None
            else f"OpenAlex 2-year journal citedness {_display_number(citedness)}"
        )
        citation_text = (
            "citation data unavailable"
            if citation_count is None
            else f"{citation_count} OpenAlex citations"
        )
        author_text = (
            f"applicant is {position} author"
            if position is not None
            else "applicant is not first or last author"
        )
        points.append(
            {
                "publication": publication,
                "index": index,
                "x": x,
                "y": y,
                "radius": radius,
                "citedness": citedness,
                "citation_count": citation_count,
                "position": position,
                "source_name": source_name,
                "label": ". ".join(
                    (
                        publication.title,
                        source_name,
                        str(year),
                        citedness_text,
                        citation_text,
                        author_text,
                    )
                ),
            }
        )
    circles = "".join(
        _journal_scatter_point(point)
        for point in sorted(
            points,
            key=lambda point: (-float(point["radius"]), int(point["index"])),
        )
    )
    accessible_list = "".join(
        f'<li data-journal-scatter-list-item>{_text(str(point["label"]))}</li>'
        for point in points
    )
    year_labels = "".join(
        f'<text x="{_year_x(year, first_year, last_year, left, right)}" y="159" '
        f'text-anchor="middle">{year}</text>'
        for year in range(first_year, last_year + 1)
    )
    y_ticks = _metric_ticks(maximum_metric)
    y_tick_markup = "".join(
        f'<line x1="{left - 5}" y1="{round(numeric_bottom - value / scale_maximum * (numeric_bottom - top), 2)}" '
        f'x2="{left}" y2="{round(numeric_bottom - value / scale_maximum * (numeric_bottom - top), 2)}" />'
        f'<text class="chart-y-axis-tick" x="{left - 8}" '
        f'y="{round(numeric_bottom - value / scale_maximum * (numeric_bottom - top) + 3, 2)}" '
        f'text-anchor="end">{_display_number(value)}</text>'
        for value in y_ticks
    )
    na_lane = (
        f'<line class="journal-scatter-na-lane" x1="{left}" y1="{na_y}" x2="{right}" y2="{na_y}" />'
        f'<text class="journal-scatter-na-label" x="{left - 8}" y="{na_y + 3}" text-anchor="end">N/A</text>'
        if any(point["citedness"] is None for point in points)
        else ""
    )
    snapshot_dates = sorted(
        {
            publication.journal_metric_observed_at_utc[:10]
            for publication in plotted
            if publication.journal_metric_observed_at_utc
        }
    )
    snapshot = (
        f'<p class="journal-scatter-snapshot">Snapshot: {_text(snapshot_dates[-1])}</p>'
        if snapshot_dates
        else ""
    )
    return (
        '<figure class="applicant-detail-chart applicant-detail-chart--journal-scatter" '
        f'data-full-page-chart role="link" tabindex="0" aria-label="Open full-page graph: {_text(title)}"><figcaption>{_text(title)}</figcaption>'
        '<p class="journal-scatter-legend">Bubble area represents OpenAlex citations. '
        'Red: first, sole, or last author. Blue: neither first nor last author.</p>'
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{_text(title)}" '
        'xmlns="http://www.w3.org/2000/svg">'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{numeric_bottom}" />'
        f'<line x1="{left}" y1="{numeric_bottom}" x2="{right}" y2="{numeric_bottom}" />'
        f'{y_tick_markup}{na_lane}'
        f'<text class="chart-y-axis-label" x="15" y="87" text-anchor="middle" '
        f'transform="rotate(-90 15 87)">OpenAlex 2-year journal citedness</text>'
        f'<text class="journal-scatter-x-label" x="{(left + right) / 2}" y="177" text-anchor="middle">Publication year</text>'
        f'{year_labels}{circles}</svg>'
        f'<p class="journal-scatter-summary">{_text(omitted_summary)}</p>{snapshot}'
        f'<ul class="journal-scatter-accessible-list">{accessible_list}</ul>'
        f'<ul class="journal-scatter-omitted">{omitted_markup}</ul></figure>'
    )


def _journal_scatter_point(point: dict[str, object]) -> str:
    publication = point["publication"]
    assert isinstance(publication, Publication)
    position = point["position"]
    assert position is None or isinstance(position, str)
    citedness = point["citedness"]
    citation_count = point["citation_count"]
    classes = ["journal-scatter-point"]
    if position is not None:
        classes.append("journal-scatter-point--lead-author")
    else:
        classes.append("journal-scatter-point--other-author")
    if citedness is None:
        classes.append("journal-scatter-point--metric-unavailable")
    if citation_count is None:
        classes.append("journal-scatter-point--citation-unavailable")
    author_markup = f' data-author-position="{position}"' if position is not None else ""
    citation_markup = "" if citation_count is None else str(citation_count)
    return (
        f'<circle class="{" ".join(classes)}" data-journal-scatter-point '
        f'data-citation-count="{citation_markup}" data-publication-year="{publication.year}" '
        f'cx="{point["x"]}" cy="{point["y"]}" r="{point["radius"]}" '
        f'role="img" tabindex="0"{author_markup} aria-label="{_text(str(point["label"]))}">'
        f'<title>{_text(str(point["label"]))}</title></circle>'
    )


def _journal_metric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) and numeric >= 0 else None


def _year_x(year: int, first_year: int, last_year: int, left: int, right: int) -> float:
    return round(
        (left + right) / 2
        if first_year == last_year
        else left + (year - first_year) / (last_year - first_year) * (right - left),
        2,
    )


def _metric_ticks(maximum: float) -> tuple[float, ...]:
    if maximum <= 0:
        return (0.0, 1.0)
    return (0.0, maximum / 2, maximum)


def _display_number(value: float) -> str:
    return format(value, ".4g")


def _publication_row(publication: Publication, applicant_name: str) -> str:
    href = _publication_url(publication)
    href_markup = (
        f' data-publication-url="{escape(href, quote=True)}"' if href else ""
    )
    label = ". ".join(part for part in (publication.title, publication.journal, _number(publication.year)) if part)
    author_position = _author_position(publication.authors_text, applicant_name)
    position_markup = f' data-author-position="{author_position}"' if author_position else ""
    lead_author_class = " applicant-publication-row--lead-author" if author_position else ""
    citations = _number(publication.citation_count)
    citation_sort = "" if publication.citation_count is None else str(publication.citation_count)
    return (
        f'<div class="applicant-publication-row{lead_author_class}" role="row" data-publication-row '
        f'data-publication-citations="{citation_sort}" '
        f'data-double-clickable="true" tabindex="0"{href_markup}{position_markup} '
        f'aria-label="Open publication: {_text(label)}" title="Double-click to open publication">'
        f'<span class="publication-title" role="cell">{_text(publication.title)}</span>'
        f'<span class="publication-meta" role="cell">{_text(publication.journal)} · {_text(publication.year)}</span>'
        f'<span class="publication-citations" role="cell">{_text(citations)}</span>'
        '</div>'
    )


def _author_position(authors_text: str | None, applicant_name: str) -> str | None:
    applicant = _person_tokens(applicant_name)
    authors = [
        _person_tokens(author)
        for author in (authors_text or "").split(";")
        if author.strip()
    ]
    if not applicant or not authors:
        return None
    if _same_person(authors[0], applicant):
        return "first" if len(authors) > 1 else "sole"
    if _same_person(authors[-1], applicant):
        return "last"
    return None


def _person_tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return tuple(
        part
        for part in "".join(
            character.lower() if character.isalnum() else " " for character in normalized
        ).split()
        if part
    )


def _same_person(author: tuple[str, ...], applicant: tuple[str, ...]) -> bool:
    if sorted(author) == sorted(applicant):
        return True
    if len(author) < 2 or len(applicant) < 2:
        return False
    given_name, family_name = applicant[0], applicant[-1]
    if given_name not in author or family_name not in author:
        return False
    middle_names = applicant[1:-1]
    for token in author:
        if token in {given_name, family_name}:
            continue
        if token in middle_names:
            continue
        if len(token) == 1 and any(name.startswith(token) for name in middle_names):
            continue
        return False
    return True


def _publication_url(publication: Publication) -> str | None:
    if publication.doi:
        doi = publication.doi.strip()
        if doi.lower().startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/") :]
        elif doi.lower().startswith("http://doi.org/"):
            doi = doi[len("http://doi.org/") :]
        if doi and not doi.lower().startswith(("javascript:", "data:", "vbscript:")):
            return "https://doi.org/" + doi
    for candidate in (publication.journal_url, publication.repository_url, publication.source_url):
        if candidate and _safe_http_url(candidate):
            return candidate
    return None


def _safe_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _valid_year(value: int | None) -> bool:
    return isinstance(value, int) and 1000 <= value <= 9999


def _number(value: object) -> str:
    return "—" if value is None else str(value)


def _text(value: object) -> str:
    return escape(_number(value) if not isinstance(value, str) else value)
