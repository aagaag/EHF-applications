# EHF Foundation and Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Establish the secure, independently deployable EHF application foundation: repository controls, configuration, SQL schema and permissions, immutable audit, shared ISAB interface shell, health checks, and atomic ISAB01 deployment.

**Architecture:** A two-worker FastAPI/Uvicorn service listens only on `127.0.0.1:8086`. Nginx is the sole local HTTP entry point. A dedicated `ehf_app` SQL login reaches only `EHFApplications` and receives `SELECT` on explicitly published views plus `EXECUTE` on application procedures; direct table DML is denied. Business changes and audit events commit in one SQL transaction. Static entry pages use the shared ISAB shell and call JSON APIs with same-origin credentials.

**Tech Stack:** Python 3.12; FastAPI/Uvicorn; `pyodbc` with ODBC Driver 18; SQL Server; PyJWT/cryptography; plain HTML/CSS/ES modules; pytest; Playwright; systemd; Nginx; PowerShell and Python deployment helpers.

**Global Constraints:** Use `main`; inspect GitHub/default-branch/worktree before edits; copy the official ISAB logo byte-for-byte; derive navigation, help, and authorization indicators from one server-filtered inventory; store durable preferences in SQL; do not introduce browser storage; bind SQL and the app to loopback; do not share service identities, schemas, secrets, or writable directories with Finances 2; and do not add applicant or production-mail behavior in this plan.

## Task 1: Bootstrap the repository and coordination contract

**Files:**

- Create: `.gitignore`
- Create: `AGENTS.md`
- Create: `CODEX_COORDINATION.md`
- Create: `README.md`
- Create: `app/__init__.py`
- Create: `app/requirements.txt`
- Create: `app/requirements-dev.txt`
- Create: `pytest.ini`
- Create: `tests/test_repository_contract.py`

**Step 1: Write the failing repository-contract test**

Assert that the required top-level directories exist, Python dependencies are exactly pinned, the repository has an approved-spec link, `.env`/credentials/PDFs/import output are ignored, and `CODEX_COORDINATION.md` contains no token-like values.

**Step 2: Run the focused test and confirm failure**

Run `python -m pytest tests/test_repository_contract.py -q`.

Expected: failure listing the missing bootstrap files.

**Step 3: Add the minimum bootstrap files**

Pin the runtime packages used by the current ISAB01 FastAPI/SQL baseline (`fastapi`, `uvicorn`, `pyodbc`, `python-multipart`, `python-docx`, `pypdf`, `pypdfium2`, `Pillow`, `PyJWT[crypto]`, `cryptography`, `openpyxl`) and test packages (`pytest`, `httpx`, `playwright`, `axe-playwright-python`). Document setup, test, import, deploy, rollback, and the explicit invitation-send gate in `README.md`.

**Step 4: Run the focused test and confirm success**

Expected: `1 passed` and no dependency with an unpinned version.

**Step 5: Commit**

Commit message: `build: bootstrap EHF portal repository`

## Task 2: Add typed configuration with fail-closed production checks

**Files:**

- Create: `app/config.py`
- Create: `tests/test_config.py`
- Create: `infra/ehf.env.example`

**Step 1: Write failing tests**

Cover development defaults and production failures for missing SQL credential path, encryption keyring path, session pepper path, OTP pepper path, Cloudflare Access issuer/audience, EHF group IDs, Turnstile secret path, allowed host, document root, quarantine root, and mail enablement. Assert that `PRODUCTION_MAIL_ENABLED=true` is rejected unless an approved sender, mail transport, and internal delivery-test receipt are all configured.

**Step 2: Run**

Run `python -m pytest tests/test_config.py -q`.

Expected: import failure because `app.config` does not exist.

**Step 3: Implement**

Create an immutable `Settings` dataclass. Read secrets only from systemd credential files, normalize `ehf.isab.science`, require absolute storage paths, reject overlapping document/quarantine paths, and expose only redacted configuration in diagnostics. Keep `INVITATIONS_ENABLED` and `PRODUCTION_MAIL_ENABLED` false by default.

**Step 4: Re-run**

Expected: all configuration tests pass.

**Step 5: Commit**

Commit message: `feat: add fail-closed EHF configuration`

## Task 3: Create the database migration runner and core schema

**Files:**

- Create: `app/db.py`
- Create: `app/migrations.py`
- Create: `database/migrations/001_database_contract.sql`
- Create: `database/migrations/002_application_core.sql`
- Create: `database/migrations/003_audit_and_preferences.sql`
- Create: `database/tests/001_validate_database_contract.sql`
- Create: `database/tests/002_validate_application_core.sql`
- Create: `database/tests/003_validate_audit_and_preferences.sql`
- Create: `scripts/test-database.ps1`
- Create: `tests/test_migrations.py`

**Step 1: Write failing migration tests**

Test ordered discovery, checksum recording, refusal to alter an already-applied migration, one-transaction application, redacted errors, and idempotent no-op reruns. Add static assertions that every table has a primary key and UTC timestamps and that immutable tables have update/delete guards.

**Step 2: Run**

Run `python -m pytest tests/test_migrations.py -q`.

Expected: failures for missing runner and SQL files.

**Step 3: Implement the database contract**

`001_database_contract.sql` creates `dbo.SchemaMigration` and a schema-version view. `002_application_core.sql` creates strongly typed, independently versioned records for:

- `FellowshipCall` and call-specific deadlines/settings;
- `Applicant`, `ApplicantContact`, and `Application`;
- `EmploymentAffiliation`, `Qualification`, `EligibilityDeclaration`, and `Bibliometrics`;
- `ContributionStatement` with a 1,000-character database constraint;
- `FieldProvenance` with source type and source identifier;
- `ApplicationSectionVersion` and section-level row versions; and
- call/application status lookup constraints.

Preserve missing numeric values as `NULL`, never zero. Store birth year/month but no birth day. Store the exact PhD date. Add deterministic SQL functions or views for age in months/years at the call deadline. Do not store derived age as applicant-entered data.

`003_audit_and_preferences.sql` creates append-only `AuditEvent`, `UserPreference`, and procedures that update a business record and append its audit event in the same transaction. The audit payload records identifiers and before/after facts but rejects secrets, OTPs, tokens, raw documents, and unrestricted free-form request bodies.

**Step 4: Verify against an isolated SQL database**

Run `powershell -File scripts/test-database.ps1 -DatabaseName EHFApplications_Test`.

Expected: migrations `001`–`003` apply, validators print `PASS`, rerun applies zero migrations, and the script drops only the explicitly named test database after confirming its `EHFApplications_Test` prefix.

**Step 5: Run Python tests**

Expected: all migration tests pass.

**Step 6: Commit**

Commit message: `feat: establish EHF database core`

## Task 4: Enforce the least-privileged SQL boundary

**Files:**

- Create: `database/migrations/004_application_permissions.sql`
- Create: `database/tests/004_validate_application_permissions.sql`
- Create: `infra/setup-sql-login.sh`
- Create: `infra/test-sql-login.sh`
- Create: `tests/test_sql_permissions.py`
- Create: `docs/permissions.md`

**Step 1: Write failing positive and negative tests**

As `ehf_app`, prove permitted health/preference procedures work. Prove direct `INSERT`, `UPDATE`, and `DELETE` on every business/audit table fail; cross-database reads fail; schema changes fail; and the login cannot read SQL metadata beyond what execution requires.

**Step 2: Implement**

Create one SQL login and database user with no server role. Grant only `CONNECT`, explicit view `SELECT`, and stored-procedure `EXECUTE`. Use ownership chaining for procedures and explicit `DENY` on table DML and schema control. Generate the password once into `/etc/ehf/sql-app-password` mode `0640`, owner `root:ehf`, and pass it through `LoadCredential`.

**Step 3: Verify**

Run `bash infra/test-sql-login.sh` on ISAB01.

Expected: every intended procedure succeeds, every broader operation prints an expected denial, and the script prints no credential.

**Step 4: Commit**

Commit message: `security: restrict EHF SQL application access`

## Task 5: Build the HTTP skeleton and security middleware

**Files:**

- Create: `app/main.py`
- Create: `app/http.py`
- Create: `app/security_headers.py`
- Create: `app/errors.py`
- Create: `tests/test_health.py`
- Create: `tests/test_security_headers.py`
- Create: `tests/test_error_contract.py`

**Step 1: Write failing endpoint tests**

Test `/health/live`, `/health/ready`, unknown routes, oversized bodies, invalid hosts, forwarded-header trust, JSON error shape, request correlation IDs, cache headers, CSP, frame protection, MIME sniffing protection, referrer policy, and redacted logs.

**Step 2: Implement**

Expose liveness without database access and readiness with a bounded SQL/storage probe that returns no personal data. Accept only `ehf.isab.science`, `127.0.0.1`, and the documented local test host in their corresponding environments. Trust proxy headers only from loopback Nginx. Return `private, no-store` for every authenticated or potentially personal response. Keep health responses `no-store` and free of version/host internals.

**Step 3: Verify**

Run `python -m pytest tests/test_health.py tests/test_security_headers.py tests/test_error_contract.py -q`.

Expected: all tests pass and captured logs contain no request body or authorization value.

**Step 4: Commit**

Commit message: `feat: add secure EHF HTTP runtime`

## Task 6: Implement the shared ISAB shell and durable preferences

**Files:**

- Create: `public/assets/isab-logo.svg`
- Create: `public/assets/site.css`
- Create: `public/assets/shell.js`
- Create: `public/assets/theme.js`
- Create: `public/internal/index.html`
- Create: `public/applicant/index.html`
- Create: `app/navigation.py`
- Create: `app/preferences.py`
- Create: `tests/test_shell_contract.py`
- Create: `tests/test_preferences.py`
- Create: `tests/browser/shell.spec.py`

**Step 1: Write failing shell tests**

Assert the official logo hash matches the current approved ISAB asset, one authorization-filtered inventory generates navigation and help, the lower Settings/Help region is independently reachable, `Authorizations:` appears only where appropriate, no `localStorage`/`sessionStorage` API occurs, and each protected destination is absent for an unauthorized role.

**Step 2: Implement the shell**

Copy the approved ISAB logo byte-for-byte. Reuse the F2 shell structure and dashboard pill tokens: persistent left navigation, independently scrollable upper area, lower Settings/Help, `ehf.isab.science`, application name, purpose statement, footer/last-modified time, 720-pixel drawer with backdrop/Escape dismissal, four skins, inversion, compact spacing, and reduced motion. Keep internal and applicant inventories separate so applicants never learn hidden workspaces or recommendation terminology.

Implement server-backed preferences keyed to the authenticated internal identity or applicant session. Any rounded destination is one semantic link; do not nest an `Open` link. Use Aptos and the 94%-wide/3%-margin responsive layout.

**Step 3: Verify**

Run `python -m pytest tests/test_shell_contract.py tests/test_preferences.py tests/browser/shell.spec.py -q`.

Expected: all tests pass at 1440×900, 1024×768, 720×900, and 390×844; no horizontal overflow; drawer and keyboard interactions pass.

**Step 4: Commit**

Commit message: `feat: adopt the shared ISAB application shell`

## Task 7: Create an atomic ISAB01 deployment and rollback path

**Files:**

- Create: `infra/ehf.service`
- Create: `infra/ehf.nginx.conf`
- Create: `infra/install-isab01.py`
- Create: `infra/test-install-isab01.py`
- Create: `scripts/deploy-isab01.ps1`
- Create: `scripts/verify-isab01.ps1`
- Create: `docs/deployment.md`
- Modify: `CODEX_COORDINATION.md`

**Step 1: Write failing installer/deployment tests**

Test safe release paths, exact Git commit archive input, test-before-activation, symlink-only activation, previous-release rollback, service hardening, loopback bind, Nginx host allowlist, and rejection when local `main` is dirty or differs from `origin/main`.

**Step 2: Implement**

Follow the current Events ISAB01 release pattern with `/opt/ehf/r/{commit-prefix}`, `/opt/ehf/current`, one pinned virtual environment, and atomic symlink switch. Run as locked Unix user `ehf`. Use `LoadCredential` for SQL/encryption/session credentials, `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`, `NoNewPrivileges=true`, and only the exact storage/quarantine paths in `ReadWritePaths`. Configure Nginx to proxy only the exact EHF host to `127.0.0.1:8086`.

Deploy from a clean synchronized `main` using the exact `git archive` bytes, run unit/SQL/install tests before activation, verify `/health/ready`, and automatically reactivate the previous release if health fails.

**Step 3: Verify locally**

Run `python -m pytest infra/test-install-isab01.py -q` and `powershell -File scripts/deploy-isab01.ps1 -WhatIf`.

Expected: installer tests pass; dry run names the exact commit and performs no remote mutation.

**Step 4: Run the complete suite**

Run `python -m pytest -q`.

Expected: all Plan 1 tests pass.

**Step 5: Commit and push**

Commit message: `feat: add atomic EHF ISAB01 deployment`

Push `main`, deploy to ISAB01 using the documented command, and run `powershell -File scripts/verify-isab01.ps1`. Expected: service active, SQL and app loopback-only, readiness healthy, and no public hostname enabled yet.
