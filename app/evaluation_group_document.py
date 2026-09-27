"""In-memory DOCX export for grouped applicant evaluations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from io import BytesIO

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

from app.evaluation_groups import BUCKET_ORDER, EvaluationApplicant, EvaluationGroups


def build_evaluation_group_docx(
    call_title: str,
    call_code: str,
    reviewer_roster: Mapping[str, str] | Sequence[tuple[str, str]],
    grouping: EvaluationGroups,
    *,
    generated_at: datetime | None = None,
) -> bytes:
    """Return a plain-text-safe DOCX summary of grouped applicant evaluations."""

    roster = _normalise_roster(reviewer_roster)
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)
    section.left_margin = Inches(0.7)
    section.right_margin = Inches(0.7)

    title = document.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run(_text(call_title))
    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.add_run(f"Call code: {_text(call_code)}")

    document.add_heading("Evaluation group summary", level=1)
    document.add_paragraph(
        f"Generated {_format_timestamp(generated_at)}. "
        f"Reviewer roster: {_format_roster(roster)}."
    )
    complete_count = sum(len(grouping.buckets.get(bucket, ())) for bucket in BUCKET_ORDER)
    document.add_paragraph(
        f"Counts: {complete_count} complete, {len(grouping.awaiting_reviews)} awaiting reviews, "
        f"{len(grouping.strong_discrepancy)} strong discrepancies."
    )

    for bucket in BUCKET_ORDER:
        applicants = grouping.buckets.get(bucket, ())
        document.add_heading(f"{bucket} ({len(applicants)})", level=2)
        _add_applicant_table(document, applicants, roster)

    document.add_heading(f"Strong discrepancies ({len(grouping.strong_discrepancy)})", level=2)
    _add_applicant_table(document, grouping.strong_discrepancy, roster)

    document.add_heading(f"Awaiting reviews ({len(grouping.awaiting_reviews)})", level=2)
    _add_applicant_table(document, grouping.awaiting_reviews, roster)

    discrepancy_ids = {applicant.id for applicant in grouping.strong_discrepancy}
    awaiting_ids = {applicant.id for applicant in grouping.awaiting_reviews}
    if discrepancy_ids & awaiting_ids:
        document.add_paragraph(
            "The partial A+C case appears in both awaiting reviews and strong discrepancies."
        )

    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _normalise_roster(
    reviewer_roster: Mapping[str, str] | Sequence[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    if isinstance(reviewer_roster, Mapping):
        return tuple((_text(key), _text(display_name)) for key, display_name in reviewer_roster.items())
    return tuple((_text(key), _text(display_name)) for key, display_name in reviewer_roster)


def _format_roster(roster: Sequence[tuple[str, str]]) -> str:
    return ", ".join(f"{display_name} ({key})" for key, display_name in roster)


def _add_applicant_table(
    document: Document,
    applicants: Sequence[EvaluationApplicant],
    roster: Sequence[tuple[str, str]],
) -> None:
    table = document.add_table(rows=1, cols=3)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    headers = ("Applicant", "Number", "Grades")
    for cell, header in zip(table.rows[0].cells, headers):
        cell.text = header
    for applicant in applicants:
        cells = table.add_row().cells
        cells[0].text = _text(applicant.name)
        cells[1].text = _text(applicant.number)
        cells[2].text = "\n".join(
            f"{key}: {applicant.grades.get(key) or 'pending'} ({display_name})"
            + (f"\nComment: {applicant.comments[key]}" if applicant.comments.get(key) else "")
            for key, display_name in roster
        )
    if not applicants:
        row = table.add_row().cells
        row[0].merge(row[2])
        row[0].text = "None"
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(9)


def _format_timestamp(value: datetime | None) -> str:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat(timespec="seconds")


def _text(value: object) -> str:
    return str(value)
