# Application Publications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for each implementation task and superpowers:verification-before-completion before reporting success.

**Goal:** Add provenance-preserving, application-scoped publication records and safely import the reviewed EHF 2026 publication manifest without overwriting existing data.

**Architecture:** A new migration adds one canonical child table and three evidence tables. A separate strict manifest importer uses the existing privileged import-run infrastructure, supports plan/apply and idempotent replay, records conflicts, and generates a manual Google Scholar review CSV. Deployment and verification remain API/CLI-first through the established ISAB01 scripts.

**Tech Stack:** SQL Server T-SQL, Python 3.13, pytest, pyodbc, PowerShell, SSH/SCP.

**Spec:** `docs/superpowers/specs/2026-08-23-application-publications-design.md`

## Global Constraints

- Work directly on clean, synchronized `main`; do not create branches or worktrees.
- Use the repository-pinned Python runtime and exact dependency pins.
- Follow red-green-refactor for each behavior.
- Do not commit applicant documents, research output, real manifests, credentials, or generated queues.
- Preserve existing migrations and document-import behavior.
- Stage task files only and create one final commit with the user-specified subject.

### Task 1: Database publication contract

- [ ] Add failing migration inventory and schema-contract tests in `tests/test_migrations.py`, `tests/test_applicant_schema.py`, and a PII-free SQL contract fixture where appropriate.
- [ ] Run the focused tests and confirm failure because migration/validator 021 and publication objects do not exist.
- [ ] Add `database/migrations/021_application_publications.sql` with the four tables, keys, filtered uniqueness, validation constraints, indexes, no-overwrite and append-only triggers, and explicit runtime denials.
- [ ] Add `database/tests/021_validate_application_publications.sql` using transaction-safe PASS/THROW conventions.
- [ ] Advance fixed migration/validator inventories in deployment, bootstrap, principal, and infrastructure tests from 20 to 21.
- [ ] Run focused migration, schema, and deployment-contract tests to green.

### Task 2: Strict manifest planning and Scholar queue

- [ ] Add failing tests in `tests/test_publication_importer.py` for strict schema validation, self-hash and count validation, applicant/work/source/citation relationships, DOI normalization, identity stability, plan-only no-connection behavior, and Scholar CSV contents.
- [ ] Run the focused tests and confirm failure because the publication importer is absent.
- [ ] Add the minimal PII-free fixture under `tests/fixtures/import/`.
- [ ] Implement `app/importer/publications.py` with typed parsing, canonical self-hash validation, deterministic identity functions, exact applicant resolution inputs, plan output, and manual Google Scholar queue generation without scraping.
- [ ] Add a small CLI entry point in `app/importer/run_publications.py` with explicit `--manifest`, `--plan-only`/`--apply`, and `--scholar-queue` arguments.
- [ ] Run the focused importer tests to green.

### Task 3: Additive, idempotent database application

- [ ] Add failing repository tests for new-row insertion, null-only canonical fills, discrepancy preservation and `ImportException` creation, evidence insertion, completed-run replay, failed-run retry, and per-applicant rollback.
- [ ] Run the focused tests and confirm the expected failures.
- [ ] Implement the SQL repository in `app/importer/publications.py` using existing `ImportRun`, `ImportRow`, and `ImportException` conventions and one transaction per applicant.
- [ ] Ensure DOI-first matching followed by identity matching, parameterized SQL only, deterministic payload hashes, and idempotent evidence writes.
- [ ] Run focused importer and database contract tests to green.

### Task 4: Operator workflow and production verification

- [ ] Add failing contract tests for the publication import wrapper, deploy inclusion, production verifier, external-manifest handling, root-only staging permissions, cleanup, and invitation safeguards.
- [ ] Run those tests and confirm failure because the scripts are absent.
- [ ] Add `scripts/import-publications-2026.ps1` for plan/apply transfer and guaranteed cleanup.
- [ ] Add `scripts/verify-publications-2026.ps1` for exact production counts, keys, statuses, conflicts, and disabled invitation/mail state.
- [ ] Update `docs/import-2026.md` with the separate publication lane and manual Scholar procedure, and correct `docs/deployment.md` to the 21-validator contract.
- [ ] Run focused PowerShell/deployment tests and `-WhatIf` deployment to green.

### Task 5: Verify, deliver, deploy, and import

- [ ] Run all focused tests, the complete pytest suite, SQL contract tests available locally, and the deployment `-WhatIf` preflight.
- [ ] Review the diff for secrets, applicant material, unintended changes, SQL safety, no-overwrite behavior, cleanup, and documentation consistency; correct every finding test-first.
- [ ] Stage only the task files and commit once as `feat: add application publication records`.
- [ ] Push `main`, deploy the exact commit to ISAB01, and run the standard production verifier.
- [ ] Apply the external validated publication manifest through the root-only wrapper.
- [ ] Generate the manual Google Scholar review CSV under `C:\Users\aag\Documents\ChatGPT\EHF-pubs\`.
- [ ] Run publication production verification and report imported counts, conflicts, null citation statuses, queue path, deployed commit, and invitation/mail safety state.
