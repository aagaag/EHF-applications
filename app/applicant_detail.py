"""Small, data-only applicant detail renderer for internal review surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape
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
    rows = "".join(_publication_row(publication) for publication in ordered)
    empty = '<p class="applicant-detail-empty">No publications are available.</p>' if not rows else ""
    return (
        '<section class="applicant-detail" aria-label="Applicant detail">'
        f"{identity}"
        f'{_bar_chart("Papers by year", papers, start_year, end_year)}'
        f'{_bar_chart("Citations by year", citations, start_year, end_year)}'
        '<section class="applicant-publications" aria-labelledby="applicant-publications-heading">'
        '<h2 id="applicant-publications-heading">Publications</h2>'
        f'<div class="applicant-publication-list" role="list">{rows}</div>{empty}'
        '</section></section>'
    )


def _bar_chart(title: str, values: dict[int, int], start_year: int, end_year: int) -> str:
    maximum = max(values.values(), default=0)
    width, height, baseline = 720, 180, 145
    slot = width / max(1, len(values))
    bars: list[str] = []
    for index, (year, value) in enumerate(values.items()):
        bar_height = 0 if maximum == 0 else max(2, round((value / maximum) * 108))
        x = round(index * slot + slot * 0.15, 2)
        bar_width = round(slot * 0.7, 2)
        y = baseline - bar_height
        bars.append(
            f'<rect x="{x}" y="{y}" width="{bar_width}" height="{bar_height}" '
            f'role="img" aria-label="{_text(year)}: {_text(value)}" tabindex="0">'
            f'<title>{_text(year)}: {_text(value)}</title></rect>'
        )
    labels = "".join(
        f'<text x="{round(index * slot + slot / 2, 2)}" y="165" text-anchor="middle">{_text(year)}</text>'
        for index, year in enumerate(values)
    )
    label = f'{title}, {start_year} through {end_year}'
    return (
        f'<figure class="applicant-detail-chart" aria-label="{_text(label)}">'
        f'<figcaption>{_text(title)}</figcaption>'
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{_text(label)}" '
        f'xmlns="http://www.w3.org/2000/svg"><line x1="0" y1="{baseline}" x2="{width}" y2="{baseline}" />'
        f'{"".join(bars)}{labels}</svg></figure>'
    )


def _publication_row(publication: Publication) -> str:
    href = _publication_url(publication)
    href_markup = (
        f' data-publication-url="{escape(href, quote=True)}"' if href else ""
    )
    label = ". ".join(part for part in (publication.title, publication.journal, _number(publication.year)) if part)
    return (
        f'<div class="applicant-publication-row" role="listitem" data-publication-row '
        f'data-double-clickable="true" tabindex="0"{href_markup} '
        f'aria-label="Open publication: {_text(label)}" title="Double-click to open publication">'
        f'<span class="publication-title">{_text(publication.title)}</span>'
        f'<span class="publication-meta">{_text(publication.journal)} · {_text(publication.year)}</span>'
        '</div>'
    )


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
