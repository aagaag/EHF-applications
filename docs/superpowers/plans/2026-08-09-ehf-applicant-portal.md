# EHF Applicant Review Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Let each 2026 applicant securely review, correct, complete, download, and explicitly confirm only that applicant's authorized data and applicant-supplied documents, with controlled missing/replacement uploads and no possible recommendation disclosure.

**Architecture:** The personalized URL carries a 256-bit opaque token whose SHA-256 hash identifies one invitation. It reveals no data until a Turnstile- and rate-limit-protected OTP challenge succeeds. OTPs are short-lived HMAC-protected values sent to the registered address; authenticated applicant sessions are random, hashed server-side, rotated, HTTP-only, secure, same-site cookies bound to one application. Typed section drafts use optimistic row versions and autosave; explicit section confirmations bind to canonical section hashes. Final submission binds a complete data/document manifest and locks applicant editing until an administrator reopens a bounded section or slot.

**Tech Stack:** FastAPI, SQL Server, `cryptography`, Cloudflare Turnstile verification, server-side rate limiting, HTML/CSS/ES modules, pytest, Playwright, ClamAV, and the document services from Plan 2.

**Global Constraints:** Plans 1–3 must be complete; no applicant uses Entra; no identity or application data appears before OTP verification; tokens/codes/session IDs are never stored in cleartext or logged; every query is scoped by the authenticated session's application ID; applicant responses contain no recommendation status, count, filename, identifier, route, or distinguishable error; all applicant-facing fields must be explicitly confirmed; originals are immutable; uploads require a specific open slot; and production mail/invitations remain disabled.

## Task 1: Add invitation, challenge, session, rate-limit, and confirmation records

**Files:**

- Create: `database/migrations/011_applicant_access.sql`
- Create: `database/migrations/012_applicant_drafts.sql`
- Create: `database/migrations/013_applicant_confirmations.sql`
- Create: `database/tests/011_validate_applicant_access.sql`
- Create: `database/tests/012_validate_applicant_drafts.sql`
- Create: `database/tests/013_validate_applicant_confirmations.sql`
- Create: `tests/test_applicant_schema.py`

**Step 1: Write failing schema tests**

Require invitation hash/revocation/expiry, OTP challenge hash/nonce/expiry/attempt count/single-use state, session hash/rotation/inactivity/absolute expiry, per-subject rate buckets, CSRF state, section drafts, correction history, section confirmation hash, final confirmation manifest, and reopen records. Reject cleartext token/code/session columns, mutable audit history, overlapping active final confirmations, and applicant writes after lock.

**Step 2: Implement**

Use lookup hashes for random invitation/session tokens and HMAC-SHA-256 with an application pepper plus per-challenge nonce for six-digit OTPs. Default OTP lifetime to ten minutes and five verification attempts; keep values configurable within tested security bounds. Use UTC timestamps and `rowversion` for concurrency. Make final confirmation append-only and require a superseding confirmation after any administrator reopen/change.

**Step 3: Verify**

Run `python -m pytest tests/test_applicant_schema.py -q` and the isolated SQL validator.

Expected: all access/draft/confirmation invariants pass; direct table DML remains denied.

**Step 4: Commit**

Commit message: `feat: add applicant access and confirmation schema`

## Task 2: Implement neutral invitation entry and OTP verification

**Files:**

- Create: `app/auth/applicant.py`
- Create: `app/auth/turnstile.py`
- Create: `app/auth/rate_limit.py`
- Create: `app/routes/applicant_auth.py`
- Create: `public/applicant/verify.html`
- Create: `public/assets/applicant-auth.js`
- Create: `tests/test_invitation_tokens.py`
- Create: `tests/test_otp.py`
- Create: `tests/test_turnstile.py`
- Create: `tests/test_applicant_rate_limits.py`
- Create: `tests/browser/applicant_auth.spec.py`

**Step 1: Write failing attack-oriented tests**

Cover valid, unknown, expired, revoked, reused, and forwarded invitation tokens; valid/invalid/expired/reused OTPs; cross-invitation OTP use; timing-neutral unknown token behavior; per-token/per-IP/global throttling; Turnstile unavailable/invalid/replayed responses; cookie flags; session rotation; CSRF; and neutral errors. Assert all pre-verification HTML/API bodies have the same structure and reveal no name/email/document/count/status.

**Step 2: Implement**

Use `/a/{opaque-token}` only to establish a neutral pre-auth context and immediately replace the token URL with `/applicant/verify` using server redirect/history replacement. Require Turnstile for code request, after repeated failures, and for suspicious submissions. Return one neutral message whether a token/challenge exists. Create the session only after successful OTP verification; mark the challenge used atomically; rotate the cookie at authentication and privilege state changes.

Do not expose the email address. If a delivery hint is necessary after internal review, show only a fixed statement that the code was sent to the registered address, not a masked address that could aid inference.

**Step 3: Verify**

Run `python -m pytest tests/test_invitation_tokens.py tests/test_otp.py tests/test_turnstile.py tests/test_applicant_rate_limits.py tests/browser/applicant_auth.spec.py -q`.

Expected: all attacks fail; pre-auth response snapshots are identity-neutral; secure cookie and rate-limit tests pass.

**Step 4: Commit**

Commit message: `security: add applicant token and OTP access`

## Task 3: Build one applicant-scoped projection and leak-prevention contract

**Files:**

- Create: `database/migrations/014_applicant_projection.sql`
- Create: `database/tests/014_validate_applicant_projection.sql`
- Create: `app/applicant/projection.py`
- Create: `app/routes/applicant_data.py`
- Create: `tests/test_applicant_object_authorization.py`
- Create: `tests/test_recommendation_non_disclosure.py`
- Create: `tests/test_applicant_response_contract.py`

**Step 1: Write failing confidentiality tests**

Create two synthetic applicants with visible files, internal files, direct referee recommendations, recommendations forwarded by the applicant, old versions, and internal notes. Test list/detail/count/search/download/package/error/timing/cache behavior while guessing every known ID. Scan serialized applicant responses for forbidden internal field names and synthetic secret markers.

**Step 2: Implement the allowlist projection**

Accept no applicant ID from the browser for applicant data APIs. Resolve the application only from the session, then query one applicant-facing view/procedure containing the approved fields, confirmation states, allowed document slots, and approved visible current versions. Do not join or count recommendation/internal tables. Return a fixed not-found response for an unauthorized/unknown document.

Implement a response-schema allowlist so adding an internal model field cannot serialize it accidentally. Add contract tests that fail if recommendation terms, internal verification fields, storage keys, source paths, or audit internals appear.

**Step 3: Verify**

Run `python -m pytest tests/test_applicant_object_authorization.py tests/test_recommendation_non_disclosure.py tests/test_applicant_response_contract.py -q`.

Expected: applicant A can read only A's allowlisted projection; every confidential/other-applicant attempt is neutral and inaccessible.

**Step 4: Commit**

Commit message: `security: isolate each applicant projection`

## Task 4: Implement typed review, correction, autosave, and section confirmation

**Files:**

- Create: `app/applicant/fields.py`
- Create: `app/applicant/drafts.py`
- Create: `app/applicant/confirmations.py`
- Create: `app/routes/applicant_review.py`
- Create: `public/applicant/review.html`
- Create: `public/assets/applicant-review.js`
- Create: `tests/test_applicant_fields.py`
- Create: `tests/test_applicant_drafts.py`
- Create: `tests/test_section_confirmations.py`
- Create: `tests/browser/applicant_review.spec.py`

**Step 1: Write failing field and workflow tests**

Test every approved applicant-facing category and required declaration. Include optional preferred/alternative contact values; telephone; birth month/year with no day; optional self-reported gender (`Prefer not to say` and self-description); UZH institute/PI/position/status/dates; molecular-life-science area; clinical percentage; first/co-first author declaration; MD/PhD/MD-PhD category; exact PhD date; publication metrics; ORCID; Google Scholar URL or no-profile declaration; applicant-reported citations; and document checklist.

Test invalid dates/ranges/URLs/ORCID, Unicode normalization, blank versus zero, stale row versions, autosave failure, unchanged confirmation, change-after-confirmation invalidation, and administrator correction provenance. Assert academic/anagraphic ages are server-derived at the call deadline.

**Step 2: Implement canonical field schemas**

Define one server-owned field inventory with type, label, help, visibility, requirement, validation, and section. Generate both API validation and UI metadata from it. Never infer gender. Store applicant values and imported values with provenance; preserve prior values in immutable change records.

Autosave each changed field/section transactionally with its row version. Show `Saved` only after commit. Explicit section confirmation records a canonical JSON hash of all section values and current source versions. Any later change invalidates that confirmation visibly.

**Step 3: Implement the UI**

Show dashboard progress and one section at a time in plain language. Every section has `Confirm this information` and a separate `Correct information` path; do not treat unchanged navigation as confirmation. Preserve drafts on validation/upload errors. Use accessible live regions and a reassuring progress state after ten seconds.

**Step 4: Verify**

Run `python -m pytest tests/test_applicant_fields.py tests/test_applicant_drafts.py tests/test_section_confirmations.py tests/browser/applicant_review.spec.py -q`.

Expected: every field and confirmation path passes at desktop/tablet/phone widths with no overflow.

**Step 5: Commit**

Commit message: `feat: add complete applicant data review`

## Task 5: Add the 1,000-character scientific-contribution statement

**Files:**

- Create: `app/applicant/contribution.py`
- Create: `tests/test_contribution_statement.py`
- Create: `tests/browser/contribution_statement.spec.py`
- Modify: `public/applicant/review.html`
- Modify: `public/assets/applicant-review.js`

**Step 1: Write failing boundary tests**

Test empty, 999, 1,000, and 1,001 Unicode characters; line endings; emoji/graphemes; pasted content; concurrent changes; confirmation invalidation; and server/client agreement. The enforceable count is Unicode code points including spaces, not words or UTF-8 bytes.

**Step 2: Implement**

Add the exact approved question, required plain-text textarea, live remaining-character counter, and explanatory `approximately 200 words` text. Normalize line endings but do not silently shorten or rewrite. Enforce 1,000 characters in the browser, API, and SQL constraint.

**Step 3: Verify**

Run `python -m pytest tests/test_contribution_statement.py tests/browser/contribution_statement.spec.py -q`.

Expected: 1,000 accepted, 1,001 rejected without losing the draft, counter announced accessibly.

**Step 4: Commit**

Commit message: `feat: collect the scientific contribution statement`

## Task 6: Add controlled document slots, uploads, and downloads

**Files:**

- Create: `database/migrations/015_applicant_document_slots.sql`
- Create: `database/tests/015_validate_applicant_document_slots.sql`
- Create: `app/applicant/documents.py`
- Create: `app/routes/applicant_documents.py`
- Create: `public/applicant/documents.html`
- Create: `public/assets/applicant-documents.js`
- Create: `tests/test_applicant_uploads.py`
- Create: `tests/test_applicant_downloads.py`
- Create: `tests/browser/applicant_documents.spec.py`

**Step 1: Write failing upload/download tests**

Test the required slots: CV, publication list, research plan, cover letter/career plan, future UZH proof when applicable, and administrator-created additional non-confidential slot. Test closed slot, wrong application, invalid/oversized/encrypted/active-content PDF, malware, scan outage, successful missing upload, authorized replacement, old-version preservation, administrator rejection/restoration, duplicate upload, and concurrent slot closure.

Re-run the direct/guessed recommendation tests through every document endpoint and combined-package endpoint.

**Step 2: Implement**

Show only applicant-facing slots. An upload route takes the session application and opaque slot ID; the database confirms the slot is open for `MISSING` or `REPLACEMENT` and the submitted row version is current. Quarantine, validate, scan, encrypt, and register before making a version pending/current. Never overwrite the original. Close or reject through administrator procedures only.

Use the Plan 2 authorized download and package services. Tell applicants only that recommendations are administered separately by the Foundation; reveal no receipt/status/count/file information.

**Step 3: Verify**

Run `python -m pytest tests/test_applicant_uploads.py tests/test_applicant_downloads.py tests/test_recommendation_non_disclosure.py tests/browser/applicant_documents.spec.py -q`.

Expected: only open slots accept PDFs; originals remain; recommendations stay non-disclosed.

**Step 4: Commit**

Commit message: `feat: add controlled applicant documents`

## Task 7: Implement final review, confirmation manifest, and lock/reopen behavior

**Files:**

- Create: `app/applicant/finalize.py`
- Create: `app/routes/applicant_finalize.py`
- Create: `public/applicant/final-review.html`
- Create: `public/assets/applicant-finalize.js`
- Create: `tests/test_final_confirmation.py`
- Create: `tests/test_reopen_workflow.py`
- Create: `tests/browser/final_review.spec.py`

**Step 1: Write failing completion tests**

Test missing section confirmation, missing statement, unresolved required slot, pending/rejected upload, stale data/document version, duplicate final submission, successful submission, post-submit edits, administrator section reopen, slot-only reopen, reconfirmation, and audit. Verify the manifest binds every applicant-facing value version, section hash, declaration, and current visible document-version ID/hash, but no recommendation/internal data.

**Step 2: Implement**

Generate the final review entirely from the applicant allowlist projection. In one SQL transaction, revalidate all requirements and versions, append the canonical confirmation manifest/hash, set the application applicant state to locked, expire draft mutation permission, and append the audit event. Repeated identical submission returns the existing confirmation without duplication.

An administrator reopen names exact sections/slots and a reason. Only those scopes become editable; unaffected confirmations remain shown, and final confirmation becomes superseded until the applicant reconfirms changed scopes and submits again.

**Step 3: Verify**

Run `python -m pytest tests/test_final_confirmation.py tests/test_reopen_workflow.py tests/browser/final_review.spec.py -q`.

Expected: only complete/current applications finalize; locked writes fail; bounded reopen works and remains audited.

**Step 4: Run complete security and UI suites**

Run `python -m pytest -q`.

Expected: all Plans 1–4 tests pass, including recommendation non-disclosure, object authorization, accessibility, and viewport checks.

**Step 5: Commit and push**

Commit message: `feat: complete the EHF applicant review workflow`

Push `main` and deploy the release with both invitation and production-mail flags still false.
