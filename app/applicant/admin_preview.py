"""Read-only rendering of an applicant record for authorized administrators."""

from __future__ import annotations

from html import escape
from typing import Any

from app.applicant.approval import ApplicantPreviewBundle
from app.applicant.fields import FIELD_INVENTORY, FieldDefinition, upgrade_legacy_applicant, upgrade_legacy_section
from app.navigation import INTERNAL_GROUPS


_SECTIONS = (
    ("identity", "Identity and contact", "Check the personal and contact details registered for this application."),
    ("employment", "UZH employment and eligibility", "Check the current or future UZH position and call-specific eligibility information."),
    ("qualifications", "Qualifications and academic age", "Check each degree and its date of conferral."),
    ("publications", "Publications and identifiers", "Check publication counts, identifiers, and publications listed by DOI."),
    ("contribution", "Scientific contribution", "Check the applicant's statement of their most important scientific contribution."),
)


def render_applicant_preview(bundle: ApplicantPreviewBundle) -> str:
    values = _section_values(bundle)
    navigation = "".join(
        f'<button class="app-nav-link review-nav-link" type="button" data-section-target="{code}">{escape(title)}</button>'
        for code, title, _description in _SECTIONS
    )
    sections = "".join(
        _section(
            code,
            title,
            description,
            values[code],
            publication_records=(
                bundle.publication_records if code == "publications" else ()
            ),
            first=index == 0,
        )
        for index, (code, title, description) in enumerate(_SECTIONS)
    )
    administrator_group = escape(INTERNAL_GROUPS.administrators)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer"><title>EHF Fellowships — applicant viewpoint</title><link rel="stylesheet" href="/assets/site.css"></head>
<body data-shell><a class="skip-link" href="#main-content">Skip to main content</a>
<button class="app-nav-toggle" type="button" aria-controls="application-navigation" aria-expanded="false" aria-label="Open application navigation"><span aria-hidden="true">☰</span> Menu</button><div class="app-nav-backdrop" hidden></div>
<aside class="app-nav" id="application-navigation" aria-label="Application navigation" data-open="false" inert>
<div class="app-nav-top"><a class="app-nav-home" href="/internal/applicant-review"><img src="/assets/isab-logo.svg" alt="ISAB"><span class="app-nav-title">EHF Fellowships</span></a><span class="app-nav-domain">ehf.isab.science</span><span class="app-nav-purpose">Inspect an existing application as the applicant would see it.</span></div>
<div class="app-nav-scroll"><nav class="app-nav-list" aria-label="Application sections"><a class="app-nav-link" href="/internal/applicant-review#viewpoints">Back to applicant review</a>{navigation}</nav></div>
<nav class="app-nav-list app-nav-lower" aria-label="Settings and help navigation"><span class="app-nav-heading">Settings</span><a class="app-nav-link" href="#appearance">Appearance</a><a class="app-nav-link" href="#help">Help</a><div class="app-nav-authorizations"><strong>Authorizations:</strong><span class="app-nav-authorization-pills"><span class="app-nav-authorization-pill group-pill-1">{administrator_group}</span></span></div></nav></aside>
<main class="site-main applicant-review-main" id="main-content" tabindex="-1">
<header class="site-hero"><h1>{escape(bundle.applicant_name)}</h1><p>Application status: {escape(bundle.application_status)}</p></header>
<div class="preview-notice" role="status"><strong>Read-only administrator preview</strong><span>This displays the saved application through the applicant form. It does not sign you in as the applicant and nothing on this page can change the record.</span></div>
{sections}
<section id="help" class="section-heading"><h2>Help</h2><p>Use the section controls to inspect the complete saved form. Applicant edits, document uploads, confirmations, and final submission remain available only through the applicant's own Entra-scoped session.</p></section>
<section id="appearance" aria-labelledby="appearance-heading"><div class="section-heading"><h2 id="appearance-heading">Appearance</h2><p>Choose the display that is most comfortable for you. Your preference is stored securely for your administrator identity.</p></div>{_appearance_controls()}</section>
</main><script src="/assets/theme.js"></script><script src="/assets/shell.js"></script><script src="/assets/applicant-preview.js"></script></body></html>"""


def _section_values(bundle: ApplicantPreviewBundle) -> dict[str, dict[str, Any]]:
    applicant = bundle.baseline.get("applicant", {})
    baseline = upgrade_legacy_applicant(applicant if isinstance(applicant, dict) else {})
    result: dict[str, dict[str, Any]] = {}
    for code, _title, _description in _SECTIONS:
        current = {
            field.code: baseline.get(field.code)
            for field in FIELD_INVENTORY
            if field.section == code
        }
        draft = bundle.drafts.get(code)
        if isinstance(draft, dict):
            current.update(upgrade_legacy_section(code, draft))
        result[code] = current
    return result


def _section(
    code: str,
    title: str,
    description: str,
    values: dict[str, Any],
    *,
    publication_records: tuple[Any, ...],
    first: bool,
) -> str:
    fields = "".join(
        _field(field, values.get(field.code))
        for field in FIELD_INVENTORY
        if field.section == code
    )
    if code == "publications":
        fields += _publication_records(publication_records)
    hidden = "" if first else " hidden"
    return (
        f'<section class="review-section" data-review-section="{code}" aria-labelledby="{code}-heading"{hidden}>'
        f'<div class="section-heading"><h2 id="{code}-heading">{escape(title)}</h2><p>{escape(description)}</p></div>'
        f'<div class="review-form"><div class="review-fields review-fields-{code}">{fields}</div></div></section>'
    )


def _field(field: FieldDefinition, value: Any) -> str:
    if field.kind == "degree_list":
        rows = value if isinstance(value, list) else []
        body = "".join(_degree_row(row, index) for index, row in enumerate(rows))
        if not body:
            body = '<p class="field-help">No degrees recorded.</p>'
        return f'<fieldset class="repeatable-field review-field-wide"><legend>{escape(field.label)}</legend><div class="repeatable-rows">{body}</div></fieldset>'
    if field.kind == "publication_list":
        rows = value if isinstance(value, list) else []
        body = "".join(_publication_row(row) for row in rows)
        if not body:
            body = '<p class="field-help">No publications recorded.</p>'
        return f'<fieldset class="repeatable-field review-field-wide"><legend>{escape(field.label)}</legend><div class="repeatable-rows">{body}</div></fieldset>'
    rendered = _display_value(value)
    field_id = f"preview-{field.section}-{field.code}"
    wide = " review-field-wide" if field.kind == "textarea" else ""
    help_text = f'<span class="field-help">{escape(field.help)}</span>' if field.help else ""
    if field.kind == "textarea":
        control = f'<textarea id="{field_id}" name="{field.code}" rows="9" readonly>{escape(rendered)}</textarea>'
    else:
        input_type = "email" if field.kind == "email" else "text"
        control = f'<input id="{field_id}" name="{field.code}" type="{input_type}" value="{escape(rendered, quote=True)}" readonly>'
    return f'<div class="review-field review-field-{field.code}{wide}"><label for="{field_id}">{escape(field.label)}</label>{control}{help_text}</div>'


def _degree_row(row: Any, index: int) -> str:
    item = row if isinstance(row, dict) else {}
    degree_type = _display_value(item.get("degreeType"))
    date = _display_value(item.get("conferralDate"))
    return (
        f'<div class="degree-row"><div class="review-field"><label for="preview-degree-{index}-type">Degree</label>'
        f'<input id="preview-degree-{index}-type" type="text" value="{escape(degree_type, quote=True)}" readonly></div>'
        f'<div class="review-field"><label for="preview-degree-{index}-date">Date of conferral</label>'
        f'<input id="preview-degree-{index}-date" type="text" value="{escape(date, quote=True)}" readonly></div></div>'
    )


def _publication_row(row: Any) -> str:
    item = row if isinstance(row, dict) else {}
    doi = _display_value(item.get("doi"))
    return f'<div class="publication-row"><span class="publication-summary"><strong>DOI</strong><span>{escape(doi)}</span></span></div>'


def _publication_records(records: tuple[Any, ...]) -> str:
    rows = "".join(_publication_record(record) for record in records)
    if not rows:
        rows = '<p class="field-help">No imported publication records.</p>'
    headings = "".join(
        f"<span>{escape(label)}</span>"
        for label in (
            "First author",
            "Authors",
            "Title",
            "Journal, volume and pages",
            "Citations by source",
        )
    )
    return (
        '<fieldset class="repeatable-field review-field-wide publication-records-field">'
        '<legend>Publication records</legend>'
        '<p class="field-help publication-record-help">Double-click a paper to open it in Google Scholar. The complete row is also keyboard accessible.</p>'
        f'<div class="publication-records"><div class="publication-records-header" aria-hidden="true">{headings}</div>{rows}</div>'
        '</fieldset>'
    )


def _publication_record(record: Any) -> str:
    authors = _optional_display(getattr(record, "authors_text", None))
    first_author = _first_author(authors)
    title = _optional_display(getattr(record, "title", None))
    citation = _scientific_citation(record)
    citation_count = _citation_counts(record)
    scholar_url = str(getattr(record, "google_scholar_url", ""))
    label = f"Open {title} in Google Scholar"
    fields = "".join(
        _publication_record_field(field_label, value)
        for field_label, value in (
            ("First author", first_author),
            ("Authors", authors),
            ("Title", title),
            ("Journal, volume and pages", citation),
            ("Citations by source", citation_count),
        )
    )
    return (
        '<div class="publication-record" data-publication-record '
        f'data-google-scholar-url="{escape(scholar_url, quote=True)}" '
        f'role="link" tabindex="0" aria-label="{escape(label, quote=True)}" '
        'title="Double-click to open this paper in Google Scholar">'
        f"{fields}</div>"
    )


def _publication_record_field(label: str, value: str) -> str:
    return (
        '<span class="publication-record-field" data-publication-field>'
        f'<span class="publication-record-label">{escape(label)}</span>'
        f'<span>{escape(value)}</span></span>'
    )


def _optional_display(value: Any) -> str:
    if value is None or not str(value).strip():
        return "Missing"
    return str(value).strip()


def _first_author(authors: str) -> str:
    if authors == "Missing":
        return authors
    return authors.split(";", 1)[0].strip() or "Missing"


def _scientific_citation(record: Any) -> str:
    journal = _optional_value(getattr(record, "journal_text", None))
    volume = _optional_value(getattr(record, "volume_text", None))
    pages = _optional_value(getattr(record, "pages_text", None))
    year_value = getattr(record, "publication_year", None)
    year = str(year_value) if year_value is not None else ""
    locus = year
    if volume:
        locus += (";" if locus else "") + volume
    if pages:
        locus += (":" if locus else "") + pages
    parts = [part for part in (journal, locus) if part]
    return ". ".join(parts) + ("." if parts else "Missing")


def _scholar_citation_count(record: Any) -> str:
    count = getattr(record, "citation_count", None)
    if count is not None:
        return str(count)
    if getattr(record, "citation_status", None) == "MANUAL_REQUIRED":
        return "Pending manual review"
    return "Not available"


def _citation_counts(record: Any) -> str:
    if hasattr(record, "openalex_citation_status") or hasattr(
        record, "semantic_scholar_citation_status"
    ):
        openalex_count = getattr(record, "openalex_citation_count", None)
        openalex_status = getattr(record, "openalex_citation_status", None)
        semantic_scholar = _citation_source_value(
            getattr(record, "semantic_scholar_citation_count", None),
            getattr(record, "semantic_scholar_citation_status", None),
        )
        google_scholar = _scholar_citation_count(record)
        parts = [f"Google Scholar: {google_scholar}"]
        if openalex_count is not None or openalex_status is not None:
            openalex = _citation_source_value(openalex_count, openalex_status)
            parts.append(f"OpenAlex: {openalex}")
        parts.append(f"Semantic Scholar: {semantic_scholar}")
        return "; ".join(parts)
    return f"Google Scholar: {_scholar_citation_count(record)}"


def _citation_source_value(count: Any, status: Any) -> str:
    if count is not None:
        return str(count)
    if status == "NOT_FOUND":
        return "Not found"
    if status == "MANUAL_REQUIRED":
        return "Pending review"
    return "Not available"


def _optional_value(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _display_value(value: Any) -> str:
    if value is None or value == "":
        return "Missing"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _appearance_controls() -> str:
    return (
        '<div class="appearance-controls"><div class="appearance-control-row">'
        '<button type="button" data-skin-choice="default" aria-pressed="true">Production default</button>'
        '<button type="button" data-skin-choice="high-contrast" aria-pressed="false">High contrast</button>'
        '<button type="button" data-skin-choice="soft-earth" aria-pressed="false">Soft green/brown</button>'
        '<button type="button" data-skin-choice="blue" aria-pressed="false">Blue</button></div>'
        '<div class="appearance-control-row"><button type="button" data-appearance-flag="invert" aria-pressed="false">Invert colours</button>'
        '<button type="button" data-appearance-flag="compact" aria-pressed="false">Compact spacing</button>'
        '<button type="button" data-appearance-flag="reduceMotion" aria-pressed="false">Reduce motion</button>'
        '</div></div>'
    )
