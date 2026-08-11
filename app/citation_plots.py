"""Shared point identities, colors, and labels for citation scatter plots."""

from __future__ import annotations

from colorsys import hls_to_rgb
from dataclasses import dataclass
from math import isfinite
from typing import Protocol, Sequence


class CitationMetric(Protocol):
    applicant: str
    total_citations: int | None
    google_scholar_citations: int | None


@dataclass(frozen=True, slots=True)
class CitationPlotPoint:
    source_index: int
    applicant: str
    surname: str
    age: float
    citations: float
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
    """Build plottable points with dataset-stable colors and ranked call-out flags."""
    colors = _record_colors(records)
    candidates: list[tuple[int, str, float, float, str]] = []
    for source_index, record in enumerate(records):
        age = _finite_number(getattr(record, age_field, None))
        citation_value = (
            record.total_citations
            if record.total_citations is not None
            else record.google_scholar_citations
        )
        citations = _finite_number(citation_value)
        if age is None or citations is None:
            continue
        candidates.append(
            (source_index, record.applicant, age, citations, colors[source_index])
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
            color=color,
            labelled=source_index in labelled_indices,
        )
        for source_index, applicant, age, citations, color in candidates
    )


def _record_colors(records: Sequence[CitationMetric]) -> tuple[str, ...]:
    ordered_indices = sorted(
        range(len(records)),
        key=lambda index: (
            records[index].applicant.casefold(), records[index].applicant, index
        ),
    )
    colors = ["#000000"] * len(records)
    for rank, source_index in enumerate(ordered_indices):
        hue = (211.0 + rank * 137.507764) % 360.0
        lightness = (0.38, 0.52, 0.66)[rank % 3]
        red, green, blue = hls_to_rgb(hue / 360.0, lightness, 0.72)
        colors[source_index] = (
            f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"
        )
    return tuple(colors)


def _finite_number(value: object | None) -> float | None:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None
