# Pending Publication Review Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auditable, instant-action internal queue for classifying pending publication records.

**Architecture:** Migration 043 supplies role-scoped list and decision procedures on the append-only publication-review model. A small repository and FastAPI route render the internal page and JSON action boundary; browser code posts a decision and removes only the successfully updated item.

**Tech Stack:** Python 3.13, FastAPI, SQL Server T-SQL, vanilla JavaScript, CSS, pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-pending-publication-review-design.md`

## Global Constraints

- Work on clean synchronized `main`, use the pinned Python runtime, and never commit applicant data or credentials.
- `PUBLISHED`, `ACCEPTED_PREPRINT`, and `NON_PUBLICATION` are the only UI decisions; Remove means the latter, never deletion.
- The latest `PENDING_REVIEW` disposition alone defines the queue; app runtime remains denied direct publication-table access.
- Same-origin checks, canonical group selection, append-only review rows, and audit records are required for every write.

## Review Focus

- A paper changed by another reviewer must remain visible and show an error rather than overwrite the newer review.
- Sparse unresolved records must show their raw citation, and Published must still count after reviewer classification.
- A caller without either internal group must receive no page or API detail.
- A malformed or cross-origin write must create no review row.
- A double click must not create two decisions; the client disables an item while its request is in flight.

### Task 1: Publication-review database boundary

**Files:**
- Create: `database/migrations/043_pending_publication_review_queue.sql`
- Create: `database/tests/043_validate_pending_publication_review_queue.sql`
- Modify: migration inventories in `database/tests/001_validate_database_contract.sql`, `infra/bootstrap-ehf-database.py`, `infra/install-ehf.py`, `infra/sql-principal.py`, `infra/test-sql-login.sh`, `scripts/test-database.ps1`, and `tests/test_migrations.py`
- Test: `tests/test_pending_publication_review_schema.py`

**Interfaces:**
- Produces: `dbo.ListPendingPublicationReviews @ActorGroup` and `dbo.RecordPendingPublicationReview @ApplicationPublicationId, @ReviewDisposition, @ReviewerIdentity, @ActorGroup`.
- Consumed by: `SqlPendingPublicationReviewRepository` in Task 2.

- [ ] **Step 1: Write failing schema tests** asserting migration 043, its validator, both procedures, runtime execute grants, stale-state locking, latest-pending selection, full citation columns, and 43-entry inventories.
- [ ] **Step 2: Run** `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_pending_publication_review_schema.py tests/test_migrations.py -q` **and confirm failure** because migration 043 is absent.
- [ ] **Step 3: Implement migration and validator.** List canonical and raw bibliographic values with applicant name; write one locked transaction that accepts only the three decisions, requires latest `PENDING_REVIEW`, calls the append-only recorder, and grants only the procedures. Alter existing statistics projection so manually reviewed published/preprint records count regardless of metadata resolution, leaving citation metrics resolved-only.
- [ ] **Step 4: Run the focused tests** and confirm green.

### Task 2: Repository, internal routes, and immediate page

**Files:**
- Create: `app/pending_publication_review.py`, `app/routes/pending_publication_review.py`, `public/internal/review-pending-papers.html`, `public/assets/pending-publication-review.js`
- Modify: `app/main.py`, `app/navigation.py`, `public/assets/site.css`
- Test: `tests/test_pending_publication_review.py`, `tests/test_shell_contract.py`

**Interfaces:**
- Consumes: Task 1 procedures.
- Produces: `GET /internal/review-pending-papers`, `GET /api/internal/pending-publications`, and `POST /api/internal/pending-publications/{id}/{decision}`.

- [ ] **Step 1: Write failing HTTP/render tests** for navigation visibility, group denial, complete citation/raw-citation serialization, same-origin protection, decision mapping, stale response behavior, and immediate row removal hooks.
- [ ] **Step 2: Run** `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_pending_publication_review.py tests/test_shell_contract.py -q` **and confirm failure** because the queue route is absent.
- [ ] **Step 3: Implement the smallest repository, routes, static page, JavaScript and CSS.** Use the existing internal shell navigation; choose administrator before trustee when both groups are present; render escaped full denominations; disable the row while posting; remove only on HTTP success and leave errors visible.
- [ ] **Step 4: Run focused tests** and confirm green.

### Task 3: Full verification, release, and production check

**Files:**
- Modify only files required by Tasks 1–2.

- [ ] **Step 1: Run** the complete pytest suite with the pinned runtime and `powershell -NoProfile -File scripts\test-database.ps1` when its local SQL prerequisites are available.
- [ ] **Step 2: Inspect** `git diff --check` and the staged file list; correct any finding with a failing regression test first.
- [ ] **Step 3: Commit** the feature files as `feat: add pending publication review queue`, push `main`, deploy with `scripts\deploy-ehf.ps1 -Apply -SqlAdminCredentialPath '/etc/ehf/sql-admin-password'`, and verify the deployed health endpoint and commit marker.
