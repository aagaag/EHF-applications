"""Role-scoped internal metrics projection for the imported 2026 call."""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any, Protocol
from uuid import UUID

from app.applicant_detail import ApplicantDetail, Publication
from app.internal_preview import PreviewApplicantMetric


class MetricRepository(Protocol):
    def load(self, canonical_group: str) -> tuple[PreviewApplicantMetric, ...]: ...

    def load_detail(
        self, application_id: UUID, canonical_group: str
    ) -> ApplicantDetail: ...


class EmptyMetricRepository:
    def load(self, canonical_group: str) -> tuple[PreviewApplicantMetric, ...]:
        del canonical_group
        return ()

    def load_detail(
        self, application_id: UUID, canonical_group: str
    ) -> ApplicantDetail:
        del application_id, canonical_group
        raise LookupError("The applicant detail is unavailable.")


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
                verified_citations=(
                    0 if row[13] is None and row[14] is not None else _integer(row[13])
                ),
                verified_citation_source=_text(row[14]),
                verified_citation_profile_url=_text(row[15]),
                validated_published_papers=_integer(row[16]),
                application_id=_text(row[17]) if len(row) > 17 else None,
                application_number=_text(row[18]) if len(row) > 18 else None,
            )
            for row in rows
        )

    def load_detail(
        self, application_id: UUID, canonical_group: str
    ) -> ApplicantDetail:
        with self._connection_factory() as connection:
            cursor = connection.execute(
                "EXEC dbo.GetInternalApplicantMetricDetail "
                "@ApplicationId=?, @ActorGroup=?",
                application_id,
                canonical_group,
            )
            header = cursor.fetchone()
            if header is None:
                raise LookupError("The applicant detail is unavailable.")
            cursor.nextset()
            rows = cursor.fetchall()
        return ApplicantDetail(
            application_number=str(header[0]),
            name=str(header[1]),
            age=_number(header[2]),
            academic_age=_number(header[3]),
            publications=tuple(_publication(row) for row in rows),
        )


def _publication(row: Any) -> Publication:
    return Publication(
        title=_text(row[0]) or "Untitled publication",
        journal=_text(row[1]),
        year=_integer(row[2]),
        doi=_text(row[3]),
        journal_url=_text(row[4]),
        source_url=_text(row[5]),
        citation_count=_integer(row[6]),
        citations_by_year=_citation_years(row[7]),
        authors_text=_text(row[8]) if len(row) > 8 else None,
    )


def _citation_years(evidence: object) -> tuple[tuple[int, int], ...]:
    if evidence is None:
        return ()
    try:
        payload = json.loads(str(evidence))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    values = payload.get("counts_by_year") if isinstance(payload, dict) else None
    if not isinstance(values, dict):
        return ()
    result: list[tuple[int, int]] = []
    for raw_year, raw_count in values.items():
        try:
            year, count = int(raw_year), int(raw_count)
        except (TypeError, ValueError):
            continue
        if 1600 <= year <= 2200 and count >= 0:
            result.append((year, count))
    return tuple(sorted(result))


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _integer(value: object) -> int | None:
    return None if value is None else int(value)


def _number(value: object) -> float | None:
    return None if value is None else float(value)
