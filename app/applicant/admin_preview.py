"""Read-only rendering of an applicant record for authorized administrators."""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlsplit

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


def render_applicant_preview(
    bundle: ApplicantPreviewBundle,
    *,
    primary_navigation: str | None = None,
    help_navigation: str | None = None,
    authorization_pills: str | None = None,
    back_href: str | None = None,
) -> str:
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
    if primary_navigation is None:
        from app.identity import AuthenticatedIdentity
        from app.internal_shell import (
            authorization_pills as render_authorization_pills,
            help_navigation as render_help_navigation,
            primary_navigation as render_primary_navigation,
        )
        from app.preferences import Identity

        principal = AuthenticatedIdentity(
            Identity("preview:administrator", "preview@example.invalid", "Administrator"),
            frozenset({INTERNAL_GROUPS.administrators}),
        )
        primary_navigation = render_primary_navigation(principal)
        help_navigation = render_help_navigation(principal)
        authorization_pills = render_authorization_pills(principal)
    assert help_navigation is not None and authorization_pills is not None
    safe_back_href = _safe_back_href(back_href)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer"><title>EHF Fellowships — applicant viewpoint</title><link rel="stylesheet" href="/assets/site.css"></head>
<body data-shell><a class="skip-link" href="#main-content">Skip to main content</a>
<button class="app-nav-toggle" type="button" aria-controls="application-navigation" aria-expanded="false" aria-label="Open application navigation"><span aria-hidden="true">☰</span> Menu</button><div class="app-nav-backdrop" hidden></div>
<aside class="app-nav" id="application-navigation" aria-label="Application navigation" data-open="false" inert>
<div class="app-nav-top"><a class="app-nav-home" href="/internal/"><img src="/assets/ehf-logo.svg" alt="Ernst Hadorn Foundation"><span class="app-nav-title">EHF Fellowships</span></a><span class="app-nav-domain">ehf.isab.science</span><span class="app-nav-purpose">Review fellowship applications in one secure workspace.</span></div>
<div class="app-nav-scroll"><nav class="app-nav-list" aria-label="Primary navigation">{primary_navigation}</nav></div>
<nav class="app-nav-list app-nav-lower" aria-label="Settings and help navigation"><span class="app-nav-heading">Settings</span><a class="app-nav-link" href="#appearance">Appearance</a><button class="app-nav-disclosure" type="button" data-disclosure aria-expanded="false" aria-controls="help-links">Help</button><div class="app-nav-submenu" id="help-links" hidden>{help_navigation}</div>{authorization_pills}</nav></aside>
<main class="site-main applicant-review-main" id="main-content" tabindex="-1">
<header class="site-hero"><h1>{escape(bundle.applicant_name)}</h1><p>Application status: {escape(bundle.application_status)}</p></header>
<div class="preview-notice" role="status"><strong>Read-only administrator preview</strong><span>This displays the saved application through the applicant form. It does not sign you in as the applicant and nothing on this page can change the record.</span></div>
<nav class="applicant-detail-tabs" aria-label="Applicant details"><a href="#summary">Summary</a><a href="#applicant-information">Applicant information</a><a href="#documents">Documents</a><a href="#access-identity">Access &amp; identity</a><a href="#internal-audit">Internal audit</a></nav>
<section id="summary" class="section-heading"><h2>Summary</h2><p><a href="{escape(safe_back_href, quote=True)}">Back to applicants</a>. Use the sections below to inspect this record without entering the applicant session.</p></section>
<section id="applicant-information" aria-labelledby="applicant-information-heading"><div class="section-heading"><h2 id="applicant-information-heading">Applicant information</h2><p>Saved form values and independently reviewed publication evidence.</p></div><nav class="applicant-section-tabs" aria-label="Application information sections">{navigation}</nav>{sections}</section>
<section id="documents" class="section-heading"><h2>Documents</h2><p>Study each original approved submission or open one freshly rebuilt PDF package containing all approved applicant-visible documents.</p><div class="internal-document-list" data-internal-documents data-application-id="{bundle.application_id}"><p role="status">Loading submitted documents…</p></div></section>
<section id="access-identity" class="section-heading"><h2>Access &amp; identity</h2><p>Identity provisioning and access decisions remain in the review queue.</p></section>
<section id="internal-audit" class="section-heading"><h2>Internal audit</h2><p>Opening this applicant workspace is recorded in the append-only audit log.</p></section>
<section id="help" class="section-heading"><h2>Help</h2><p>Use the section controls to inspect the complete saved form. Applicant edits, document uploads, confirmations, and final submission remain available only through the applicant's own Entra-scoped session.</p></section>
<section id="appearance" aria-labelledby="appearance-heading"><div class="section-heading"><h2 id="appearance-heading">Appearance</h2><p>Choose the display that is most comfortable for you. Your preference is stored securely for your administrator identity.</p></div>{_appearance_controls()}</section>
</main><script src="/assets/theme.js"></script><script src="/assets/shell.js"></script><script src="/assets/applicant-preview.js"></script></body></html>"""


def _safe_back_href(value: str | None) -> str:
    if not value or len(value) > 2048:
        return "/internal/applicant-previews"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path != "/internal/applicant-previews":
        return "/internal/applicant-previews"
    return value


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
        if code == "qualifications":
            current["degrees"] = _with_recovered_phd_conferral_year(
                current.get("degrees"),
                baseline.get("phdConferralYear"),
            )
        result[code] = current
    return result


def _with_recovered_phd_conferral_year(
    values: Any, recovered_year: Any
) -> list[dict[str, Any]]:
    """Expose a legacy academic-age-derived year without representing it as a date."""
    year = _recovered_year(recovered_year)
    if year is None or not isinstance(values, list):
        return values if isinstance(values, list) else []
    rows: list[dict[str, Any]] = []
    for value in values:
        row = dict(value) if isinstance(value, dict) else {}
        if row.get("degreeType") == "PhD" and not row.get("conferralDate"):
            row["conferralYear"] = year
        rows.append(row)
    return rows


def _recovered_year(value: Any) -> int | None:
    if type(value) is int:
        year = value
    elif isinstance(value, str) and len(value) == 4 and value.isascii() and value.isdigit():
        year = int(value)
    else:
        return None
    return year if 1900 <= year <= 2200 else None


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
    if date == "Missing":
        year = item.get("conferralYear")
        if isinstance(year, int) and 1900 <= year <= 2200:
            date = f"{year} (year recorded; full date unavailable)"
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
            "Resolution and review",
            "Citations by source",
        )
    )
    return (
        '<fieldset class="repeatable-field review-field-wide publication-records-field">'
        '<legend>Publication records</legend>'
        '<p class="field-help publication-record-help">Double-click a paper to open its DOI record. The complete row is also keyboard accessible.</p>'
        f'<div class="publication-records"><div class="publication-records-header" aria-hidden="true">{headings}</div>{rows}</div>'
        '</fieldset>'
    )


def _publication_record(record: Any) -> str:
    resolved = getattr(record, "resolution_status", None) == "RESOLVED"
    absent_metadata = "Not resolved" if not resolved else "Not recorded"
    authors = _publication_metadata_display(getattr(record, "authors_text", None), absent_metadata)
    first_author = _first_author(authors)
    title = _publication_metadata_display(getattr(record, "title", None), absent_metadata)
    citation = _scientific_citation(record)
    citation_count = _citation_counts(record)
    publication_url = str(getattr(record, "publication_url", "") or "")
    review = _publication_review(record)
    fields = "".join(
        _publication_record_field(field_label, value)
        for field_label, value in (
            ("First author", first_author),
            ("Authors", authors),
            ("Title", title),
            ("Journal, volume and pages", citation),
            ("Resolution and review", review),
            ("Citations by source", citation_count),
        )
    )
    interactive = ""
    if publication_url:
        label = f"Open {title} publication"
        interactive = (
            f'data-publication-url="{escape(publication_url, quote=True)}" '
            f'role="link" tabindex="0" aria-label="{escape(label, quote=True)}" '
            'title="Double-click to open this publication"'
        )
    return (
        '<div class="publication-record" data-publication-record '
        f"{interactive}>"
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


def _publication_metadata_display(value: Any, absent: str) -> str:
    if value is None or not str(value).strip():
        return absent
    return str(value).strip()


def _first_author(authors: str) -> str:
    if authors in {"Missing", "Not resolved", "Not recorded"}:
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
    if parts:
        return ". ".join(parts) + "."
    return "Not resolved" if getattr(record, "resolution_status", None) != "RESOLVED" else "Not recorded"


def _publication_review(record: Any) -> str:
    resolution = str(getattr(record, "resolution_status", None) or "UNRESOLVED")
    disposition = str(getattr(record, "review_disposition", None) or "PENDING_REVIEW")
    disposition_label = {
        "ACCEPTED_PREPRINT": "ACCEPTED / PREPRINT",
    }.get(disposition, disposition.replace("_", " "))
    summary = f"{resolution.replace('_', ' ')} · {disposition_label}"
    reason = _optional_value(getattr(record, "review_reason", None))
    evidence = _optional_value(getattr(record, "review_evidence", None))
    source = _optional_value(getattr(record, "source_citation", None))
    page = getattr(record, "source_page", None)
    detail_parts = [part for part in (reason, evidence) if part]
    if source:
        locator = f"Dossier page {page}: " if page is not None else "Source record: "
        detail_parts.append(locator + source)
    return summary + (" — " + " ".join(detail_parts) if detail_parts else "")


def _scholar_citation_count(record: Any) -> str:
    count = getattr(record, "citation_count", None)
    if count is not None:
        return str(count)
    if getattr(record, "citation_status", None) == "MANUAL_REQUIRED":
        return "Pending manual review"
    return "Not available"


def _citation_counts(record: Any) -> str:
    openalex = _citation_source_value(
        getattr(record, "openalex_citation_count", None),
        getattr(record, "openalex_citation_status", None),
    )
    return f"OpenAlex: {openalex}"


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
