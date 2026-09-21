# EHF Multi-Call Applications Architecture

## Design specification

Date: 21 September 2026  
Status: Design approved in conversation; written specification awaiting review  
Repository: `aagaag/EHF-applications`  
Production hostname: `ehf.isab.science`

## 1. Purpose

The EHF portal must support multiple fellowship calls in one deployment and one
`EHFApplications` database. Each call has its own title, deadlines, applicant
pool, access state, shortlister roster, shortlist assignments, imports,
analysis runs, rankings, plots, reports, exports, and audit history. The form,
analysis, ranking, plotting, and report implementations remain shared.

The existing `EHF-2026` call remains an ordinary call in this architecture. Its
record identifiers, applicant data, document objects, A/B/C shortlist groups,
analysis results, and audit history must not change as a side effect of the
migration.

## 2. Decisions and invariants

The following decisions are approved:

1. All calls use the existing application service, virtual machine, and SQL
   Server database. A database or deployment is not cloned per call.
2. `FellowshipCallId` is the mandatory isolation key for every call-owned
   operation. No operation may use an implicit current call.
3. Applicant pools are independent. The same human applying to two calls has
   two call-scoped applicant/application records; the system does not join
   applicants across calls by name, email address, or Entra identity.
4. Every call defines its own number, names, order, and identities of
   shortlisters.
5. Shortlist editing remains owner-only. Administrators configure the roster
   but cannot assign A/B/C groups on another shortlister's behalf.
6. Analyses, rankings, plots, and reports use one shared implementation pinned
   by a versioned analysis-profile code.
7. Missing, mismatched, inactive, or unauthorized call context fails closed.
8. Production applicant invitations and mail remain disabled until the existing
   documented approval gate is completed separately for the applicable call.

## 3. Current baseline

The schema already contains `dbo.FellowshipCall`, and
`dbo.Application.FellowshipCallId` associates applications with calls. Import
runs and citation cutoff runs also carry the call identifier. This foundation
is retained.

The active implementation is nevertheless single-call in several places:

- SQL procedures filter on the literal call code `EHF-2026`.
- internal and applicant routes do not carry explicit call context;
- report titles, filenames, cutoffs, and navigation copy contain `2026`;
- import and verification commands are named and configured for 2026;
- applicant Entra mappings assume one application per Entra object globally;
- `ShortlistTrustee`, application code, and report rendering hardcode Ricky,
  Magda, and Adriano;
- migrations 037 and 038 store the current shortlisters and their A/B/C group
  assignments without a call-scoped roster.

These hardcoded behaviors are compatibility inputs for `EHF-2026`, not the
model for later calls.

## 4. Call context and routing

### 4.1 Call identity

`FellowshipCall` remains the authoritative call registry. It gains or exposes
typed values for:

- immutable `FellowshipCallId`;
- unique stable `CallCode`;
- unique validated `PublicSlug` used in URLs;
- `DisplayName` and optional compact display title;
- application and applicant-review deadlines;
- overall call status;
- applicant-review, internal-selection, and invitation gates; and
- a versioned `AnalysisProfileCode`, initially `ehf-standard-v1`.

Security and workflow gates must be typed columns or constrained relational
state. `SettingsJson` may hold presentation-only options but is not
authoritative for authorization or lifecycle transitions.

### 4.2 Runtime context

The HTTP boundary resolves a URL slug to a frozen `CallContext` containing the
call ID, code, slug, titles, deadlines, statuses, and analysis profile. Every
call-owned service and repository method receives that context or its immutable
call ID explicitly.

Canonical routes are:

- `/internal/calls/` for the authorized call inventory;
- `/internal/calls/{call-slug}/` for one call workspace;
- `/api/internal/calls/{call-slug}/...` for internal operations;
- `/calls/{call-slug}/applicant/...` for applicant pages;
- `/api/calls/{call-slug}/applicant/...` for applicant operations; and
- `/calls/{call-slug}/a/{opaque-token}` for invitation entry.

Existing browser routes may redirect only to the known `EHF-2026` context.
Legacy APIs may act only as explicit `EHF-2026` compatibility wrappers during
the migration window. A new call is never reachable through a legacy route.

Unknown slugs, URL/session mismatches, and application IDs belonging to another
call return the existing neutral unavailable response. The server never guesses
a call from an application ID, email address, token prefix, or first database
match.

## 5. Data isolation

### 5.1 Applicant pool

`Applicant` becomes call-scoped by adding `FellowshipCallId`. `Application`
retains both its call and applicant IDs and gains a composite ownership foreign
key so an applicant from call A cannot be attached to an application in call B.
Existing applicant IDs are preserved during the `EHF-2026` backfill.

Application-owned tables may continue to use globally unique `ApplicationId`
as their primary relationship, but all callable procedures accept a call ID and
verify that the application belongs to it. High-risk or independently queried
tables receive an explicit call ID and composite constraint where that provides
database-enforced protection, including call access, shortlists, access
requests, applicant identity mappings, and call-level audit events.

Document object keys remain random and globally unique. Authorization is based
on the relational call/application/document chain, never on the object key or
storage path.

### 5.2 Internal call access

Platform Entra groups remain the first authorization boundary. A call-scoped
group-grant relation defines which canonical groups may administer or read each
call. Both checks are required: current membership in the Entra group and an
active grant for the selected call.

The existing administrator and trustee groups are seeded as the grants for
`EHF-2026`. Group grants do not confer shortlist ownership.

### 5.3 Applicant identity

Applicant invitations and sessions remain opaque and application-bound. They
also store or return `FellowshipCallId`, and every applicant request verifies
that the URL call, session call, and application call agree.

Applicant access requests carry a call ID. Entra mappings are unique per
`(FellowshipCallId, EntraObjectId)`, allowing the same identity to have a
different, isolated application in another call. Call-less or ambiguous Entra
sign-in fails rather than choosing the first mapping.

## 6. Configurable shortlisters

### 6.1 Roster

The global, code-constrained `ShortlistTrustee` model is replaced by
`FellowshipCallShortlister`:

- `FellowshipCallShortlisterId` — stable primary key;
- `FellowshipCallId` — owning call;
- `ActorEntraObjectId` — authorization anchor;
- `DisplayName` — call-specific visible name;
- `DisplayOrder` — call-specific ordering;
- `IsActive`, creation time, deactivation time, and configuring actor.

The database enforces one active roster entry per Entra object per call and one
display order per call. A person may appear in several calls, with independent
display names and ordering.

### 6.2 Assignments and owner-only writes

`CallShortlistSelection` stores:

- `FellowshipCallId`;
- `ApplicationId`;
- `FellowshipCallShortlisterId`;
- nullable `GroupCode` constrained to `A`, `B`, or `C`;
- modifying identity, timestamp, and row version.

Composite foreign keys require the application and shortlister to belong to the
same call. The write procedure validates, in one transaction, that:

1. the call is in an editable internal-selection state;
2. the application belongs to the requested call;
3. the roster entry belongs to the call and is active;
4. the signed-in Entra object owns that roster entry; and
5. the requested group is `A`, `B`, `C`, or an explicit clear operation.

Administrators can add, rename, reorder, or deactivate roster entries but have
no procedure that writes another owner's group. Roster removal is a
deactivation, never a deletion, once selections or audit records exist.
Historical selections remain readable and auditable.

### 6.3 Rendering

The server returns the selected call's roster with the shortlist state. Python
and HTML contain no handwritten person list or Entra object IDs. The report
renders the active roster in configured order and shows editing controls only
for the signed-in owner's entry.

The layout supports zero, one, or many shortlisters and long display names. At
wide widths, roster entries may appear as generated columns. When the roster or
viewport would overflow, they reflow into a labelled shortlist subgrid within
each responsive applicant row. The page must retain the ISAB shell, three-percent
side margins, keyboard access, and no horizontal page scrolling.

## 7. Shared analysis and reporting

The metrics, publication validation, citation cutoff, h-index calculation,
ranking, plotting, detail rendering, and workbook generation remain shared code.
They consume a call-scoped dataset and the call's `AnalysisProfileCode`.

Every relevant SQL procedure accepts `@FellowshipCallId` and removes the literal
`EHF-2026` predicate. Analysis and cutoff activation require a completed import
run belonging to the same call. A run cannot mix applications or observations
from another call.

Application numbers, titles, cutoff labels, workbook headings, filenames, and
metadata derive from call configuration and activated analysis evidence. Export
audit records include the immutable call ID, call code, profile version, actor,
row count, outcome, and generation time.

Shortlist roster size does not change calculations or plots. Shortlist group
assignments are a call-scoped reviewer output layered on the shared report.

## 8. Call administration and lifecycle

`/internal/calls/` presents authorized calls as complete keyboard-accessible
links. Each call summary shows its title, code, deadlines, status, applicant
count, latest import, activated analysis evidence, roster state, and selection
state.

Creating a call creates a `DRAFT` call and may clone configuration only:
analysis profile, form/workflow version, required-document definitions, and
presentation settings. Applicants, documents, imports, audit events, roster
members, selections, sessions, and invitations are never cloned.

Lifecycle gates are independent:

- overall call status controls configuration and archival;
- applicant-review state controls applicant reads and writes;
- internal-selection state controls owner shortlist writes; and
- invitation state controls invitation sending and remains subject to the
  documented external approval gate.

Archiving makes all call-owned operations read-only except authorized audit and
export reads. Each state transition is transactional and audited. A blocked
transition returns a clear internal error without partial mutation.

## 9. Imports and operational commands

The 2026-specific import, publication, citation, Scholar-review, review-artifact,
inventory, and verification implementations become generic call-parameterized
commands. Each command requires an explicit validated call ID or code and records
it in its manifest and `ImportRun`.

Temporary directories use a validated short call slug plus an opaque transfer
identifier. The same source fingerprint may occur independently in two calls;
idempotency is scoped to the call. Plan-only execution remains non-mutating, and
no import or deployment command sends invitations or mail.

The existing `*-2026` commands may remain as thin compatibility wrappers that
pass the literal `EHF-2026` code to the generic implementation. Verification
uses call-scoped counts and invariants rather than fixed global counts.

## 10. Migration and compatibility

The change uses an additive expand/contract sequence after migration 038:

1. Add call registry fields, lifecycle gates, group grants, call-scoped
   applicant ownership, call-scoped identity/access fields, roster tables, and
   composite constraints in an expandable form.
2. Backfill every existing call-owned row from the current application's
   `FellowshipCallId` and validate that no row is null, orphaned, or mismatched.
3. Seed the `EHF-2026` group grants and three roster entries using the current
   Entra object IDs, display names, and order.
4. Migrate every existing migration-038 A/B/C assignment, modifier, and
   timestamp to the matching `EHF-2026` application and roster entry.
5. Parameterize procedures and repositories while retaining explicit 2026
   compatibility wrappers for the previous application release.
6. Deploy call-aware routes and rendering, then run parity and cross-call
   verification before enabling a second real call.
7. Retire legacy tables and wrappers only in a later reviewed deployment after
   rollback no longer depends on them.

Backfill verification must prove that `EHF-2026` retains the same application
and document IDs, stored-object keys and hashes, import provenance, publication
and citation results, activated cutoffs, workbook values, A/B/C shortlist
groups, and audit evidence.

## 11. Failure handling and security

- Cross-call identifiers return the same neutral unavailable response as a
  missing object.
- Applicant URL/session/call disagreement revokes or rejects the request and
  exposes no applicant identity.
- A shortlister cannot modify another roster entry even when also an
  administrator.
- Inactive roster entries retain history but cannot write.
- Missing call authorization never falls back to a global role or default call.
- Incomplete, mixed-call, or wrong-profile analysis evidence cannot be
  activated.
- Export generation failure records a failure for the correct call and returns
  no partial workbook.
- Archived calls reject writes without mutating timestamps or audit payloads.
- Audit payloads retain existing sensitive-key prohibitions.

## 12. Verification

Implementation follows test-driven development: the smallest behavior test is
written and run red before each production change, followed by focused tests
and the complete repository suite.

The acceptance fixture contains two calls with overlapping applicant names and
emails, different titles and deadlines, different roster sizes and display
orders, and at least one Entra identity mapped independently in both calls.

Required coverage includes:

- database rejection of cross-call applicant, application, roster, selection,
  access-request, document, import, and analysis relationships;
- unknown-call and call-mismatch route behavior;
- the same Entra identity resolving only within the requested call;
- zero, one, three, and many shortlister layouts with long names on desktop,
  tablet, and phone widths;
- owner-only A/B/C assignment, including an administrator attempting to edit
  another owner;
- roster deactivation preserving historical selections;
- independent import fingerprints, cutoffs, metrics, rankings, plots, and
  exports for the two calls;
- archive and lifecycle write denial;
- plan-only non-mutation and invitation/mail safety gates; and
- exact `EHF-2026` migration parity.

Production verification checks the activated commit, migration inventory,
isolated runtime SQL permissions, readiness endpoint, neutral unauthorized
responses, one authorized `EHF-2026` report, and a synthetic second-call
isolation probe containing no applicant data.

## 13. Deployment and rollback

The service remains on the dedicated `EHF` virtual machine reached through the
verified `ehf-hestia` SSH alias. The application, migrations, and validators are
deployed through the existing immutable-release and atomic-symlink workflow.

The first deployment is expand-compatible: it does not drop the legacy
shortlist tables or 2026 wrappers. Therefore the installer can restore the
previous application release if activation or health verification fails. A
database backup and coordinated document-store checkpoint precede the schema
change, and the deployment record names the validated previous release.

Applicant invitations and production mail remain disabled throughout this
deployment. Enabling them is outside this specification.

## 14. Implementation coordination

The primary agent owns schema design, authorization, migrations, integration,
production deployment, rollback, and final verification. Low-cost workers may
receive only isolated one- or two-file mechanical tasks with explicit ownership,
such as focused unit tests, generic script wrappers, responsive presentation,
or copy updates. They do not own database migrations, authentication,
authorization, secrets, or deployment.

All work remains on synchronized `main`. Each implementation task stages only
its own files, runs its focused red/green test cycle, and records a concise
handoff. The full suite, deployment checks, and production verification remain
the primary agent's responsibility.

## 15. Acceptance criteria

The feature is complete when:

1. administrators can create and select multiple calls in the same database;
2. each call displays only its own applicants and call-derived titles;
3. each call has an independently configurable ordered shortlister roster;
4. each shortlister can edit only their own A/B/C assignments;
5. every analysis, ranking, plot, report, export, document, and import is
   demonstrably call-scoped;
6. a second call passes the complete workflow without changing `EHF-2026`;
7. `EHF-2026` parity checks pass; and
8. the synchronized commit is deployed and independently verified while
   applicant invitations and production mail remain disabled.
