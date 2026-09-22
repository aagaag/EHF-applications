# Pending Publication Review Queue Design

## Purpose

Let an internal EHF reviewer classify every paper awaiting manual review from one fast, focused page. The main navigation exposes **Review Pending Papers** to administrators and trustees. The page groups the current queue by applicant and gives the reviewer the complete available bibliographic denomination before an immediate decision.

## Queue and decisions

The queue contains only publications whose latest append-only review disposition is `PENDING_REVIEW`. Each item shows applicant name and the canonical authors, title, journal, volume, pages, year, DOI/link, plus the latest raw citation when canonical fields are absent. Decisions are mutually exclusive and immediate: **Published** records `PUBLISHED`, **Preprint** records `ACCEPTED_PREPRINT`, and **Remove** records `NON_PUBLICATION`. Remove excludes a source item from the queue; it does not delete source or audit evidence.

The manual decision is authoritative even when a source record is not bibliographically resolved. Published/preprint totals use that reviewer disposition, while citation metrics continue to require resolved evidence. This makes all pending source records actionable without falsely treating unverified metadata as citation evidence.

## Security and consistency

Only `EHF-Administrators` and `EHF-Trustees` can open the page or use its API. Writes require same-origin requests and are executed by a single SQL procedure with the authenticated reviewer identity and canonical group. The procedure locks the publication, verifies that its newest review remains pending, appends the new review and audit event in one transaction, and rejects stale or malformed requests without leaking record existence.

No browser confirmation is shown. A successful click removes the item in place; a failed or stale action leaves it present and shows an inline message so the reviewer can reload or retry.

## Delivery constraints

- Work only on clean, synchronized `main`; stage task files only.
- Preserve append-only publication evidence and runtime table denies.
- Use the repository-pinned Python runtime and red-green-refactor tests.
- Do not commit applicant documents, credentials, or generated artifacts.
