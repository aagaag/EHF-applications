"""PII-minimised internal exception summaries for EHF import review."""

from __future__ import annotations

import csv
import html
from pathlib import Path

from app.importer.run import ImportResult


def write_exception_report(result: ImportResult, output_root: Path) -> tuple[Path, Path]:
    """Write bounded HTML and CSV summaries without source paths, values, or document text."""
    output_root.mkdir(parents=True, exist_ok=True)
    rows = [
        (f"EHF-IMP-{index:04d}", code, count)
        for index, (code, count) in enumerate(sorted(result.exception_counts.items()), start=1)
    ]
    html_path = output_root / "exceptions.html"
    csv_path = output_root / "exceptions.csv"
    html_path.write_text(_html_report(result, rows), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("exception_id", "exception_code", "exception_count"))
        writer.writeheader()
        writer.writerows(
            {
                "exception_id": exception_id,
                "exception_code": code,
                "exception_count": count,
            }
            for exception_id, code, count in rows
        )
    return html_path, csv_path


def _html_report(result: ImportResult, rows: list[tuple[str, str, int]]) -> str:
    table = "\n".join(
        "<tr>"
        f"<td>{html.escape(exception_id)}</td>"
        f"<td>{html.escape(code)}</td>"
        f"<td>{count}</td>"
        "</tr>"
        for exception_id, code, count in rows
    ) or "<tr><td colspan=\"3\">No exceptions recorded.</td></tr>"
    return (
        "<!doctype html>\n"
        "<html lang=\"en\"><head><meta charset=\"utf-8\"><title>EHF import exceptions</title>"
        "</head><body><h1>EHF import exception report</h1>"
        f"<p>Mode: {html.escape(result.mode.value)}; planned applications: {result.application_count}; "
        f"exceptions: {sum(result.exception_counts.values())}.</p>"
        "<table><thead><tr><th>Internal ID</th><th>Exception code</th><th>Count</th>"
        f"</tr></thead><tbody>{table}</tbody></table></body></html>\n"
    )
