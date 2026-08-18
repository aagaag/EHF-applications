# Applicant Form Simplification Implementation Plan

> **Execution:** Complete autonomously on `main` with test-driven development. Production invitations remain disabled.

**Goal:** Simplify the applicant workspace, add repeatable degrees and DOI-confirmed publications, migrate existing drafts safely, and retain applicant isolation plus administrator/trustee approval.

**Architecture:** Keep the existing section-draft and approval model. Extend the server-owned field inventory with validated array fields, add a fixed-host Crossref lookup service behind the authenticated review API, render the two repeatable controls in the existing applicant shell, and introduce a forward-only SQL migration for legacy compatibility and promotion.

**Technology:** FastAPI, Pydantic, SQL Server JSON/DDL, vanilla JavaScript, CSS grid, pytest, Playwright.

---

## Task 1: Lock the simplified field contract

**Files:**
- Modify: `tests/test_applicant_fields.py`
- Modify: `app/applicant/fields.py`
- Modify: `tests/test_applicant_response_contract.py`
- Modify: `app/applicant/projection.py`
- Modify: `app/applicant/pilot.py`

Write failing tests for the exact new inventory, gender removal, postdoctoral Yes/No validation, repeatable complete degrees, direct Scholar question, conditional URL, removed Scholar citation count, and DOI-list normalization. Implement only the validated contract and projection/pilot compatibility, then run the focused tests.

## Task 2: Add safe Crossref DOI resolution

**Files:**
- Create: `tests/test_applicant_publications.py`
- Create: `app/applicant/publications.py`
- Modify: `tests/test_applicant_review_routes.py`
- Modify: `app/routes/applicant_review.py`
- Modify: `app/main.py`

Write failing service tests for DOI normalization, fixed-host request construction, canonical response mapping, bounded cache, timeout, not-found, and malformed response. Write failing route tests for authentication, CSRF, successful metadata, and sanitized errors. Implement the lookup service, dependency injection, and route, then run the focused tests.

## Task 3: Build the compact, repeatable interface

**Files:**
- Modify: `tests/browser/applicant_review.spec.py`
- Modify: `public/applicant/review.html`
- Modify: `public/assets/applicant-review.js`
- Modify: `public/assets/site.css`

Write failing browser tests for compact identity sizing, three-column employment, degree add/remove/date controls, Scholar URL conditionality, DOI lookup/confirm/remove, saved JSON, responsive reflow, keyboard access, and no horizontal overflow. Implement within the existing approved ISAB shell and retain the unchanged sections. Run the browser test file at desktop, tablet, and phone viewports.

## Task 4: Migrate and promote the new data model

**Files:**
- Create: `database/migrations/017_applicant_form_simplification.sql`
- Create: `database/tests/017_validate_applicant_form_simplification.sql`
- Modify: `tests/test_applicant_schema.py`
- Modify: `tests/test_synthetic_pilot_schema.py`
- Modify: `tests/test_migrations.py`
- Modify: `infra/sql-principal.py`
- Modify: `infra/test-sql-login.sh`

Write failing static/database contract tests for migration ordering, the general conferral-date column, exact portal degree mapping, legacy JSON upgrade, multi-degree promotion, preservation of applicant-draft provenance, and validator inclusion. Implement an idempotent, forward-only migration and validator, then run the SQL contract tests.

## Task 5: Regression verification and review

**Files:**
- Modify only files implicated by failures.

Run formatting/static checks, the full pytest suite, the full Playwright suite, and repository security checks. Review the diff for scope, privacy, authorization, and approved-layout preservation. Obtain an independent code review and correct verified findings with new failing tests.

## Task 6: Commit, push, deploy, and verify

Stage only task files, commit with `feat: simplify applicant application form`, and push `main`. Deploy using the repository-documented production process, apply migration 017, verify the service and authenticated applicant workspace, verify assets load with their expected content type, exercise one non-production DOI lookup, and confirm that production invitations remain disabled.
