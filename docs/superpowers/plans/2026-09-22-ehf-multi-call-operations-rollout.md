# Multi-Call Operations and Rollout Implementation Plan

> **Required subskill:** Use `superpowers:executing-plans` to implement this plan task by task. Steps explicitly marked as low-cost eligible may be delegated only after their interfaces and ownership boundaries are fixed.

**Goal:** Generalize the import and verification toolchain for arbitrary fellowship calls, prove isolation with two independent calls, and deploy the complete multi-call platform without enabling applicant invitations.

**Architecture:** Every import or operational command receives an explicit immutable call target. Generic scripts own the implementation while the existing `*-2026` entry points remain compatibility wrappers for `EHF-2026`. A synthetic second call exercises application, identity, shortlisting, metrics, export, and archive isolation before the expand-compatible schema is deployed to production.

**Tech Stack:** Python 3.12, FastAPI/Uvicorn, `pyodbc`/SQL Server, PowerShell, pytest, browser scenarios, systemd, Nginx, and the existing immutable Hestia deployment scripts.

**Approved design:** `docs/superpowers/specs/2026-09-21-ehf-multi-call-architecture-design.md`

## Global constraints

- Work directly on `main`; do not create a branch or worktree.
- Begin each task from a clean worktree with local `main` equal to `origin/main`.
- Use `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe` for Python.
- Follow test-driven development: add the smallest failing behavior test, run it RED, implement the minimum, then run the focused and full suites.
- Keep the invitation and outbound-mail gates disabled. This plan does not authorize invitations or applicant mail.
- Never commit credentials, applicant documents, imported applicant data, generated reports, or test artifacts.
- Use only credential paths and secret references in commands and documentation; never print or persist secret values.
- Preserve the approved EHF-2026 behavior and its existing `*-2026` operational entry points.
- Stage only files named by the active task.

## Review focus

- No import, verifier, or operational script may infer the current call from a global default once a call target has been resolved.
- An identical source fingerprint must be independently importable into two calls without cross-call updates or deduplication.
- Compatibility wrappers must be thin, explicit, and pinned to `EHF-2026`.
- The synthetic second call must contain no production applicant data.
- Production verification must prove EHF-2026 parity and that invitations remain disabled.

### Task 1: Make the Python import pipeline call-aware

**Files:**

- Create: `app/importer/call_target.py`
- Modify: `app/importer/run.py`
- Modify: `app/importer/publications.py`
- Modify: `app/importer/open_citations.py`
- Modify: `app/importer/scholar_reviews.py`
- Modify: `app/importer/review_artifacts.py`
- Modify: `app/importer/run_publications.py`
- Modify: `app/importer/run_open_citations.py`
- Modify: `app/importer/run_scholar_reviews.py`
- Modify: `app/importer/run_review_artifacts.py`
- Modify: `app/importer/collect_open_citations.py` if its manifest contract becomes call-owned
- Modify: `tests/test_import_idempotency.py`
- Modify: `tests/test_import_transactions.py`
- Modify: `tests/test_publication_importer.py`
- Modify: `tests/test_open_citation_importer.py`
- Modify: `tests/test_scholar_review_importer.py`
- Modify: `tests/test_review_artifact_importer.py`

**Step 1: Add a failing call-target contract test**

Add tests proving that every importer requires this immutable value object:

```python
@dataclass(frozen=True)
class CallImportTarget:
    fellowship_call_id: UUID
    call_code: str
    public_slug: str
    display_name: str
    application_deadline_utc: datetime
```

The tests must reject missing call context and must prove that repositories receive `fellowship_call_id` explicitly.

Run:

```powershell
$Python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python -m pytest tests/test_import_idempotency.py tests/test_import_transactions.py -q
```

Expected: FAIL because the import pipeline still relies on the EHF-2026 singleton assumptions.

**Step 2: Add failing cross-call idempotency tests**

Use two generated call IDs and the same source fingerprint. Assert that:

- repeated imports into one call are idempotent;
- the same source fingerprint can exist once in each call;
- a rollback in one call does not alter the other call;
- publication, citation, scholar-review, and review-artifact repositories always constrain reads and writes by `FellowshipCallId`.

Run:

```powershell
& $Python -m pytest tests/test_import_idempotency.py tests/test_import_transactions.py tests/test_publication_importer.py tests/test_open_citation_importer.py tests/test_scholar_review_importer.py tests/test_review_artifact_importer.py -q
```

Expected: FAIL on the first missing call predicate or call-keyed uniqueness assertion.

**Step 3: Implement `CallImportTarget` and thread it through the pipeline**

Resolve the call by exact code or slug at the CLI boundary. Pass the resulting `CallImportTarget` through every service and repository call. Do not read a process-global active call and do not retain EHF-2026 literals in generic modules.

All call-owned insert, update, delete, lookup, and idempotency queries must include `FellowshipCallId`. Use the call deadline from the target instead of a fixed 2026 deadline.

**Step 4: Run focused and regression tests**

Run:

```powershell
& $Python -m pytest tests/test_import_idempotency.py tests/test_import_transactions.py tests/test_publication_importer.py tests/test_open_citation_importer.py tests/test_scholar_review_importer.py tests/test_review_artifact_importer.py -q
& $Python -m pytest -q
```

Expected: PASS.

**Step 5: Commit the Python import changes**

```powershell
git add app/importer/call_target.py app/importer/run.py app/importer/publications.py app/importer/open_citations.py app/importer/scholar_reviews.py app/importer/review_artifacts.py app/importer/run_publications.py app/importer/run_open_citations.py app/importer/run_scholar_reviews.py app/importer/run_review_artifacts.py tests/test_import_idempotency.py tests/test_import_transactions.py tests/test_publication_importer.py tests/test_open_citation_importer.py tests/test_scholar_review_importer.py tests/test_review_artifact_importer.py
git commit -m "refactor: scope imports by fellowship call"
```

Add `app/importer/collect_open_citations.py` explicitly only if its manifest contract changed; do not stage an entire directory.

### Task 2: Generalize PowerShell import, collection, and verification commands

**Files:**

- Create: `scripts/inventory-call.ps1`
- Create: `scripts/import-call.ps1`
- Create: `scripts/import-publications.ps1`
- Create: `scripts/import-open-citations.ps1`
- Create: `scripts/import-scholar-reviews.ps1`
- Create: `scripts/import-review-artifacts.ps1`
- Create: `scripts/collect-open-citations.ps1`
- Create: `scripts/verify-import.ps1`
- Create: `scripts/verify-open-citations.ps1`
- Create: `scripts/verify-publications.ps1`
- Create: `scripts/verify-review-artifacts.ps1`
- Create: `scripts/verify-scholar-reviews.ps1`
- Modify: `scripts/inventory-call-2026.ps1`
- Modify: `scripts/import-call-2026.ps1`
- Modify: `scripts/import-open-citations-2026.ps1`
- Modify: `scripts/import-publications-2026.ps1`
- Modify: `scripts/import-review-artifacts-2026.ps1`
- Modify: `scripts/import-scholar-reviews-2026.ps1`
- Modify: `scripts/collect-open-citations-2026.ps1`
- Modify: `scripts/verify-import-2026.ps1`
- Modify: `scripts/verify-open-citations-2026.ps1`
- Modify: `scripts/verify-publications-2026.ps1`
- Modify: `scripts/verify-review-artifacts-2026.ps1`
- Modify: `scripts/verify-scholar-reviews-2026.ps1`
- Modify: `tests/test_source_inventory.py`
- Modify: `tests/test_deployment_contract.py`
- Modify: `tests/test_open_citation_ops.py`
- Modify: `tests/test_scholar_review_ops.py`
- Modify: `tests/test_review_artifact_importer.py`

**Step 1: Add failing script-contract tests**

Assert that each generic script requires an explicit `-CallCode` or `-CallSlug`, validates it through the call catalog, and stores temporary/output state under a sanitized call-specific directory. Assert that each `*-2026.ps1` script only forwards its arguments plus `-CallCode EHF-2026`.

Run:

```powershell
& $Python -m pytest tests/test_source_inventory.py tests/test_deployment_contract.py tests/test_open_citation_ops.py tests/test_scholar_review_ops.py tests/test_review_artifact_importer.py -q
```

Expected: FAIL because the generic entry points and compatibility-wrapper contracts do not exist.

**Step 2: Implement the generic scripts**

Each generic script must:

1. accept exactly one call identifier;
2. resolve it before accessing source files or SQL;
3. pass the resolved call to the Python CLI;
4. reject path separators and traversal in call-derived directory names;
5. keep plan/dry-run behavior available where the current 2026 script provides it;
6. avoid emitting applicant names, email addresses, or document paths in normal logs.

Retain the current `*-2026.ps1` names as thin compatibility wrappers. Do not duplicate the implementation.

**Step 3: Run focused and full tests**

```powershell
& $Python -m pytest tests/test_source_inventory.py tests/test_deployment_contract.py tests/test_open_citation_ops.py tests/test_scholar_review_ops.py tests/test_review_artifact_importer.py -q
& $Python -m pytest -q
```

Expected: PASS.

**Step 4: Delegate only isolated wrappers if useful**

After the generic parameter and exit-code contract is fixed, a low-cost worker may own one compatibility wrapper plus its single contract test. The worker must be told it is not alone in the repository, must not modify generic scripts or shared fixtures, and must not revert other edits. The primary agent reconciles and reruns the focused suite.

**Step 5: Commit the operational scripts**

Stage the exact new and modified script/test paths reported by `git status --short`, then commit:

```powershell
git commit -m "refactor: generalize fellowship call operations"
```

### Task 3: Prove two-call isolation end to end

**Files:**

- Create: `tests/test_multi_call_isolation.py`
- Create: `tests/browser/multi_call.spec.py`
- Modify: shared test fixtures only where necessary

**Step 1: Add the failing synthetic two-call fixture**

Create two synthetic calls entirely in test setup. Use overlapping applicant display names and email addresses, the same synthetic Entra object ID in both calls, different shortlister rosters, and different stage settings. Do not copy production data.

Run:

```powershell
& $Python -m pytest tests/test_multi_call_isolation.py -q
```

Expected: FAIL at the first missing call-specific boundary.

**Step 2: Cover every isolation boundary**

The integration test must prove:

- application creation, status, sessions, invitations, and documents are isolated;
- the same person may belong to both calls without account or ownership collision, using distinct call-owned `ApplicantId` values even when names and email addresses match;
- internal review writes and owner-only A/B/C edits affect only the selected call;
- roster membership and display names differ by call;
- metrics, cutoff, ranking, plots, detail views, exports, and archived artifacts contain only the selected call;
- imports and source fingerprints remain independently idempotent;
- call creation and call switching do not change EHF-2026 data;
- closed or archived stages reject writes only for their own call.

**Step 3: Add the browser acceptance flow**

Exercise call selection, call-scoped URLs, dynamic shortlister reflow/subgrids, roster administration, owner-only editing, and call-labeled exports. Assert zero document-level horizontal overflow and that a URL for one call cannot display or mutate records from the other call.

Run:

```powershell
& $Python -m pytest tests/browser/multi_call.spec.py -q
```

Expected: PASS only after the foundation, access, and shortlist/report plans are complete.

**Step 4: Run the full suite**

```powershell
& $Python -m pytest -q
```

Expected: PASS with no test depending on execution order or production data.

**Step 5: Commit the acceptance coverage**

```powershell
git add tests/test_multi_call_isolation.py tests/browser/multi_call.spec.py
git commit -m "test: prove multi-call isolation"
```

Add a shared fixture path only if it was actually modified.

### Task 4: Update operator documentation and deployment verification

**Files:**

- Modify: `docs/deployment.md`
- Create or modify: `docs/import.md`
- Modify: `docs/import-2026.md`
- Modify: `scripts/verify-ehf.ps1`
- Modify: `scripts/deploy-ehf.ps1` only if the deployment contract requires it
- Modify: `tests/test_deployment_contract.py`
- Modify: `CODEX_COORDINATION.md`

**Step 1: Add failing deployment-contract assertions**

Assert that the verifier checks:

- schema migrations through `042`;
- the EHF-2026 call resolves and retains its expected profile/stages;
- a generic call can be inventoried without accessing another call;
- current-call URLs and compatibility URLs respond as documented;
- every call has `InvitationsEnabled=0`, and the service invitation/delivery environment gates remain disabled;
- the running commit matches the supplied 40-character SHA.

Run:

```powershell
& $Python -m pytest tests/test_deployment_contract.py -q
```

Expected: FAIL until the verification script exposes these checks.

**Step 2: Implement verifier and documentation updates**

Document exact call creation, import, inventory, verification, archive, and rollback commands. `docs/import-2026.md` must state that it is an EHF-2026 compatibility path and point to the generic guide. Keep examples free of applicant data and secret values.

`scripts/verify-ehf.ps1` must fail closed when the expected commit, call catalog, migration tip, any per-call invitation flag, or service invitation/mail gate is wrong. Its output must be suitable for a nonpersonal deployment evidence record. Two-call mutation probes run only in the isolated rolled-back database workflow; the live verifier does not create or delete production calls.

**Step 3: Verify the deployment contract and dry run**

```powershell
& $Python -m pytest tests/test_deployment_contract.py -q
powershell -NoProfile -File scripts/deploy-ehf.ps1 -WhatIf
```

Expected: PASS; the dry run names the intended host and actions without changing production.

**Step 4: Commit the operator contract**

```powershell
git add docs/deployment.md docs/import.md docs/import-2026.md scripts/verify-ehf.ps1 tests/test_deployment_contract.py CODEX_COORDINATION.md
git commit -m "docs: document multi-call operations"
```

Add `scripts/deploy-ehf.ps1` explicitly only if it changed.

### Task 5: Reconcile, push, deploy, and verify production

**Files:**

- Modify: `CODEX_COORDINATION.md` with nonpersonal verification evidence only

**Step 1: Establish the final clean baseline**

```powershell
git fetch origin main
git status --short
git rev-parse HEAD
git rev-parse origin/main
git diff --check
```

Expected: the worktree is clean, local `main` contains only the planned commits, and the implementation is based on the previously verified `origin/main` history.

**Step 2: Run every release gate**

```powershell
$Python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python -m pytest -q
& $Python -m pytest tests/browser/multi_call.spec.py -q
powershell -NoProfile -File scripts/test-database.ps1
& $Python -m pytest infra/test-install-ehf.py tests/test_deployment_contract.py -q
powershell -NoProfile -File scripts/deploy-ehf.ps1 -WhatIf
```

Expected: every command passes. Stop before deployment on any failure and use `superpowers:systematic-debugging` rather than bypassing a gate.

**Step 3: Confirm deployment prerequisites without exposing secrets**

Verify the configured `ehf-hestia` SSH alias, pinned host identity, documented backup/restore path, and the existence—not the contents—of `/etc/ehf/sql-admin-password`. Confirm again that applicant invitations and outbound mail are disabled.

**Step 4: Push the exact tested commit**

```powershell
git push origin main
git fetch origin main
git rev-parse HEAD
git rev-parse origin/main
```

Expected: the two 40-character SHAs are identical. Save that SHA as `ExpectedCommit`.

**Step 5: Deploy and verify**

```powershell
powershell -NoProfile -File scripts/deploy-ehf.ps1 -Apply -SqlAdminCredentialPath '/etc/ehf/sql-admin-password'
powershell -NoProfile -File scripts/verify-ehf.ps1 -ExpectedCommit <tested-40-character-sha>
```

Expected: migrations `040` through `042` apply successfully; the service and proxy are healthy; EHF-2026 produces the same scoped report behavior; authorized production calls can be inventoried without mutation or cross-call leakage; every call and service-level invitation/mail gate remains disabled. The two-call create/archive/read-only proof has already passed in the isolated transaction-rolled-back database suite; no synthetic production call is created or deleted.

If verification fails, stop traffic-changing work and use the documented rollback command with the explicitly validated previous commit. Do not improvise a destructive database rollback; the schema changes are expand-compatible.

**Step 6: Record evidence and commit the coordination update**

Record only the deployed commit, migration tip, test summaries, health results, and invitation-gate state in `CODEX_COORDINATION.md`. Do not include applicant data, document paths, usernames, or credential material.

```powershell
git add CODEX_COORDINATION.md
git commit -m "docs: record multi-call production rollout"
git push origin main
git fetch origin main
git rev-parse HEAD
git rev-parse origin/main
```

Expected: the evidence commit is on `origin/main` and the worktree is clean.

## Final acceptance criteria

- One shared database hosts multiple fully isolated fellowship calls.
- Every operational and import path is explicitly call-bound.
- Existing EHF-2026 commands remain supported as compatibility wrappers.
- Two-call integration and browser tests cover data, identity, roster, analytics, export, and archive isolation.
- The tested commit is deployed to `ehf-hestia` with migrations through `042`.
- Production EHF-2026 behavior is preserved.
- Applicant invitations and outbound mail remain disabled.
