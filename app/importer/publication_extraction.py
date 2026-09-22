"""Layout-aware extraction of applicant-authored publication citations.

The module deliberately separates PDF/section/entry segmentation from
bibliographic field parsing.  Applicant documents are processed locally and
every candidate retains page-level provenance.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from pypdf import PdfReader


_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_YEAR_COLUMN_RE = re.compile(r"^\s*(?:19|20)\s*\d\s*\d\s+\S")
_ENUMERATOR_RE = re.compile(r"^\s*(?:[•●▪◦‣]|\d{1,3}[.)])\s+")
_PAGE_NUMBER_RE = re.compile(r"^\s*(?:page\s+)?\d+(?:\s*/\s*\d+)?\s*$", re.IGNORECASE)

_PUBLICATION_HEADINGS = {
    "publication": "PUBLISHED",
    "publications": "PUBLISHED",
    "publicationlist": "PUBLISHED",
    "listofpublications": "PUBLISHED",
    "selectedpublications": "PUBLISHED",
    "peerreviewedpublications": "PUBLISHED",
    "peerreviewedpapers": "PUBLISHED",
    "originalarticles": "PUBLISHED",
    "researcharticles": "PUBLISHED",
    "journalarticles": "PUBLISHED",
    "bookchapters": "PUBLISHED",
    "conferencepapers": "PUBLISHED",
    "conferenceworkshoppapers": "PUBLISHED",
    "workshoppapers": "PUBLISHED",
    "review": "PUBLISHED",
    "reviews": "PUBLISHED",
    "preprint": "ACCEPTED_PREPRINT",
    "preprints": "ACCEPTED_PREPRINT",
    "submittedmanuscript": "ACCEPTED_PREPRINT",
    "submittedmanuscripts": "ACCEPTED_PREPRINT",
    "acceptedmanuscript": "ACCEPTED_PREPRINT",
    "acceptedmanuscripts": "ACCEPTED_PREPRINT",
    "manuscriptsunderreview": "ACCEPTED_PREPRINT",
    "manuscriptinpreparation": "UNDER_PREPARATION",
    "manuscriptsinpreparation": "UNDER_PREPARATION",
}

_STOP_HEADINGS = {
    "awards",
    "education",
    "employment",
    "experience",
    "fellowshipsandawards",
    "grants",
    "invitedpresentations",
    "patents",
    "presentations",
    "professionalexperience",
    "references",
    "referees",
    "researchandworkexperience",
    "researchplan",
    "studentsupervision",
    "teaching",
    "workexperience",
}


@dataclass(frozen=True, slots=True)
class PdfPageText:
    page_number: int
    plain_text: str
    layout_text: str
    source_label: str


@dataclass(frozen=True, slots=True)
class PublicationCandidate:
    applicant_name: str
    filename: str
    page_start: int
    page_end: int
    line_start: int
    line_end: int
    section_label: str
    status_hint: str
    raw_citation: str
    normalized_citation: str
    year: int | None
    segmentation_method: str


@dataclass(frozen=True, slots=True)
class DocumentExtractionAudit:
    source_path: str
    source_sha256: str
    page_count: int
    pages_scanned: int
    candidates: tuple[PublicationCandidate, ...]
    extraction_modes: tuple[str, ...]
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SourceLine:
    page: int
    number: int
    text: str
    indent: int


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _heading_key(value: str) -> str:
    return "".join(character for character in _fold(value) if character.isalnum())


def _normalize_spaced_years(value: str) -> str:
    pattern = re.compile(r"(?<!\d)([12])\s*([09])\s*([0-9])\s*([0-9])(?!\d)")
    return pattern.sub(lambda match: "".join(match.groups()), value)


def choose_page_text(plain_text: str, layout_text: str) -> tuple[str, str]:
    """Choose the extraction that best preserves both words and entry lines."""
    plain = plain_text or ""
    layout = layout_text or ""
    if not plain.strip():
        return layout, "layout"
    if not layout.strip():
        return plain, "plain"

    plain_lines = len(plain.splitlines())
    layout_lines = len(layout.splitlines())
    plain_tokens = len(plain.split())
    layout_tokens = len(layout.split())
    if plain_tokens >= 6 and layout_tokens < max(2, int(plain_tokens * 0.55)):
        return plain, "plain"
    if plain_lines <= 3 and layout_lines >= plain_lines + 4:
        return layout, "layout"
    return plain, "plain"


def _dedicated_publication_filename(filename: str) -> bool:
    key = _heading_key(Path(filename).stem)
    return "publication" in key or "publist" in key


def _heading(line: str) -> tuple[str, str] | None:
    stripped = line.strip().rstrip(":")
    if not stripped or len(stripped) > 90:
        return None
    key = _heading_key(stripped)
    status = _PUBLICATION_HEADINGS.get(key)
    return (stripped, status) if status is not None else None


def _is_stop_heading(line: str) -> bool:
    stripped = line.strip().rstrip(":")
    if not stripped or len(stripped) > 90:
        return False
    return _heading_key(stripped) in _STOP_HEADINGS


def _is_explanatory_line(line: str) -> bool:
    key = _heading_key(line)
    return (
        key.startswith("researchhighlight")
        or key.startswith("equalcontribution")
        or key.startswith("applicantnameshown")
        or ("papers" in key and "peerreviewed" in key and "typically" in key)
    )


def _repeated_furniture(pages: Sequence[tuple[int, str]]) -> set[str]:
    page_lines: list[set[str]] = []
    for _page_number, text in pages:
        nonempty = [line.strip() for line in text.splitlines() if line.strip()]
        edge = nonempty[:2] + nonempty[-2:]
        page_lines.append({_heading_key(line) for line in edge if len(line) <= 140})
    counts: dict[str, int] = {}
    for values in page_lines:
        for value in values:
            counts[value] = counts.get(value, 0) + 1
    return {value for value, count in counts.items() if value and count > 1}


def _author_variants(applicant_name: str) -> tuple[str, ...]:
    tokens = re.findall(r"[a-z0-9]+", _fold(applicant_name))
    if not tokens:
        return ()
    values = {tokens[-1]}
    if len(tokens) >= 2:
        values.add(" ".join(tokens[-2:]))
        values.add("".join(tokens[-2:]))
    return tuple(sorted((value for value in values if len(value) >= 5), key=len, reverse=True))


def _contains_applicant(raw: str, variants: Sequence[str]) -> bool:
    folded = " ".join(re.findall(r"[a-z0-9]+", _fold(raw)))
    joined = folded.replace(" ", "")
    return any(variant in folded or variant.replace(" ", "") in joined for variant in variants)


def _has_terminal_evidence(raw: str) -> bool:
    stripped = raw.strip()
    tail = stripped[-120:]
    years = list(_YEAR_RE.finditer(stripped))
    terminal_year = bool(
        years
        and len(stripped) - years[-1].end() <= 60
        and not (len(years) == 1 and years[0].start() <= 8)
    )
    return bool(
        terminal_year
        or re.search(r"(?i)(?:doi\s*:|https?://doi\.org/|arxiv\s*:|in\s+preparation)\S*\s*$", tail)
    )


def _looks_like_entry_start(line: str) -> bool:
    if _ENUMERATOR_RE.match(line) or _YEAR_COLUMN_RE.match(line):
        return True
    stripped = line.strip()
    prefix = stripped[:100]
    return bool(
        re.match(r"[A-ZÀ-ÖØ-Þ][\w'’.-]+\s+(?:[A-Z](?:[A-Z]|[.-])?\s*)[,;]", prefix)
        or ("," in prefix and re.search(r"\b[A-Z](?:[A-Z])?\b", prefix))
    )


def _join_lines(lines: Sequence[_SourceLine]) -> str:
    output = ""
    for source_line in lines:
        value = source_line.text.strip()
        value = _ENUMERATOR_RE.sub("", value, count=1)
        if not value:
            continue
        if output.endswith("-") and value[:1].islower():
            output = output[:-1] + value
        else:
            output = f"{output} {value}".strip()
    output = _normalize_spaced_years(output)
    return " ".join(output.split())


def _candidate_from_lines(
    lines: Sequence[_SourceLine],
    *,
    applicant_name: str,
    filename: str,
    section_label: str,
    status_hint: str,
    variants: Sequence[str],
    segmentation_method: str,
) -> PublicationCandidate | None:
    raw = _join_lines(lines)
    year_matches = [(int(match.group(0)), match.start()) for match in _YEAR_RE.finditer(raw)]
    year = year_matches[-1][0] if year_matches else None
    if status_hint == "UNDER_PREPARATION" and not (
        year_matches and year_matches[0][1] <= 8 and year_matches[0][0] >= 2000
    ):
        year = None
    year_optional = status_hint in {"ACCEPTED_PREPRINT", "UNDER_PREPARATION"}
    if (
        len(raw) < 40
        or (year is None and not year_optional)
        or not _contains_applicant(raw, variants)
    ):
        return None
    if raw.count(".") + raw.count(":") < 2:
        return None
    return PublicationCandidate(
        applicant_name=applicant_name,
        filename=filename,
        page_start=lines[0].page,
        page_end=lines[-1].page,
        line_start=lines[0].number,
        line_end=lines[-1].number,
        section_label=section_label,
        status_hint=status_hint,
        raw_citation=raw,
        normalized_citation=" ".join(_fold(raw).split()),
        year=year,
        segmentation_method=segmentation_method,
    )


def extract_candidates_from_pages(
    pages: Sequence[PdfPageText],
    *,
    applicant_name: str,
    filename: str,
) -> tuple[PublicationCandidate, ...]:
    """Detect publication sections and segment applicant-authored entries."""
    selected: list[tuple[int, str]] = []
    for page in pages:
        text, _mode = choose_page_text(page.plain_text, page.layout_text)
        selected.append((page.page_number, _normalize_spaced_years(text)))
    furniture = _repeated_furniture(selected)
    variants = _author_variants(applicant_name)
    dedicated = _dedicated_publication_filename(filename)

    candidates: list[PublicationCandidate] = []
    buffer: list[_SourceLine] = []
    section_label = "PUBLICATION_LIST" if dedicated else ""
    status_hint = "PUBLISHED" if dedicated else ""
    active = dedicated
    method = "section-boundary"

    def flush(reason: str) -> None:
        nonlocal buffer, method
        if buffer:
            candidate = _candidate_from_lines(
                buffer,
                applicant_name=applicant_name,
                filename=filename,
                section_label=section_label,
                status_hint=status_hint,
                variants=variants,
                segmentation_method=reason or method,
            )
            if candidate is not None:
                candidates.append(candidate)
        buffer = []
        method = reason

    for page_number, text in selected:
        for line_number, original in enumerate(text.splitlines(), start=1):
            stripped = original.strip()
            key = _heading_key(stripped)
            if (
                stripped
                and (key in furniture or _PAGE_NUMBER_RE.match(stripped))
                and _heading(stripped) is None
            ):
                continue
            heading = _heading(stripped)
            if heading is not None:
                flush("section-heading")
                section_label, status_hint = heading
                active = True
                continue
            if _is_stop_heading(stripped):
                flush("stop-heading")
                active = False
                continue
            if not active or _is_explanatory_line(stripped):
                continue
            if not stripped:
                if buffer and _has_terminal_evidence(_join_lines(buffer)):
                    flush("blank-group")
                continue

            current = _join_lines(buffer)
            strong_start = bool(_ENUMERATOR_RE.match(original) or _YEAR_COLUMN_RE.match(original))
            terminal_transition = bool(
                buffer and _has_terminal_evidence(current) and _looks_like_entry_start(original)
            )
            if buffer and (strong_start or terminal_transition):
                flush("enumerator-or-terminal-year")
            buffer.append(
                _SourceLine(page_number, line_number, original, len(original) - len(original.lstrip()))
            )
    flush("document-end")

    unique: dict[tuple[int, int, str], PublicationCandidate] = {}
    for candidate in candidates:
        key = (candidate.page_start, candidate.page_end, candidate.normalized_citation)
        unique.setdefault(key, candidate)
    return tuple(unique.values())


def extract_document(path: Path, applicant_name: str) -> DocumentExtractionAudit:
    """Extract one PDF without mutating it and return a complete audit envelope."""
    source_bytes = path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    issues: list[str] = []
    pages: list[PdfPageText] = []
    modes: list[str] = []
    try:
        reader = PdfReader(path, strict=False)
    except Exception as error:
        return DocumentExtractionAudit(
            str(path), source_hash, 0, 0, (), (), (f"UNREADABLE_PDF:{type(error).__name__}",)
        )

    for page_number, page in enumerate(reader.pages, start=1):
        try:
            plain = page.extract_text() or ""
        except Exception:
            plain = ""
        try:
            layout = page.extract_text(extraction_mode="layout") or ""
        except Exception:
            layout = ""
        _selected, mode = choose_page_text(plain, layout)
        modes.append(mode)
        pages.append(PdfPageText(page_number, plain, layout, str(path)))
    if not any((page.plain_text.strip() or page.layout_text.strip()) for page in pages):
        issues.append("NO_EXTRACTABLE_TEXT")
    candidates = extract_candidates_from_pages(
        pages, applicant_name=applicant_name, filename=path.name
    )
    return DocumentExtractionAudit(
        str(path), source_hash, len(reader.pages), len(pages), candidates, tuple(modes), tuple(issues)
    )


def extract_corpus(
    source_root: Path, applicant_names_by_folder: dict[str, str]
) -> tuple[DocumentExtractionAudit, ...]:
    """Audit every PDF below mapped applicant folders in deterministic order."""
    audits: list[DocumentExtractionAudit] = []
    for path in sorted(source_root.rglob("*.pdf"), key=lambda value: str(value).casefold()):
        relative = path.relative_to(source_root)
        if not relative.parts:
            continue
        applicant = applicant_names_by_folder.get(relative.parts[0])
        if applicant is None:
            continue
        audits.append(extract_document(path, applicant))
    return tuple(audits)


def iter_candidates(audits: Iterable[DocumentExtractionAudit]) -> Iterable[PublicationCandidate]:
    for audit in audits:
        yield from audit.candidates
