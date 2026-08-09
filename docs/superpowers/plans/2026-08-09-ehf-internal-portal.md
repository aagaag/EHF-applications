# EHF Internal Administration Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Deliver the secure internal portal for Adriano Aguzzi and Margaryta Schaltegger as full operational administrators and Ricky Weissman and Magda Polymenidou as read-only trustees, including the live applicant table, record detail, classification/completeness operations, exports, and two accessible scatter plots.

**Architecture:** Cloudflare Access provides the external internal-user boundary; the app independently validates its JWT and resolves exact Entra tenant/object/group IDs. The internal API maps the two EHF groups to `ADMINISTRATOR` and `TRUSTEE`, repeats authorization at every route and stored procedure, and fails closed if group resolution is unavailable. One server-side query model drives the responsive table, exports, and reports. Administrative mutations use row versions and append audit events in the same transaction. Communication work in this plan is preview/outbox-only; real delivery remains disabled.

**Tech Stack:** FastAPI, PyJWT, Cloudflare Access identity endpoint, Microsoft Graph group-authorization sidecar, SQL Server, HTML/CSS/ES modules, server-side search/sort/filter/pagination, `openpyxl`, accessible SVG scatter plots with a tabular alternative, pytest, and Playwright.

**Global Constraints:** Plans 1–2 must be complete; EHF groups are application-specific and do not become general ISAB groups; stable tenant/object/group IDs are authoritative and email is descriptive only; trustees can never mutate data, open slots, classify documents, or create/send communications; the selection-committee group has no first-release route or app assignment; internal pages must never be reachable through applicant authentication; and the authorization indicator is generated from the same inventory as server authorization and shows only groups that currently grant access.

## Task 1: Create the EHF identity manifest and least-privileged Entra provisioning scripts

**Files:**

- Create: `infra/identity/ehf-identity.json`
- Create: `scripts/provision-entra.ps1`
- Create: `scripts/verify-entra.ps1`
- Create: `tests/test_identity_manifest.py`
- Create: `docs/identity-onboarding.md`
- Modify: `docs/permissions.md`

**Step 1: Write failing manifest tests**

Require tenant ID `8226a4c2-10fa-4742-b4c0-f4fdb97a0534`, exact group display names, immutable object IDs after provisioning, role mapping, explicit members, and a disabled/no-assignment selection-committee entry. Reject email-only grants, duplicate IDs, unknown roles, and any member placed in both operational and read-only roles.

**Step 2: Implement an idempotent provisioning script**

Use the real Azure CLI path and Microsoft Graph, not browser steering. Create or reconcile:

- `EHF-Applications-Administrators` with Adriano Aguzzi and Margaryta Schaltegger;
- `EHF-Applications-Trustees` with Ricky Weissman and Magda Polymenidou; and
- `EHF-Applications-Selection-Committee` with no members and no application assignment.

Resolve each person by exact authoritative directory identity. For an external trustee not yet in the tenant, plan the B2B invitation but require the `-ApplyGuestInvitations` switch; fail on zero or multiple email matches and never guess an address. Guest creation is performed only after Adriano Aguzzi reviews the resolved addresses. Record stable group/member object IDs, not secrets, into the manifest.

Create a dedicated EHF enterprise application or Cloudflare-facing Entra authorization object as required by the final Access configuration. Assign only the administrators and trustees groups. Configure Conditional Access MFA for the EHF app through an idempotent, named policy where tenant licensing permits; otherwise stop and report the exact missing licensing/control rather than weakening MFA.

**Step 3: Test without mutation**

Run `powershell -File scripts/provision-entra.ps1 -PlanOnly`.

Expected: exact proposed groups/members/app assignment, no mutation, no ambiguous identity, and selection committee explicitly unassigned.

**Step 4: Apply and verify in the authorized execution phase**

After address review, run with `-Apply` and, only if required, `-ApplyGuestInvitations`. Then run `scripts/verify-entra.ps1`.

Expected: group membership and app assignments match the manifest; MFA policy targets the EHF app; removal test revokes access; selection committee has no effective access.

**Step 5: Commit**

Commit message: `security: define EHF internal identities`

## Task 2: Validate Cloudflare Access identity and exact EHF group membership

**Files:**

- Create: `app/auth/__init__.py`
- Create: `app/auth/internal.py`
- Create: `app/auth/group_authorization.py`
- Create: `app/auth/roles.py`
- Create: `app/routes/internal_session.py`
- Create: `infra/ehf-group-authorization.service`
- Create: `tests/test_internal_auth.py`
- Create: `tests/test_internal_roles.py`

**Step 1: Write failing authentication/authorization tests**

Cover valid/invalid signature, issuer, audience, expiry, not-before, host, header/claim email mismatch, tenant mismatch, missing object ID, group resolution timeout, unknown group, administrator, trustee, both groups, and selection committee. Verify trusted identity is `(tenant_id, object_id)` and not email. Verify no Access header allows an applicant route to become internal.

**Step 2: Implement**

Follow the current F2 Access pattern: validate RS256 JWT against the Cloudflare cert endpoint with bounded cache/timeouts; fetch the Access identity group list; if absent, query only the three configured EHF group IDs through a credential-isolated Unix-socket sidecar. The web process never receives a Graph credential. Normalize group IDs and reject any result outside the configured allowlist.

Map administrators to read/write and trustees to read-only. If an identity appears in both groups, use administrator only when the manifest explicitly names that stable object ID as an administrator; otherwise fail closed as a permission conflict. Selection committee always denies in release 1.

**Step 3: Verify**

Run `python -m pytest tests/test_internal_auth.py tests/test_internal_roles.py -q`.

Expected: intended identities pass; every malformed, stale, unavailable, or broader case fails closed.

**Step 4: Commit**

Commit message: `security: enforce EHF internal roles`

## Task 3: Add internal read models and the responsive applicant table

**Files:**

- Create: `database/migrations/008_internal_read_models.sql`
- Create: `database/tests/008_validate_internal_read_models.sql`
- Create: `app/internal/applications.py`
- Create: `app/routes/internal_applications.py`
- Create: `public/internal/applications.html`
- Create: `public/assets/internal-applications.js`
- Create: `tests/test_internal_applications_api.py`
- Create: `tests/browser/internal_table.spec.py`

**Step 1: Write failing API/UI tests**

Test complete server-side search, sort, direction, filters, pagination, deterministic tie-breaking, missing-value order, visible-column preference, trustee/admin equality for reads, and denial for applicants/selection committee. Test whole-row single-click navigation plus Enter/Space, no nested `Open` link, every coherent field's stacked sort control, labelled card reflow, long values, empty/error/loading states, and 3% side margins.

**Step 2: Implement the read model**

Build one view/procedure with the approved metrics and operational fields: applicant; degree; derived anagraphic/academic age; optional gender; first-/last-author/total papers; h-index; applicant total citations; ORCID; Foundation-verified Google Scholar citations and identity certainty; application/confirmation/completeness status; missing data/doc counts; internal recommendation status; invitation/reminder state; last activity; corrections; and contribution completion.

Calculate completeness from required call fields and current document slots, not a separately editable percentage. Use parameter allowlists for sorting/filtering and apply them to the full result set before pagination.

**Step 3: Implement the table**

Use the 94%-wide rounded container and full-width fluid rows. On narrow widths, reflow to labelled cards with no horizontal page scroll. Make each complete row a semantic link to `/internal/applications/{opaque-id}`. Keep columns/filter preferences durable in SQL.

**Step 4: Verify**

Run `python -m pytest tests/test_internal_applications_api.py tests/browser/internal_table.spec.py -q`.

Expected: API and four representative viewport tests pass.

**Step 5: Commit**

Commit message: `feat: add the live EHF applicant table`

## Task 4: Build the role-aware applicant detail workspace

**Files:**

- Create: `app/internal/detail.py`
- Create: `app/routes/internal_detail.py`
- Create: `public/internal/application.html`
- Create: `public/assets/internal-detail.js`
- Create: `database/migrations/009_internal_operations.sql`
- Create: `database/tests/009_validate_internal_operations.sql`
- Create: `tests/test_internal_detail.py`
- Create: `tests/test_trustee_read_only.py`
- Create: `tests/browser/internal_detail.spec.py`

**Step 1: Write failing permission-matrix tests**

Test applicant-facing data, internal verification, applicant-visible documents, confidential recommendations, communications status, and audit tabs. Prove trustees can read every authorized item/version but receive `403` from all POST/PATCH/DELETE routes, even with forged browser state/action headers. Prove administrators can classify, correct on behalf of an applicant, verify bibliometrics, open/close slots, accept/reject/restore versions, and add internal notes with audit and optimistic row-version checks.

**Step 2: Implement server operations**

Create separate procedures for each bounded operation. Store the verified actor, reason, before/after state, source, and timestamp in one transaction. Never physically delete a document, classification, note, correction, or version. A recommendation-class document can never be changed to applicant-visible without a distinct classification decision; every override of a recommendation signal requires a reason and remains audited.

**Step 3: Implement the UI**

Render the same read model for both roles. Omit mutation controls entirely for trustees; do not merely disable them. Separate tabs/sections clearly. Do not expose confidential filenames in applicant-facing previews. Use blue and amber/orange for paired actions and spatially separate consequential choices.

**Step 4: Verify**

Run `python -m pytest tests/test_internal_detail.py tests/test_trustee_read_only.py tests/browser/internal_detail.spec.py -q`.

Expected: all role and concurrency tests pass.

**Step 5: Commit**

Commit message: `feat: add role-aware EHF record operations`

## Task 5: Implement Foundation-verified bibliometrics and accessible scatter plots

**Files:**

- Create: `app/internal/reports.py`
- Create: `app/routes/internal_reports.py`
- Create: `public/internal/reports.html`
- Create: `public/assets/scatter-plot.js`
- Create: `tests/test_reports.py`
- Create: `tests/browser/scatter_plots.spec.py`

**Step 1: Write failing calculation tests**

Test call-deadline age calculation from birth month/year and exact PhD date, missing values, future/invalid dates, leap dates, citation zero versus missing, Foundation-verified versus applicant-reported citations, verification timestamps, filters, and the exact `Not plotted because data are incomplete` list.

**Step 2: Implement report data**

Use Foundation-verified Google Scholar citation totals only on the y-axis. Plot citations versus anagraphic age and versus academic age. Return exact numeric data, axis labels, verification date, and excluded-record reasons. Do not scrape Google Scholar; administrators enter or confirm the Foundation-verified value and identity certainty.

**Step 3: Implement accessible plots**

Render progressive-enhancement SVG plots with one focusable point per applicant, visible textual axes, keyboard tooltip/details, and a complete adjacent HTML table. Use shape/focus/text in addition to color. Keep an unfiltered call-wide view and an explicit filtered view. Respect reduced motion and all skins.

**Step 4: Verify**

Run `python -m pytest tests/test_reports.py tests/browser/scatter_plots.spec.py -q`.

Expected: plotted/excluded totals equal the API dataset; keyboard and table alternatives expose every point; no overflow at tested widths.

**Step 5: Commit**

Commit message: `feat: add EHF citation-age reports`

## Task 6: Add audited CSV/XLSX exports

**Files:**

- Create: `app/internal/exports.py`
- Create: `app/routes/internal_exports.py`
- Create: `tests/test_exports.py`
- Create: `tests/test_export_audit.py`

**Step 1: Write failing export tests**

Test role authorization, current filter/sort application, complete result set rather than current page, CSV formula injection, Unicode, missing values, column selection, XLSX data types, export metadata, temporary-file cleanup, and audit. Verify no document bytes, recommendation contents, hidden security fields, or applicant tokens enter an export.

**Step 2: Implement**

Generate CSV with formula-dangerous cells escaped as text. Generate XLSX with a data sheet and an `Export metadata` sheet containing exporting stable identity, UTC time, call, filters, columns, row count, and a visible confidential-use notice. Stream through a bounded temporary file and remove it in guaranteed cleanup. Record every requested/completed/failed export.

**Step 3: Verify**

Run `python -m pytest tests/test_exports.py tests/test_export_audit.py -q`.

Expected: both roles can export authorized read data; export mutations are impossible; audit and cleanup pass.

**Step 4: Commit**

Commit message: `feat: add audited EHF data exports`

## Task 7: Add communication previews and a disabled outbox

**Files:**

- Create: `database/migrations/010_communications.sql`
- Create: `database/tests/010_validate_communications.sql`
- Create: `app/communications/model.py`
- Create: `app/communications/render.py`
- Create: `app/communications/transport.py`
- Create: `app/routes/internal_communications.py`
- Create: `public/internal/communications.html`
- Create: `public/assets/internal-communications.js`
- Create: `tests/test_communications.py`
- Create: `tests/test_mail_disabled.py`

**Step 1: Write failing safety tests**

Prove trustees cannot create, alter, schedule, or send. Prove administrators must see resolved recipient, configured sender, subject, HTML body, personalized destination, attachments, and generated-by footer before queuing. Prove no production transport can instantiate while disabled and no deploy/import command changes that flag.

**Step 2: Implement preview/outbox-only behavior**

Create immutable message versions and an outbox state machine (`DRAFT`, `APPROVED_FOR_INTERNAL_TEST`, `READY`, `SENT`, `FAILED`, `CANCELLED`). Templates are HTML plus a generated plain-text alternative and append `Generated by: `, the value returned by `socket.gethostname()`, ` via EHF Applications at `, and an ISO-8601 UTC timestamp. Store invitation tokens only as hashes; render a link only inside the bounded delivery job. In this plan, register only a development sink that writes no recipient message to production mail.

**Step 3: Verify**

Run `python -m pytest tests/test_communications.py tests/test_mail_disabled.py -q`.

Expected: previews pass; every attempted real send is rejected with a logged safe status; trustee mutation tests return `403`.

**Step 4: Run the full suite and commit**

Run `python -m pytest -q`.

Expected: all Plans 1–3 tests pass.

Commit message: `feat: add gated EHF communication previews`
