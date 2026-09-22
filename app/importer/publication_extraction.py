"""Layout-aware extraction of applicant-authored publication citations.

The module deliberately separates PDF/section/entry segmentation from
bibliographic field parsing.  Applicant documents are processed locally and
every candidate retains page-level provenance.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlsplit

import httpx
from pypdf import PdfReader


_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_YEAR_COLUMN_RE = re.compile(r"^\s*(?:19|20)\s*\d\s*\d\s+\S")
_ENUMERATOR_RE = re.compile(r"^\s*(?:[•●▪◦‣]|\d{1,3}[.)])\s+")
_BARE_ENUMERATOR_RE = re.compile(r"^\s*\d{1,3}\s+(?=[A-ZÀ-ÖØ-Þ])")
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
    "conferencepapers": "PUBLISHED",
    "conferenceworkshoppapers": "PUBLISHED",
    "journalandconferencepublications": "PUBLISHED",
    "additionalpublicationsinpeerreviewedscientificjournals": "PUBLISHED",
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
    "letterofrecommendation",
    "letterofsupport",
    "recommendationletter",
    "supportletter",
    "motivationletter",
    "coverletter",
    "patents",
    "peerreviewedbooks",
    "books",
    "bookchapter",
    "bookchapters",
    "presentations",
    "conferencepresentations",
    "selectedconferencepresentations",
    "professionalexperience",
    "references",
    "referees",
    "researchandworkexperience",
    "researchplan",
    "researchproposal",
    "researchstatement",
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
class ParsedPublication:
    authors: tuple[str, ...] = ()
    title: str | None = None
    journal: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    raw_citation: str = ""
    parser_method: str = "deterministic"
    field_evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PublicationClassification:
    disposition: str
    confidence: float
    reason: str


class GrobidCitationParser:
    """Adapter for a local-only GROBID processCitation service."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8070",
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        endpoint = base_url.rstrip("/")
        hostname = urlsplit(endpoint).hostname
        if hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("GROBID must use a loopback endpoint for applicant privacy.")
        self._endpoint = endpoint
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def parse(self, raw_citation: str) -> ParsedPublication:
        response = self._client.post(
            f"{self._endpoint}/api/processCitation",
            data={"citations": raw_citation},
            headers={"Accept": "application/xml"},
        )
        response.raise_for_status()
        return parse_grobid_tei(response.text, raw_citation=raw_citation)


@dataclass(frozen=True, slots=True)
class _SourceLine:
    page: int
    number: int
    text: str
    indent: int


_DOI_RE = re.compile(r"(?i)\b10\.\d{4,9}/[-._;()/:a-z0-9]+")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_INLINE_SECTION_PATTERNS = (
    (
        re.compile(
            r"(?i)\b(additional\s+publications\s+in\s+peer[- ]reviewed\s+scientific\s+journals)\s*:\s*$"
        ),
        "PUBLISHED",
    ),
    (
        re.compile(
            r"(?i)\b(unpublished\s+(?:work|manuscripts?)\s*(?:\([^)]*\))?)\s*:\s*"
        ),
        "UNDER_PREPARATION",
    ),
    (
        re.compile(r"(?i)\b(unpublished\s+manuscripts\b.*)$"),
        "ACCEPTED_PREPRINT",
    ),
)
_INLINE_STOP_PATTERNS = (
    re.compile(r"(?i)\b(INTELLECTUAL\s+PROPERTY)\b"),
)


def _clean_doi(value: str | None) -> str | None:
    match = _DOI_RE.search(value or "")
    if match is None:
        return None
    doi = match.group(0).rstrip(".,;)").casefold()
    suffix = doi.partition("/")[2]
    if len(suffix) < 4 or suffix.endswith(("-", "_", "/")):
        return None
    return doi


def _tei_text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = " ".join(" ".join(element.itertext()).split())
    return value or None


def _tei_first(root: ET.Element, expression: str) -> ET.Element | None:
    return root.find(expression, {"tei": "http://www.tei-c.org/ns/1.0"})


def parse_grobid_tei(xml: str, *, raw_citation: str = "") -> ParsedPublication:
    """Normalize GROBID's TEI citation response without relying on child order."""
    root = ET.fromstring(xml)
    if root.tag.endswith("TEI"):
        citation = _tei_first(root, ".//tei:biblStruct")
        if citation is not None:
            root = citation

    authors: list[str] = []
    for author in root.findall(".//tei:analytic/tei:author", {"tei": "http://www.tei-c.org/ns/1.0"}):
        person = _tei_first(author, ".//tei:persName")
        name = _tei_text(person if person is not None else author)
        if name:
            authors.append(name)

    title = _tei_text(_tei_first(root, ".//tei:analytic/tei:title[@level='a']"))
    journal = _tei_text(_tei_first(root, ".//tei:monogr/tei:title[@level='j']"))
    if journal is None:
        journal = _tei_text(_tei_first(root, ".//tei:monogr/tei:title"))

    def scope(unit: str) -> str | None:
        element = _tei_first(root, f".//tei:imprint/tei:biblScope[@unit='{unit}']")
        if element is None:
            return None
        value = _tei_text(element)
        if value:
            return value
        start = element.get("from")
        end = element.get("to")
        return f"{start}-{end}" if start and end else start or end

    date = _tei_first(root, ".//tei:imprint/tei:date[@type='published']")
    if date is None:
        date = _tei_first(root, ".//tei:imprint/tei:date")
    date_value = date.get("when") if date is not None else None
    if not date_value:
        date_value = _tei_text(date)
    year_match = _YEAR_RE.search(date_value or "")
    doi_element = _tei_first(root, ".//tei:idno[@type='DOI']")
    if doi_element is None:
        doi_element = _tei_first(root, ".//tei:idno[@type='doi']")
    doi = _clean_doi(_tei_text(doi_element))
    url = _tei_text(_tei_first(root, ".//tei:ptr[@type='web']"))
    if url is None:
        pointer = _tei_first(root, ".//tei:ptr")
        url = pointer.get("target") if pointer is not None else None
    evidence = tuple(
        name
        for name, value in (
            ("authors", authors),
            ("title", title),
            ("journal", journal),
            ("year", year_match),
            ("doi", doi),
        )
        if value
    )
    return ParsedPublication(
        authors=tuple(authors),
        title=title,
        journal=journal,
        volume=scope("volume"),
        issue=scope("issue"),
        pages=scope("page"),
        year=int(year_match.group(0)) if year_match else None,
        doi=doi,
        url=url,
        raw_citation=raw_citation,
        parser_method="grobid",
        field_evidence=evidence,
    )


def fallback_parse_candidate(candidate: PublicationCandidate) -> ParsedPublication:
    """Conservatively recover common author-title-venue-year citation fields."""
    raw = _clean_ocr_text(candidate.raw_citation.strip())
    parsed_year = candidate.year
    if (
        parsed_year is not None
        and parsed_year < 2000
        and re.search(
            r"(?i)\b(?:in\s+preparation|preprint|submitted|under\s+(?:review|revision)|in\s+revision|accepted\s+(?:in|for|by))\b",
            raw,
        )
    ):
        parsed_year = None
    raw_without_year_prefix = re.sub(r"^(?:19|20)\d{2}\s+", "", raw)
    doi = _clean_doi(raw_without_year_prefix)
    url_match = _URL_RE.search(raw_without_year_prefix)
    url = url_match.group(0).rstrip(".,;)") if url_match else None
    body = _DOI_RE.sub("", raw_without_year_prefix)
    body = _URL_RE.sub("", body)
    body = re.sub(r"(?i)\bdoi\s*:\s*", "", body)
    title: str | None = None
    journal: str | None = None
    comma_year = re.search(r"\s*\((?:19|20)\d{2}[^)]*\)\s*$", body)
    comma_parts = (
        body[: comma_year.start()].rstrip(" ,").rsplit(",", 2)
        if comma_year is not None
        else []
    )
    comma_style = bool(
        len(comma_parts) == 3
        and len(re.findall(r"[^\W\d_]{3,}", comma_parts[1], re.UNICODE)) >= 3
        and 2 <= len(comma_parts[2].strip()) <= 100
    )
    first_sentence = re.match(r"^(.{20,}?)\.\s+(.+)$", body)
    variants = _author_variants(candidate.applicant_name)
    if comma_style:
        author_text, title, journal = (part.strip(" ,;:") for part in comma_parts)
        citation_body = ""
    elif (
        first_sentence
        and len(re.findall(r"[^\W\d_]{3,}", first_sentence.group(1), re.UNICODE)) >= 4
        and first_sentence.group(1).count(",") < 2
        and not _contains_applicant(first_sentence.group(1), variants)
        and _contains_applicant(first_sentence.group(2), variants)
    ):
        title = first_sentence.group(1).strip(" ,;:")
        remainder = first_sentence.group(2)
        venue_matches = list(
            re.finditer(
                r"(?:^|\.\s+)([A-ZÀ-ÖØ-Þ][^.]{2,100}?)\.\s*(?=(?:19|20)\d{2}(?:\b|;))",
                remainder,
            )
        )
        if venue_matches:
            venue = venue_matches[-1]
            author_text = remainder[: venue.start()].strip(" .,;:")
            journal = venue.group(1).strip(" ,;:")
        else:
            comma_venue = re.search(
                r"\.\s+((?:eLife|iScience|npj\s+\S+|[A-ZÀ-ÖØ-Þ])[^.]{0,100}?),"
                r"\s*(?=(?:19|20)\d{2}\b)",
                remainder,
            )
            if comma_venue:
                author_text = remainder[: comma_venue.start()].strip(" .,;:")
                journal = comma_venue.group(1).strip(" ,;:")
            else:
                author_text = remainder
        citation_body = ""
    else:
        apa_year = re.search(r"\s*\((?:19|20)\d{2}\)\.?\s+", body)
        if apa_year:
            author_text = body[: apa_year.start()].rstrip(" .")
            citation_body = body[apa_year.end() :]
        else:
            colon = re.search(r"\s*:\s+", body)
            period = re.search(r"\.[*†‡#]*\s+(?=[A-Z])", body)
            if (
                colon
                and (period is None or colon.start() < period.start())
                and ("," in body[: colon.start()] or re.search(r"\band\b", body[: colon.start()], re.I))
            ):
                author_text, citation_body = body[: colon.start()], body[colon.end() :]
            else:
                first_period = re.match(r"^(.{5,}?)\.[*†‡#]*\s+(.+)$", body)
                if first_period:
                    author_text, citation_body = first_period.groups()
                else:
                    author_text, citation_body = body, ""
    segments = [
        part.strip(" ,;:")
        for part in re.split(r"\.\s+(?=[A-Z0-9])", citation_body)
        if part.strip(" ,;:")
    ]
    authors: tuple[str, ...] = ()
    if author_text:
        authors = tuple(
            part.strip()
            for part in re.split(r"\s*,\s*|\s+and\s+", author_text)
            if part.strip()
        )
    if title is None and segments:
        title = segments[0]
    if journal is None and len(segments) >= 2:
        journal = segments[1]
    if title and journal is None:
        trailing_venue = re.match(
            r"^(.+?)\.\s+((?:npj|eLife|iScience|bioRxiv|medRxiv)\b.+?)\.?$",
            title,
            re.IGNORECASE,
        )
        if trailing_venue:
            title, journal = (
                trailing_venue.group(1).strip(" ,;:"),
                trailing_venue.group(2).strip(" ,;:"),
            )
    if title:
        title = re.sub(
            r"(?i)^\s*(?:publication\s+list(?:\s*\(continued\))?\s+)?"
            r"(?:(?:research|review)\s+articles\s+)?",
            "",
            title,
        ).strip()
        title = re.sub(r"(?i)\bsubmitted\b\s*", "", title)
        title = re.sub(r"(?<!\w)#\d+\s*", "", title).strip()
    if journal:
        journal = journal.strip(" ,;:.")
        if not re.search(r"[^\W\d_]", journal, re.UNICODE):
            journal = None
    volume = issue = pages = None
    volume_match = re.search(
        r"(?<!\d)(\d{1,4})\s*(?:\(([^)]+)\))?\s*:\s*([A-Za-z]?\d+(?:\s*[-–]\s*[A-Za-z]?\d+)?)",
        raw_without_year_prefix,
    )
    if volume_match:
        volume = volume_match.group(1)
        issue = volume_match.group(2)
        pages = re.sub(r"\s+", "", volume_match.group(3)).replace("–", "-")
        if journal and volume_match.start() >= raw_without_year_prefix.find(journal):
            journal_volume = re.search(
                r"(?<!\d)\d{1,4}\s*(?:\([^)]+\))?\s*:\s*[A-Za-z]?\d+",
                journal,
            )
            if journal_volume:
                journal = journal[: journal_volume.start()].strip(" ,;:")
    evidence = tuple(
        name
        for name, value in (
            ("authors", authors),
            ("title", title),
            ("journal", journal),
            ("year", parsed_year),
            ("doi", doi),
        )
        if value
    )
    return ParsedPublication(
        authors=authors,
        title=title,
        journal=journal,
        volume=volume,
        issue=issue,
        pages=pages,
        year=parsed_year,
        doi=doi,
        url=url,
        raw_citation=raw,
        parser_method="deterministic",
        field_evidence=evidence,
    )


def classify_publication(
    publication: ParsedPublication, *, section_status: str = ""
) -> PublicationClassification:
    """Classify bibliographic evidence separately from identifier resolution."""
    raw = _fold(publication.raw_citation)
    if re.search(
        r"\b(?:(?:doctoral|phd|master'?s?|bachelor'?s?)\s+(?:degree\s+)?thesis|dissertation)\b",
        raw,
    ):
        return PublicationClassification("NON_PUBLICATION", 0.99, "explicit thesis or dissertation")
    if re.search(r"\b(?:patents?|intellectual\s+property)\b", raw) or re.search(
        r"(?i)\b(?:WO|EP|US)\d{6,}[A-Z]\d\b", publication.journal or ""
    ):
        return PublicationClassification("NON_PUBLICATION", 0.99, "explicit patent record")
    title_words = re.findall(r"[^\W\d_]{3,}", publication.title or "", re.UNICODE)
    title_key = "".join(
        character for character in _fold(publication.title or "") if character.isalnum()
    )
    author_initials = re.findall(r"\b[A-ZÀ-ÖØ-Þ]\s*\.", publication.title or "")
    author_fragment = bool(
        re.search(r",\s*[A-ZÀ-ÖØ-Þ]{1,3}\b", publication.title or "")
        or (publication.title or "").count(",") >= 3
        or re.match(
            r"(?i)^\s*[*#†§]*\s*:?[ ]*(?:contributed\s+equally|corresponding\s+author|co[- ]?supervised)",
            publication.title or "",
        )
    )
    administrative_title = bool(
        re.search(
            r"(?i)\b(?:anschrift|bankverbindung|postal\s+address|current\s+position|"
            r"curriculum\s+vitae|contact\s+details)\b",
            publication.title or "",
        )
    )
    title_quality = bool(
        publication.title
        and len(title_key) >= 8
        and title_words
        and len(author_initials) < 3
        and not author_fragment
        and not administrative_title
    )
    narrative = bool(
        re.search(
            r"\b(?:dear\s+(?:members|dr)|selection\s+committee|letter\s+of\s+support|"
            r"fellowship\s+application|outstanding\s+(?:candidate|research)|to\s+whom\s+it\s+may\s+concern)\b",
            raw,
        )
    )
    venue_quality = bool(
        publication.journal
        and len(re.findall(r"[^\W\d_]{2,}", publication.journal, re.UNICODE)) >= 1
        and len(publication.journal.strip()) >= 3
    )
    quality_failure = not title_quality or narrative
    if re.search(r"\bin\s+preparation\b|\bmanuscript\s+in\s+preparation\b", raw):
        if quality_failure:
            return PublicationClassification("PENDING_REVIEW", 0.2, "low-quality title or narrative context")
        return PublicationClassification("UNDER_PREPARATION", 0.99, "explicit in-preparation status")
    preprint_signal = re.search(
        r"\b(?:preprint|biorxiv|medrxiv|arxiv|ssrn|submitted|under\s+(?:review|revision)|in\s+(?:review|revision)|accepted\s+(?:in|for|by)|forthcoming|revised\s+and\s+resubmitted)\b",
        raw,
    )
    if preprint_signal or section_status == "ACCEPTED_PREPRINT":
        if quality_failure:
            return PublicationClassification("PENDING_REVIEW", 0.2, "low-quality title or narrative context")
        return PublicationClassification("ACCEPTED_PREPRINT", 0.97, "explicit preprint or review status")
    if section_status == "UNDER_PREPARATION":
        if quality_failure:
            return PublicationClassification("PENDING_REVIEW", 0.2, "low-quality title or narrative context")
        return PublicationClassification("UNDER_PREPARATION", 0.95, "in-preparation section")

    missing: list[str] = []
    if not publication.authors:
        missing.append("authors")
    if not publication.title:
        missing.append("title")
    if not publication.journal:
        missing.append("journal")
    elif not venue_quality:
        missing.append("credible journal or proceedings venue")
    if publication.year is None:
        missing.append("year")
    if not title_quality:
        missing.append("credible title")
    if narrative:
        missing.append("non-narrative citation context")
    if not missing:
        return PublicationClassification(
            "PUBLISHED", 0.96, "authors, title, venue, and publication year present"
        )
    return PublicationClassification(
        "PENDING_REVIEW",
        0.35,
        "; ".join(f"missing {field}" for field in missing),
    )


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _clean_ocr_text(value: str) -> str:
    return value.translate(
        str.maketrans({"Ɵ": "ti", "Ʃ": "tt", "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff"})
    )


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
    plain_blank_lines = sum(not line.strip() for line in plain.splitlines())
    layout_blank_lines = sum(not line.strip() for line in layout.splitlines())
    if plain_tokens >= 6 and layout_tokens < max(2, int(plain_tokens * 0.55)):
        return plain, "plain"
    if plain_lines <= 3 and layout_lines >= plain_lines + 4:
        return layout, "layout"
    if (
        layout_tokens >= int(plain_tokens * 0.9)
        and layout_lines >= plain_lines + 2
        and layout_blank_lines >= plain_blank_lines + 2
    ):
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
        or key.startswith("authorscontributedequally")
        or key.startswith("applicantnameshown")
        or (key.startswith("conferencepublications") and "archival" in key)
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
        values.add(" ".join(tokens[:2]))
        values.add("".join(tokens[:2]))
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
        or re.search(
            r"(?i)(?:doi\s*:|https?://doi\.org/|arxiv\s*:|in\s+preparation|under\s+(?:review|revision)|in\s+review|accepted\s+(?:in|for|by)\b)[^\n]*$",
            tail,
        )
        or re.search(
            r"(?i)\b\d{1,4}\s*(?:\([^)]+\))?\s*[,:]\s*(?:[a-z]\d{3,}|\d+(?:\s*[-–]\s*\d+)?)\.?"
            r"(?:\s*\([^)]*(?:equal|contribut)[^)]*\))?\s*$",
            tail,
        )
    )


def _looks_like_entry_start(line: str) -> bool:
    if _ENUMERATOR_RE.match(line) or _BARE_ENUMERATOR_RE.match(line) or _YEAR_COLUMN_RE.match(line):
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
        value = _BARE_ENUMERATOR_RE.sub("", value, count=1)
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
    inherited_year: int | None = None,
) -> PublicationCandidate | None:
    raw = _join_lines(lines)
    year_matches = [(int(match.group(0)), match.start()) for match in _YEAR_RE.finditer(raw)]
    year = year_matches[0][0] if year_matches else inherited_year
    if status_hint == "UNDER_PREPARATION" and not (
        year_matches and year_matches[0][1] <= 8 and year_matches[0][0] >= 2000
    ):
        year = None
    inline_unpublished = re.search(
        r"(?i)\b(?:in\s+preparation|preprint|submitted|under\s+(?:review|revision)|in\s+revision|accepted\s+(?:in|for|by))\b",
        raw,
    )
    year_optional = status_hint in {"ACCEPTED_PREPRINT", "UNDER_PREPARATION"} or bool(
        inline_unpublished
    )
    if (
        len(raw) < 40
        or (year is None and not year_optional)
        or not _contains_applicant(raw, variants)
    ):
        return None
    if "orcid.org/" in raw.casefold() and ("@" in raw or "postdoctoral" in raw.casefold()):
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
    column_year: int | None = None

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
                inherited_year=column_year,
            )
            if candidate is not None:
                candidates.append(candidate)
        buffer = []
        method = reason

    for page_number, text in selected:
        for line_number, original in enumerate(text.splitlines(), start=1):
            stripped = original.strip()
            inline_stop = next(
                (match for pattern in _INLINE_STOP_PATTERNS if (match := pattern.search(original))),
                None,
            )
            if active and inline_stop is not None:
                prefix = original[: inline_stop.start()].strip()
                if prefix:
                    buffer.append(
                        _SourceLine(page_number, line_number, prefix, len(original) - len(original.lstrip()))
                    )
                flush("inline-stop-heading")
                active = False
                column_year = None
                continue
            inline_section = next(
                (
                    (match, inline_status)
                    for pattern, inline_status in _INLINE_SECTION_PATTERNS
                    if (match := pattern.search(original)) is not None
                ),
                None,
            )
            if active and inline_section is not None:
                inline_heading, inline_status = inline_section
                prefix = original[: inline_heading.start()].strip()
                suffix = original[inline_heading.end() :].strip()
                if prefix:
                    buffer.append(
                        _SourceLine(page_number, line_number, prefix, len(original) - len(original.lstrip()))
                    )
                flush("inline-section-heading")
                section_label = inline_heading.group(1)
                status_hint = inline_status
                active = True
                if suffix:
                    buffer.append(
                        _SourceLine(page_number, line_number, suffix, len(original) - len(original.lstrip()))
                    )
                continue
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
                column_year = None
                continue
            if _is_stop_heading(stripped):
                flush("stop-heading")
                active = False
                column_year = None
                continue
            if not active or _is_explanatory_line(stripped):
                continue
            if not stripped:
                if buffer and _has_terminal_evidence(_join_lines(buffer)):
                    flush("blank-group")
                continue

            current = _join_lines(buffer)
            strong_start = bool(
                _ENUMERATOR_RE.match(original)
                or _BARE_ENUMERATOR_RE.match(original)
                or _YEAR_COLUMN_RE.match(original)
            )
            terminal_transition = bool(
                buffer and _has_terminal_evidence(current) and _looks_like_entry_start(original)
            )
            if buffer and (strong_start or terminal_transition):
                flush("enumerator-or-terminal-year")
            if _YEAR_COLUMN_RE.match(original):
                year_match = _YEAR_RE.search(_normalize_spaced_years(original[:20]))
                if year_match is not None:
                    column_year = int(year_match.group(0))
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
