# EHF Authorization and Report Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename and reconcile the two active EHF authorization groups, add the confirmed members, remove redundant `Preview surface` labels, and make the Reports area display and download one authoritative 2026 metrics dataset as Excel.

**Architecture:** Preserve the two existing Microsoft Entra group object IDs and rename their display names in place. The application continues resolving authorization by those IDs, gives administrator membership precedence, and derives navigation and pills from the same canonical names. One role-scoped metrics projection drives the responsive report table, both scatter plots, and an audited in-memory XLSX export.

**Tech Stack:** FastAPI, Microsoft Entra/Microsoft Graph, Cloudflare Access, SQL Server, `openpyxl==3.1.5`, pytest, Playwright, Node test runner, PowerShell, and the existing ISAB01 immutable deployment workflow.

## Global Constraints

- Work directly on each repository's clean synchronized GitHub default branch, `main`; do not create a branch or worktree.
- Preserve the existing Entra group object IDs `8e199674-d599-45e1-9daa-d138a0b40753` and `fc584ecb-8be3-4f70-89d0-a5f0ae37f21a`.
- Use the canonical names `EHF-Administrators` and `EHF-Trustees` everywhere.
- Use the ISAB member identities for Adriano Aguzzi, Margaryta Schaltegger, and Elena De Cecco; retain the verified guest identities for Ricky Weissman and Magdalini Polymenidou.
- A person in both groups receives administrator permissions.
- Keep applicant invitations and production mail disabled.
- Do not expose applicant documents, recommendation contents, authentication material, hidden identifiers, or confidential filenames in reports or exports.
- Preserve all approved visual and document content except the explicitly requested `Preview surface` removal and Report additions.
- Keep all Python dependencies exactly pinned and use `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`.

For every PowerShell test block below, first set the explicit project runtime:

```powershell
$Python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
```

---

### Task 1: Rename the application authorization inventory and remove redundant card copy

**Files:**

- Modify: `app/navigation.py`
- Modify: `app/identity.py`
- Modify: `app/internal_preview.py`
- Modify: `public/applicant/index.html`
- Modify: `tests/test_shell_contract.py`
- Modify: `tests/test_production_identity_metrics.py`
- Modify: `tests/test_task6_corrections.py`

**Interfaces:**

- Produces: `INTERNAL_GROUPS.administrators == "EHF-Administrators"` and `INTERNAL_GROUPS.trustees == "EHF-Trustees"`.
- Preserves: administrator-first role selection in `create_app()` when both group names are present.

- [ ] **Step 1: Write failing group-name, dual-membership, and copy tests**

Update the exact-name assertions to the two new names. Add a route test whose principal contains both names and whose metric repository records the requested role:

```python
principal = _identity(INTERNAL_GROUPS.trustees, INTERNAL_GROUPS.administrators)
response = _client(principal, metric_repository=repository).get("/internal/")
assert response.status_code == 200
assert repository.requested_roles == ["EHF-Administrators"]
```

Assert that neither the protected internal HTML nor `public/applicant/index.html` contains `Preview surface`, while `Preview only` remains present.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
& $Python -m pytest tests/test_shell_contract.py tests/test_production_identity_metrics.py tests/test_task6_corrections.py -q
```

Expected: failures show the old canonical names and existing `Preview surface` labels.

- [ ] **Step 3: Apply the smallest production changes**

Change only the two canonical strings in `app/navigation.py` and `app/identity.py`. Remove the `<em>Preview surface</em>` fragment from `_cards()` and from the three applicant cards; preserve card links, labels, help text, and every safety notice.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the same focused command. Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add app/navigation.py app/identity.py app/internal_preview.py public/applicant/index.html tests/test_shell_contract.py tests/test_production_identity_metrics.py tests/test_task6_corrections.py
git commit -m "fix: rename EHF authorization groups"
```

---

### Task 2: Add one-source report visualization and XLSX generation

**Files:**

- Create: `app/report_exports.py`
- Modify: `app/internal_preview.py`
- Modify: `app/main.py`
- Modify: `public/assets/site.css`
- Create: `tests/test_report_exports.py`
- Modify: `tests/test_populated_preview.py`
- Modify: `tests/browser/shell.spec.py`

**Interfaces:**

- Produces: `build_metrics_workbook(records, metadata) -> bytes`.
- Produces: `ReportExportMetadata(actor_identity: str, actor_group: str, generated_at_utc: datetime, call_code: str = "EHF-2026", filters: str = "None")`.
- Produces: authorized `GET /internal/reports/metrics.xlsx` with media type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` and filename `ehf-2026.xlsx`.
- Consumes: the same `MetricRepository.load(role)` result used to render the HTML report.

- [ ] **Step 1: Write failing workbook and HTML parity tests**

Create synthetic records covering Unicode, numeric values, missing values, and a formula-dangerous applicant name. Assert that the workbook contains sheets `Applicant metrics`, `Charts`, and `Export metadata`; uses the exact 13 metrics columns from the SharePoint reference; writes missing values as `NR`; preserves numeric cell types; escapes text beginning with `=`, `+`, `-`, or `@`; includes two scatter-chart objects; and contains no email, token, document, or recommendation fields.

Assert the Reports section contains one responsive metrics table, both existing scatter plots, and a semantic `Download Excel` link to `/internal/reports/metrics.xlsx`. Assert the HTML row count and workbook row count equal the source tuple length.

- [ ] **Step 2: Run the focused tests and verify RED**

```powershell
& $Python -m pytest tests/test_report_exports.py tests/test_populated_preview.py tests/browser/shell.spec.py -q
```

Expected: module/route/table assertions fail because the exporter and download action do not exist.

- [ ] **Step 3: Implement the workbook builder**

Use `openpyxl.Workbook` and `BytesIO`. The first sheet contains title, review-date note, explanatory notes, a frozen/filterable table, typed rows, capped column widths, and Aptos styling. The Charts sheet contains an adjacent auditable data table and two `ScatterChart` objects using total citations with Google Scholar fallback, matching the web plots. The metadata sheet contains only call code, actor stable identity, canonical group, UTC generation time, row count, filters, and a confidential-use notice.

Sanitize untrusted spreadsheet text with:

```python
def safe_excel_text(value: str) -> str:
    return "'" + value if value.startswith(("=", "+", "-", "@")) else value
```

- [ ] **Step 4: Implement the report table and download route**

Render the 13-column dataset in a labelled responsive wrapper without horizontal page overflow. Add a semantic link labelled `Download Excel` outside the clickable Reports card. In the route, authenticate first, choose administrators before trustees, load the role-scoped records once for that request, build the workbook, and return it with `Cache-Control: no-store` and attachment disposition `ehf-2026.xlsx`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the Task 2 focused command. Expected: all selected tests pass with no browser overflow or accessibility violations.

- [ ] **Step 6: Render a synthetic workbook with Microsoft Excel and inspect it**

Create one synthetic export through the production builder, open and export previews with one controlled hidden Excel instance, inspect every worksheet and both charts, then close the workbook and quit only that automation instance in `finally`. Confirm no task-created `EXCEL.EXE` remains.

- [ ] **Step 7: Commit**

```powershell
git add app/report_exports.py app/internal_preview.py app/main.py public/assets/site.css tests/test_report_exports.py tests/test_populated_preview.py tests/browser/shell.spec.py
git commit -m "feat: add EHF Excel report download"
```

---

### Task 3: Add immutable report-export auditing

**Files:**

- Create: `database/migrations/010_report_export_audit.sql`
- Create: `database/tests/010_validate_report_export_audit.sql`
- Modify: `database/tests/001_validate_database_contract.sql`
- Modify: `database/tests/005_validate_application_permissions.sql`
- Modify: `infra/bootstrap-ehf-database.py`
- Modify: `infra/install-isab01.py`
- Modify: `infra/sql-principal.py`
- Modify: `infra/test-sql-login.sh`
- Modify: `infra/test-install-isab01.py`
- Modify: `app/report_exports.py`
- Modify: `app/main.py`
- Modify: `docs/permissions.md`
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_report_exports.py`

**Interfaces:**

- Produces: SQL procedure `dbo.RecordReportExportAudit(@ActorIdentity, @ActorGroup, @RowCount, @Outcome, @FailureStage)`.
- Produces: `ReportAuditRepository.record(metadata, row_count, outcome, failure_stage=None) -> None` and `SqlReportAuditRepository`.

- [ ] **Step 1: Write failing migration, permission, and repository tests**

Assert migration 010 creates a procedure-only execution principal, rejects actor groups outside `EHF-Administrators` and `EHF-Trustees`, accepts only `COMPLETED` or `FAILED`, inserts one append-only `AuditEvent`, grants runtime execution only on the procedure, and never grants runtime table DML. Assert the route records `COMPLETED` after generation and a safe `FAILED` stage on builder failure without returning workbook bytes.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
& $Python -m pytest tests/test_migrations.py tests/test_sql_permissions.py tests/test_report_exports.py -q
```

Expected: migration count/procedure/audit assertions fail.

- [ ] **Step 3: Implement migration 010 and the audit repository**

Create an execution principal that can insert only through `dbo.RecordReportExportAudit`. Validate every argument, use `FOR JSON PATH` for the fixed safe payload keys `actorGroup`, `rowCount`, `format`, `outcome`, and `failureStage`, and append event type `REPORT_EXPORT_COMPLETED` or `REPORT_EXPORT_FAILED`. Update exact runtime-procedure inventories, release bundles, SQL-login probes, validators, and migration-count expectations from 9 to 10.

Call the repository only after authorization. On generation failure, record a fixed allowlisted stage such as `workbook-generation` and return the existing redacted error contract.

- [ ] **Step 4: Run focused and database contract tests and verify GREEN**

Run the Task 3 focused command plus:

```powershell
& $Python -m pytest tests/test_database_bootstrap.py tests/test_repository_contract.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add database app docs/permissions.md tests/test_migrations.py tests/test_report_exports.py
git commit -m "feat: audit EHF report exports"
```

---

### Task 4: Reconcile Entra and Cloudflare authorization sources

**Files:**

- Create: `scripts/reconcile-ehf-entra.ps1`
- Create: `tests/test_entra_group_contract.py`
- Modify in `C:\Users\aag\Documents\GitHub\isab-cloudflare-edge`: `scripts/configure-ehf-access.mjs`
- Modify in `C:\Users\aag\Documents\GitHub\isab-cloudflare-edge`: `scripts/configure-ehf-access.test.mjs`
- Modify in `C:\Users\aag\Documents\GitHub\isab-cloudflare-edge`: `scripts/deploy-events-tunnel.test.mjs`

**Interfaces:**

- Produces: `scripts/reconcile-ehf-entra.ps1 -WhatIf|-Apply` using the installed Microsoft Azure CLI and Microsoft Graph.
- Preserves: the two group IDs and Cloudflare Access rules based on those IDs.

- [ ] **Step 1: Write failing contracts for exact identities, names, IDs, and safe modes**

Assert the script fixes tenant ID `8226a4c2-10fa-4742-b4c0-f4fdb97a0534`, validates that `Get-Command az` resolves to the Microsoft SDK path, reads and verifies both groups before writing, supports `-WhatIf` without Graph writes, PATCHes only display names, adds only missing expected member object IDs, fails on unexpected members, and re-reads exact names/members after apply.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
& $Python -m pytest tests/test_entra_group_contract.py -q
```

In the edge repository run:

```powershell
node --test scripts/configure-ehf-access.test.mjs scripts/deploy-events-tunnel.test.mjs
```

Expected: the EHF application test fails because the reconciliation script is absent; edge assertions still expose old names.

- [ ] **Step 3: Implement the safe idempotent Graph reconciliation**

Use only `C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd rest`. Verify current object IDs and membership first. Desired administrators are Adriano Aguzzi (`d5c5fb6a-f9c3-456c-97b1-20b450647f8c`), Margaryta Schaltegger (`0da50d11-f875-4a4d-8ac8-f7bbd44499d7`), and Elena De Cecco (`70a7cbba-44f0-4689-b600-768b9c05ec6c`). Desired trustees are Adriano Aguzzi plus the existing Ricky Weissman (`7747ffa7-5193-4cc8-9221-08a1dd24b026`) and Magdalini Polymenidou (`09d14671-38e1-4763-8d67-512c9787d379`) guest objects. Never print tokens or credential material.

- [ ] **Step 4: Update the edge repository names without changing rules**

Change only the descriptive `name` fields returned in `authorized_entra_groups` and the corresponding fixtures to `EHF-Administrators` and `EHF-Trustees`. The Cloudflare selectors remain the same two stable Entra IDs, so no Access policy recreation is required.

- [ ] **Step 5: Run focused tests and dry-run reconciliation**

Run both Task 4 test commands and:

```powershell
powershell -NoProfile -File scripts/reconcile-ehf-entra.ps1 -WhatIf
```

Expected: tests pass; dry run reports only the two renames and two missing memberships, with no write.

- [ ] **Step 6: Commit both repositories separately**

In `EHF-applications`:

```powershell
git add scripts/reconcile-ehf-entra.ps1 tests/test_entra_group_contract.py
git commit -m "feat: reconcile EHF Entra groups"
```

In `isab-cloudflare-edge`:

```powershell
git add scripts/configure-ehf-access.mjs scripts/configure-ehf-access.test.mjs scripts/deploy-events-tunnel.test.mjs
git commit -m "fix: rename EHF Entra group labels"
```

---

### Task 5: Verify, apply, push, deploy, and re-verify

**Files:**

- Modify: `CODEX_COORDINATION.md`

**Interfaces:**

- Applies: exact Microsoft Entra group display names and memberships.
- Publishes: both clean `main` branches to GitHub.
- Deploys: the exact EHF application commit to ISAB01 and verifies the live immutable release.

- [ ] **Step 0: Register the EHF-only secret delivery task if still absent**

In `C:\Users\aag\Documents\GitHub\codex-op-broker`, add a narrowly scoped fixed task that retrieves the existing SQL Server administrator password inside the broker and installs it only as `/etc/ehf/sql-admin-password` on `aag@10.10.20.29`, owned by root with mode `0600`. The task must return only a redacted success result, must not print or persist the secret anywhere else, and must not modify the Finances2 credential file. Run the broker repository's focused and full policy tests, commit and push its clean synchronized `main`, install the reviewed policy at `C:\ProgramData\Codex1PasswordBroker\policy.json`, request one reusable capability session, execute the task, and verify only the target path's ownership and mode over SSH.

- [ ] **Step 1: Run complete local verification**

In `EHF-applications`:

```powershell
& $Python -m pytest infra/test-install-isab01.py tests/test_deployment_contract.py -q
& $Python -m pytest -q
powershell -NoProfile -File scripts/deploy-isab01.ps1 -WhatIf
```

In `isab-cloudflare-edge`, run its complete checked-in test command and the focused EHF tests. Expected: zero failures and no warnings that indicate unsafe configuration drift.

- [ ] **Step 2: Apply and verify Entra reconciliation**

```powershell
powershell -NoProfile -File scripts/reconcile-ehf-entra.ps1 -Apply
```

Immediately re-read both group objects and member sets through Microsoft Graph. Confirm the exact names, exact expected member IDs, unchanged group IDs, and administrator-first application behavior.

- [ ] **Step 3: Verify Cloudflare Access remains exact**

Run the supported EHF Access status workflow. Confirm the existing Access application remains configured with the same two group IDs and no stale policy; do not recreate the app or tunnel.

- [ ] **Step 4: Record the handoff and commit**

Append a concise non-secret entry to `CODEX_COORDINATION.md` naming the verified tests and the fact that invitations/mail remain disabled, then commit only that file.

- [ ] **Step 5: Push both synchronized main branches**

Fetch first, refuse divergence or unrelated changes, then push `isab-cloudflare-edge/main` and `EHF-applications/main`. Confirm local `HEAD` equals `origin/main` in both repositories.

- [ ] **Step 6: Deploy the EHF application**

Use the broker-installed EHF-only root credential path without reading its contents. Resolve the pushed commit locally and run:

```powershell
$ExpectedCommit = (git rev-parse HEAD).Trim()
powershell -NoProfile -File scripts/deploy-isab01.ps1 -Apply -SqlAdminCredentialPath '/etc/ehf/sql-admin-password'
powershell -NoProfile -File scripts/verify-isab01.ps1 -ExpectedCommit $ExpectedCommit
```

Expected: migration 010 and its validator pass before the atomic release switch; readiness passes; the service binds only to loopback; invitations and production mail remain false.

- [ ] **Step 7: Run production acceptance checks**

Verify the deployed commit marker, readiness, authorization denial for unauthenticated access, renamed authorization pills for authorized identities, dual-membership administrator precedence, responsive Reports table, and a valid downloadable workbook with three sheets and two charts. Confirm no applicant message was sent and no source document was modified.
