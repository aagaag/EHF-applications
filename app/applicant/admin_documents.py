"""Read-only rendering of an applicant's proposal documents for administrators."""

from __future__ import annotations

from html import escape

from app.applicant.approval import ApplicantPreviewDocument, ApplicantPreviewDocuments
from app.navigation import INTERNAL_GROUPS


DOCUMENT_TYPE_LABELS = {
    "CV": "Curriculum vitae",
    "COVER_LETTER": "Cover letter",
    "RESEARCH_PLAN": "Research plan",
    "PUBLICATION_LIST": "Publication list",
    "RECOMMENDATION_LETTER": "Recommendation letter",
    "OTHER": "Dossier document",
}
DOCUMENT_TYPE_FILENAMES = {
    "CV": "curriculum-vitae",
    "COVER_LETTER": "cover-letter",
    "RESEARCH_PLAN": "research-plan",
    "PUBLICATION_LIST": "publication-list",
    "RECOMMENDATION_LETTER": "recommendation-letter",
    "OTHER": "dossier-document",
}
CONFIDENTIAL_DOCUMENT_TYPES = frozenset({"RECOMMENDATION_LETTER"})


def document_type_label(document_type: str) -> str:
    return DOCUMENT_TYPE_LABELS.get(document_type, "Dossier document")


def document_preview_filename(document_type: str, slot_code: str) -> str:
    """Return a stable, safe attachment name for one proposal PDF."""
    stem = DOCUMENT_TYPE_FILENAMES.get(document_type, "dossier-document")
    suffix = "".join(
        character for character in slot_code if character.isascii() and character.isalnum()
    )
    if not suffix:
        return f"{stem}.pdf"
    return f"{stem}-{suffix[-12:].lower()}.pdf"


def render_applicant_documents(bundle: ApplicantPreviewDocuments) -> str:
    """Render every active proposal PDF of one applicant as one complete control."""
    administrator_group = escape(INTERNAL_GROUPS.administrators)
    controls = "".join(_document_control(document) for document in bundle.documents)
    if controls:
        body = f'<div class="shell-grid preview-documents">{controls}</div>'
    else:
        body = (
            '<p role="status">No proposal documents are available for this application yet. '
            "Documents appear here once an imported or uploaded PDF becomes the active "
            "version of a document slot.</p>"
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer"><title>EHF Fellowships — applicant documents</title><link rel="stylesheet" href="/assets/site.css"></head>
<body data-shell><a class="skip-link" href="#main-content">Skip to main content</a>
<button class="app-nav-toggle" type="button" aria-controls="application-navigation" aria-expanded="false" aria-label="Open application navigation"><span aria-hidden="true">☰</span> Menu</button><div class="app-nav-backdrop" hidden></div>
<aside class="app-nav" id="application-navigation" aria-label="Application navigation" data-open="false" inert>
<div class="app-nav-top"><a class="app-nav-home" href="/internal/applicant-review"><img src="/assets/isab-logo.svg" alt="ISAB"><span class="app-nav-title">EHF Fellowships</span></a><span class="app-nav-domain">ehf.isab.science</span><span class="app-nav-purpose">Open the proposal PDFs of one application.</span></div>
<div class="app-nav-scroll"><nav class="app-nav-list" aria-label="Primary navigation"><a class="app-nav-link" href="/internal/applicant-review#viewpoints">Back to applicant review</a><a class="app-nav-link" href="/internal/applicant-previews/{escape(str(bundle.application_id))}">Open the saved application</a></nav></div>
<nav class="app-nav-list app-nav-lower" aria-label="Settings and help navigation"><span class="app-nav-heading">Settings</span><a class="app-nav-link" href="#appearance">Appearance</a><a class="app-nav-link" href="#help">Help</a><div class="app-nav-authorizations"><strong>Authorizations:</strong><span class="app-nav-authorization-pills"><span class="app-nav-authorization-pill group-pill-1">{administrator_group}</span></span></div></nav></aside>
<main class="site-main applicant-review-main" id="main-content" tabindex="-1">
<header class="site-hero"><h1>{escape(bundle.applicant_name)}</h1><p>Proposal documents · application status: {escape(bundle.application_status)}</p></header>
<div class="preview-notice" role="status"><strong>Read-only administrator view</strong><span>Each control below opens the active PDF of one dossier document. Opening a document is recorded in the application audit trail and nothing on this page can change the application.</span></div>
<section id="documents" aria-labelledby="documents-heading"><div class="section-heading"><h2 id="documents-heading">Proposal documents</h2><p>{_document_count(bundle)}</p></div>{body}</section>
<section id="help" class="section-heading"><h2>Help</h2><p>Use the Back to applicant review navigation to return to the applicant cards. Documents stay unreviewed until an administrator records a classification decision; confidential recommendation material is marked as such.</p></section>
<section id="appearance" aria-labelledby="appearance-heading"><div class="section-heading"><h2 id="appearance-heading">Appearance</h2><p>Choose the display that is most comfortable for you. Your preference is stored securely for your administrator identity.</p></div>{_appearance_controls()}</section>
</main><script src="/assets/theme.js"></script><script src="/assets/shell.js"></script></body></html>"""


def _document_count(bundle: ApplicantPreviewDocuments) -> str:
    count = len(bundle.documents)
    if count == 0:
        return "This application has no active proposal document."
    if count == 1:
        return "This application has one active proposal document."
    return f"This application has {count} active proposal documents."


def _document_control(document: ApplicantPreviewDocument) -> str:
    label = document_type_label(document.document_type)
    href = f"/api/internal/applicant-preview-documents/{escape(str(document.document_version_id))}"
    confidential = (
        '<em class="preview-document-confidential">Confidential</em>'
        if document.document_type in CONFIDENTIAL_DOCUMENT_TYPES
        else ""
    )
    return (
        f'<a class="shell-card preview-document-card" href="{href}" '
        f'target="_blank" rel="noopener noreferrer" data-preview-document>'
        f"<strong>{escape(label)} (PDF)</strong>"
        f"<span>{escape(_document_facts(document))}</span>"
        f"<span>Dossier reference: {escape(document.slot_code)}</span>"
        f"{confidential}</a>"
    )


def _document_facts(document: ApplicantPreviewDocument) -> str:
    facts: list[str] = []
    if document.page_count is not None:
        pages = "1 page" if document.page_count == 1 else f"{document.page_count} pages"
        facts.append(pages)
    if document.byte_size is not None:
        facts.append(_byte_size(document.byte_size))
    facts.append(f"classification {document.classification}")
    return " · ".join(facts)


def _byte_size(byte_size: int) -> str:
    if byte_size >= 1_048_576:
        return f"{byte_size / 1_048_576:.1f} MB"
    if byte_size >= 1024:
        return f"{byte_size / 1024:.0f} KB"
    return f"{byte_size} bytes"


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
        "</div></div>"
    )
