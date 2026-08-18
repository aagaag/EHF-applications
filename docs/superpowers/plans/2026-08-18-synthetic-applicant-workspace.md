# Synthetic Applicant Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an EHF administrator create and complete a database-marked synthetic applicant through the existing applicant form without creating Entra access, sending invitations, or affecting real applicant workflows.

**Architecture:** Migration 019 adds an authoritative synthetic-workspace marker and an administrator-bound third applicant-session source while preserving the legacy session contract for fail-closed rollback. A same-origin administrator endpoint creates the record and session atomically, and the existing form reuses its normal save, confirmation, and DOI lookup services while server-side guards block documents, final submission, approval, reporting, and provisioning.

**Tech Stack:** FastAPI, Microsoft SQL Server, PyODBC, HTML/CSS ES modules, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-18-synthetic-applicant-workspace-design.md`

## Global Constraints

- Work directly on synchronized `main` and preserve all previously approved source documents.
- Write and run the smallest failing behavior test before every production change.
- The browser supplies no application, applicant, email, Entra object, or session identity identifiers.
- Every synthetic applicant request must revalidate `EHF-Administrators` and the exact creating identity.
- Synthetic workspaces never send invitations or mail and never create Entra records.
- Production invitations and production mail remain disabled.

---

### Task 1: Add the synthetic SQL boundary

**Files:**
- Create: `database/migrations/019_synthetic_applicant_workspace.sql`
- Create: `database/tests/019_validate_synthetic_applicant_workspace.sql`
- Modify: `infra/sql-principal.py`
- Modify: `infra/test-sql-login.sh`
- Modify: `infra/test-install-isab01.py`
- Modify: `scripts/test-database.ps1`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Produces: `CreateSyntheticApplicantWorkspace`, `GetApplicantSessionV19`, `ApplicantSyntheticWorkspace`, and the version-19 session result contract.

- [ ] Write failing migration inventory, permission, behavioral SQL, and rollback-contract tests covering server-generated IDs, exact administrator actor binding, exclusion guards, and legacy-session denial.
- [ ] Run the focused migration/deployment tests and confirm they fail because version 019 is absent.
- [ ] Add migration 019 and the minimum installer/inventory changes. Preserve the six-column legacy `GetApplicantSession` contract and add the synthetic actor only to `GetApplicantSessionV19`.
- [ ] Run the focused tests and database validator until they pass.

### Task 2: Add administrator-bound synthetic sessions

**Files:**
- Modify: `app/auth/applicant.py`
- Modify: `app/applicant/sql_pilot.py`
- Create: `app/applicant/synthetic.py`
- Test: `tests/test_synthetic_applicant_workspace.py`

**Interfaces:**
- Consumes: `CreateSyntheticApplicantWorkspace` and `GetApplicantSessionV19`.
- Produces: `SyntheticApplicantWorkspaceService.create(actor: str, actor_group: str) -> NewApplicantSession` and `ApplicantSessionContext.synthetic_actor_identity`.

- [ ] Write failing service/repository tests proving exact actor binding, three-way session-source validation, and fail-closed lookup after closure.
- [ ] Run the focused tests and confirm the expected missing-service/session-source failures.
- [ ] Implement the minimal domain and SQL repository code, deriving token hashes server-side and binding only the returned generated application.
- [ ] Run the focused tests until they pass.

### Task 3: Add the browser creation flow and request guards

**Files:**
- Create: `app/routes/internal_synthetic.py`
- Modify: `app/main.py`
- Modify: `app/routes/applicant_entra.py`
- Modify: `app/routes/applicant_documents.py`
- Modify: `app/routes/applicant_finalize.py`
- Modify: `public/internal/applicant-review.html`
- Modify: `public/assets/internal-applicant-review.js`
- Modify: `public/applicant/review.html`
- Modify: `public/applicant/documents.html`
- Modify: `public/applicant/final-review.html`
- Modify: `public/assets/applicant-review.js`
- Modify: `public/assets/applicant-documents.js`
- Modify: `public/assets/applicant-finalize.js`
- Modify: `public/assets/site.css`
- Test: `tests/test_synthetic_applicant_routes.py`
- Test: `tests/browser/applicant_synthetic_workspace.spec.py`

**Interfaces:**
- Consumes: `SyntheticApplicantWorkspaceService` and synthetic session context.
- Produces: `POST /api/internal/synthetic-applicants`, a secure redirect session, and `syntheticAdmin` session-probe state.

- [ ] Write failing route tests for administrator creation, trustee/nonmember neutral denial, same-origin enforcement, exact creator replay denial, and server-side document/final-submit blocking.
- [ ] Write a failing browser test for the whole-card action, persistent banner, existing form reuse, keyboard operation, four skins, and phone/desktop containment.
- [ ] Run both focused suites and confirm failures arise from the missing flow.
- [ ] Implement the route, middleware distinction, UI action/banner, and action hiding without adding a second form renderer.
- [ ] Run the focused suites until they pass.

### Task 4: Verify, deploy, and execute the synthetic workflow

**Files:**
- Modify: `CODEX_COORDINATION.md`

**Interfaces:**
- Consumes: the completed production browser workflow.
- Produces: one production synthetic workspace containing complete fantasy data and ten confirmed real DOI publications.

- [ ] Run Python syntax checks, JavaScript syntax checks, all application/infra tests, every browser spec, all SQL validators, and `git diff --check`.
- [ ] Request independent code review and correct every Critical or Important finding with a new failing test.
- [ ] Commit only task files, push synchronized `main`, deploy with the documented ISAB01 command, and run the live verifier.
- [ ] In the in-app browser, create the synthetic workspace; enter all five sections; add and confirm each of the ten verified DOIs; inspect final review; and verify the synthetic banner throughout.
- [ ] Query only non-secret production postconditions: one new synthetic workspace, ten persisted DOI rows in the synthetic draft, no pending synthetic approval/document records, no Entra/access-request/invitation rows, and invitation/mail flags still false.
- [ ] Record the non-personal synthetic pilot result in `CODEX_COORDINATION.md` and rerun repository-state verification.
