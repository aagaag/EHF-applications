# Applicant Form Simplification Design

**Date:** 2026-08-18
**Status:** Approved for implementation by Adriano Aguzzi's instruction to finish autonomously

## Objective

Make the applicant review workspace faster and easier to complete while preserving per-applicant isolation, administrator/trustee approval, the existing scientific-contribution workflow, documents, and final review.

## Approved form changes

### Identity and contact

- Keep the section and its existing fields, except remove `genderSelfDescription` and the `Self-describe` gender option.
- Use a compact desktop grid so short values such as birth month, birth year, telephone, and gender do not occupy unnecessarily long controls.
- Reflow to two columns on tablets and one column on phones without horizontal scrolling.

### UZH employment and eligibility

- Keep the section and its meaning.
- Use three fluid columns on desktop, two on tablets, and one on phones.
- Replace the ambiguous free-text postdoctoral-employment field with the required Yes/No question `Are you currently employed in a postdoctoral position?` and explanatory help text. The existing future-start-date field continues to cover appointments that have not started.

### Qualifications and academic age

- Replace the single highest-degree field with an ordered, repeatable degree list.
- Every row contains a degree type selected from exactly `BSc`, `MA`, `MD`, and `PhD`, plus a calendar-selectable date of conferral.
- Applicants may add and remove rows. At least one complete row is required before section confirmation.
- Academic age continues to derive from the PhD conferral date when a PhD is present; no derived academic-age value is requested from the applicant.

### Publications and identifiers

- Keep the existing paper counts, h-index, applicant-reported citations, and ORCID.
- Replace the inverse `I do not have...` control with the direct required Yes/No question `Do you have a public Google Scholar profile?`.
- Show and require the Google Scholar profile URL only when the answer is Yes; clear it when the answer is No.
- Remove the separately entered Google Scholar citation count.
- Add a repeatable DOI publication list. The applicant enters only a DOI. The server retrieves canonical metadata from Crossref, the interface shows the resolved publication, and the applicant explicitly confirms it before it is added.
- Persist the normalized DOI and confirmation state as the authoritative applicant input. Metadata is re-resolved from Crossref for display, using a bounded in-process cache; client-supplied bibliographic metadata is never trusted as application data.

## DOI lookup boundary

- The lookup endpoint requires the same authenticated, application-bound applicant session and CSRF protection as section edits.
- Accept only normalized DOI syntax and construct requests against the fixed Crossref API host; applicants cannot supply a destination URL.
- Apply bounded input length, request timeout, response-size/shape validation, and a bounded cache.
- Return clear validation, not-found, and temporary-service errors without leaking provider or infrastructure details.
- A DOI is added only after a successful lookup and an explicit applicant confirmation.

## Persistence and compatibility

- Section drafts continue to be JSON, now with `degrees` and `publications` arrays.
- A new forward-only migration adds a general qualification conferral date, accepts the four portal degree types, upgrades legacy baseline/draft JSON, and updates administrator-approved promotion to write every degree.
- Legacy `MD_PHD` data is preserved by converting it to MD and PhD entries when a reliable date exists; legacy values that cannot be made complete remain visible as missing work rather than being invented.
- Approval remains mandatory: applicant edits continue to create applicant-sourced draft values and do not become authoritative internal application data until an administrator or trustee approves the submission.

## Unchanged behavior

- Each Entra-authenticated applicant can load and edit only the application bound to that identity and session.
- Scientific contribution, documents, final review, confirmation, conflict handling, finalization, and administrator/trustee review remain in place.
- Production applicant invitations remain disabled.

## Verification

- Unit tests cover field inventory, array validation, conditional Scholar rules, DOI normalization and lookup failure modes.
- Route tests cover authenticated/CSRF-protected DOI lookup and application isolation.
- Browser tests cover repeatable degree rows, conditional Scholar URL, DOI confirmation, the three-column employment layout, responsive reflow, keyboard behavior, and absence of horizontal overflow.
- Migration contract tests cover forward-only schema/procedure changes and installation order.
- The full Python and browser suites run before commit, followed by production deployment and an authenticated smoke test that does not send invitations.
