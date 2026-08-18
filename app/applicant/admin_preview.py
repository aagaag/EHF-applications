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
        _section(code, title, description, values[code], first=index == 0)
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
    code: str, title: str, description: str, values: dict[str, Any], *, first: bool
) -> str:
    fields = "".join(
        _field(field, values.get(field.code))
        for field in FIELD_INVENTORY
        if field.section == code
    )
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
