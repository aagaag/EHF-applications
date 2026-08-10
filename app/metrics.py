"""Role-scoped internal metrics projection for the imported 2026 call."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from app.internal_preview import PreviewApplicantMetric


class MetricRepository(Protocol):
    def load(self, canonical_group: str) -> tuple[PreviewApplicantMetric, ...]: ...


class EmptyMetricRepository:
    def load(self, canonical_group: str) -> tuple[PreviewApplicantMetric, ...]:
        del canonical_group
        return ()


class SqlMetricRepository:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def load(self, canonical_group: str) -> tuple[PreviewApplicantMetric, ...]:
        with self._connection_factory() as connection:
            rows = connection.execute(
                "EXEC dbo.GetInternalApplicationMetrics @ActorGroup=?", canonical_group
            ).fetchall()
        return tuple(
            PreviewApplicantMetric(
                applicant=str(row[0]),
                degree=_text(row[1]),
                age=_integer(row[2]),
                academic_age=_number(row[3]),
                gender=_text(row[4]),
                first_author_papers=_integer(row[5]),
                last_author_papers=_integer(row[6]),
                total_papers=_integer(row[7]),
                h_index=_integer(row[8]),
                total_citations=_integer(row[9]),
                orcid=_text(row[10]),
                google_scholar_citations=_integer(row[11]),
                identity_certainty=_text(row[12]),
            )
            for row in rows
        )


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _integer(value: object) -> int | None:
    return None if value is None else int(value)


def _number(value: object) -> float | None:
    return None if value is None else float(value)
