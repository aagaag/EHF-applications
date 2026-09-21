"""Shared point identities, colors, and labels for citation scatter plots."""

from __future__ import annotations

from colorsys import hls_to_rgb
from dataclasses import dataclass
from math import isfinite
from typing import Protocol, Sequence


class CitationMetric(Protocol):
    applicant: str
    h_index: int | None
    total_citations: int | None
    google_scholar_citations: int | None
    verified_citations: int | None


@dataclass(frozen=True, slots=True)
class CitationPlotPoint:
    source_index: int
    applicant: str
    surname: str
    age: float
    citations: float
    h_index: int | None
    color: str
    labelled: bool


_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})


def applicant_surname(name: str) -> str:
    """Return the shortest useful surname label without altering its spelling."""
    normalized = " ".join(name.split())
    if not normalized:
        return "Applicant"
    if "," in normalized:
        parts = _without_name_suffix(normalized.split(",", 1)[0].split())
        return " ".join(parts) or "Applicant"
    parts = _without_name_suffix(normalized.split())
    return parts[-1] if parts else "Applicant"


def _without_name_suffix(parts: list[str]) -> list[str]:
    if len(parts) > 1 and parts[-1].rstrip(".").casefold() in _NAME_SUFFIXES:
        return parts[:-1]
    return parts


def citation_plot_points(
    records: Sequence[CitationMetric], age_field: str, *, label_limit: int = 15
) -> tuple[CitationPlotPoint, ...]:
    """Build plottable points with H-index heat colors and ranked call-out flags."""
    colors = _record_colors(records)
    candidates: list[tuple[int, str, float, float, int | None, str]] = []
    for source_index, record in enumerate(records):
        age = _finite_number(getattr(record, age_field, None))
        citation_value = getattr(record, "verified_citations", None)
        citations = _finite_number(citation_value)
        if age is None or citations is None:
            continue
        h_index_value = _finite_number(getattr(record, "h_index", None))
        h_index = int(h_index_value) if h_index_value is not None else None
        candidates.append(
            (
                source_index,
                record.applicant,
                age,
                citations,
                h_index,
                colors[source_index],
            )
        )

    ranked = sorted(
        candidates,
        key=lambda candidate: (
            -candidate[3], candidate[1].casefold(), candidate[1], candidate[0]
        ),
    )
    labelled_indices = {
        candidate[0] for candidate in ranked[: max(0, label_limit)]
    }
    return tuple(
        CitationPlotPoint(
            source_index=source_index,
            applicant=applicant,
            surname=applicant_surname(applicant),
            age=age,
            citations=citations,
            h_index=h_index,
            color=color,
            labelled=source_index in labelled_indices,
        )
        for source_index, applicant, age, citations, h_index, color in candidates
    )


def _record_colors(records: Sequence[CitationMetric]) -> tuple[str, ...]:
    h_indices = tuple(
        value
        for record in records
        if (value := _finite_number(getattr(record, "h_index", None))) is not None
    )
    if not h_indices:
        return ("#B42318",) * len(records)
    low, high = min(h_indices), max(h_indices)
    return tuple(
        _h_index_heat_color(
            _finite_number(getattr(record, "h_index", None)), low, high
        )
        for record in records
    )


def _h_index_heat_color(
    h_index: float | None, low: float, high: float
) -> str:
    if h_index is None:
        return "#B42318"
    position = 0.5 if low == high else (h_index - low) / (high - low)
    saturation = 0.10 + 0.80 * position
    lightness = 0.94 - 0.52 * position
    red, green, blue = hls_to_rgb(210.0 / 360.0, lightness, saturation)
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"


def _finite_number(value: object | None) -> float | None:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None
