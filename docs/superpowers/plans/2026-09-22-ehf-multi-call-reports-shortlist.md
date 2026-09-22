# EHF Multi-Call Reports and Shortlisting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The primary agent owns migration, SQL authorization, roster ownership, and integration; only explicitly marked presentation/test steps may use `low_cost_worker`.

**Goal:** Make metrics, application details, exports, plots, and A/B/C shortlisting call-scoped, and replace the hardcoded three-person trustee list with an independently configurable ordered roster for every call.

**Architecture:** Migration 042 introduces call-owned roster and selection tables, migrates all migration-038 groups, and adds versioned call-aware metrics/detail/export/shortlist procedures beside the preserved EHF-2026 SQL surface. Python repositories receive `CallContext`; the report renderer consumes server-supplied metadata and roster entries, and the write path validates call, lifecycle, application, active roster membership, and exact Entra ownership in one transaction.

**Tech Stack:** SQL Server/T-SQL, Python dataclasses/protocols, FastAPI, server-rendered HTML/SVG, plain JavaScript/CSS, `openpyxl`, pytest, and browser scenarios.

**Spec:** `docs/superpowers/specs/2026-09-21-ehf-multi-call-architecture-design.md`

## Global Constraints

- Plans 1-2 are committed, pushed, and green before this plan begins.
- This plan owns migration and validator 042.
- Preserve every existing `EHF-2026` A/B/C group, modifier identity, application ID, and recorded timestamp.
- No Python, HTML, JavaScript, or active SQL procedure may contain a handwritten Ricky/Magda/Adriano roster after this plan.
- Administrators configure the roster but cannot write another owner's group.
- Shared calculations and plots receive only the selected call's dataset and active analysis evidence.
- Responsive report rows must not introduce horizontal page scrolling for any supported roster size.

## Review Focus

- Migrated A/B/C values and historical unassigned rows must remain exact.
- Inactive roster members must remain visible in historical audit data but cannot write.
- An administrator who is not the target roster owner must receive neutral denial.
- Call-A application/detail/export IDs must not appear in call B output.
- Report and workbook headings, filenames, cutoff labels, and audit events must use selected-call metadata, not global defaults.

---

### Task 1: Add migration 042 reporting and roster isolation

**Delegation:** Primary agent only.

**Files:**

- Create: `database/migrations/042_call_scoped_reporting_shortlist.sql`
- Create: `database/tests/042_validate_call_scoped_reporting_shortlist.sql`
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_shortlist_migration.py`
- Modify: `tests/test_sql_permissions.py`
- Modify: `infra/install-ehf.py`
- Modify: `infra/bootstrap-ehf-database.py`
- Modify: `infra/sql-principal.py`
- Modify: `infra/test-sql-login.sh`
- Modify: `scripts/test-database.ps1`
- Modify: `tests/test_deployment_contract.py`

**Interfaces:**

- Produces `dbo.FellowshipCallShortlister` and `dbo.CallShortlistSelection`.
- Produces call-aware roster configuration/read/write procedures.
- Adds versioned call-aware metrics, detail, cutoff activation, report-export audit, and shortlist procedures while preserving prior-release EHF-2026 SQL signatures.

- [ ] **Step 1: Write failing migration and parity tests**

```python
def test_call_scoped_shortlist_migration_preserves_group_assignments() -> None:
    sql = (MIGRATION_DIRECTORY / "042_call_scoped_reporting_shortlist.sql").read_text(
        encoding="utf-8"
    )
    for fragment in (
        "CREATE TABLE dbo.FellowshipCallShortlister",
        "CREATE TABLE dbo.CallShortlistSelection",
        "ActorEntraObjectId",
        "DisplayOrder",
        "GroupCode",
        "INSERT dbo.CallShortlistSelection",
        "FROM dbo.TrusteeShortlistSelection",
        "CREATE OR ALTER PROCEDURE dbo.GetInternalApplicationMetricsByCall",
        "CREATE OR ALTER PROCEDURE dbo.RecordReportExportAuditByCall",
    ):
        assert fragment in sql
```

Add a complete active-module inventory test against `sys.sql_modules`: every module containing an `EHF-2026` literal must be classified as an explicit legacy wrapper, migration/test-only synthetic support, or a defect. Include modules originating in migrations 017 and 019, not only the selected report procedures. Assert that call-aware procedures contain no literal call selection and that old tables are not dropped.

- [ ] **Step 2: Run focused tests to verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_migrations.py tests\test_shortlist_migration.py tests\test_sql_permissions.py tests\test_deployment_contract.py -q
```

- [ ] **Step 3: Create call-scoped roster and selection tables**

Create this ownership shape:

```sql
FellowshipCallShortlister(
  FellowshipCallShortlisterId uniqueidentifier PRIMARY KEY,
  FellowshipCallId uniqueidentifier NOT NULL,
  ActorEntraObjectId uniqueidentifier NOT NULL,
  DisplayName nvarchar(120) NOT NULL,
  DisplayOrder int NOT NULL,
  IsActive bit NOT NULL,
  ConfiguredByIdentity nvarchar(255) NOT NULL,
  CreatedAtUtc datetime2(7) NOT NULL,
  DeactivatedAtUtc datetime2(7) NULL,
  RowVersion rowversion,
  UNIQUE(FellowshipCallId, ActorEntraObjectId),
  UNIQUE(FellowshipCallId, DisplayOrder)
)

CallShortlistSelection(
  FellowshipCallId uniqueidentifier NOT NULL,
  ApplicationId uniqueidentifier NOT NULL,
  FellowshipCallShortlisterId uniqueidentifier NOT NULL,
  GroupCode char(1) NULL CHECK (GroupCode IN ('A','B','C') OR GroupCode IS NULL),
  ModifiedByIdentity nvarchar(255) NOT NULL,
  RecordedAtUtc datetime2(7) NOT NULL,
  RowVersion rowversion,
  PRIMARY KEY(FellowshipCallId, ApplicationId, FellowshipCallShortlisterId)
)
```

Add composite foreign keys proving both application and roster entry belong to the supplied call. Deny runtime table DML. Roster reorder uses one serializable transaction, moves affected rows to temporary noncolliding negative positions, writes the final contiguous order, checks row versions, and rolls back fully on any conflict.

- [ ] **Step 4: Backfill the current roster and assignments**

Resolve the unique `EHF-2026` call, insert roster entries from `ShortlistTrustee` in the current Ricky/Magda/Adriano display order, then copy every `TrusteeShortlistSelection` row by joining `TrusteeCode` to the new roster and `ApplicationId` to the same call. Copy `GroupCode`, `ModifiedByIdentity`, and `RecordedAtUtc` exactly. Abort if source and destination counts or values differ.

Leave migrations 037/038 tables intact for rollback. New code reads only the 042 tables, but every successful `EHF-2026` selection write dual-writes `CallShortlistSelection` and `TrusteeShortlistSelection` atomically until a separately approved contract migration. New calls write only the call-scoped table. Test a post-cutover EHF-2026 change and clear followed by a legacy read to prove rollback parity.

- [ ] **Step 5: Implement call-aware SQL procedures**

Create or alter:

```sql
ListFellowshipCallShortlistersByCall @FellowshipCallId, @ActorGroup
ConfigureFellowshipCallShortlisterByCall @FellowshipCallId, @ActorEntraObjectId,
    @DisplayName, @DisplayOrder, @IsActive, @ActorIdentity, @ActorGroup
GetInternalShortlistSelectionsByCall @FellowshipCallId, @ActorIdentity,
    @ActorGroup, @ActorEntraObjectId
SetInternalShortlistSelectionByCall @FellowshipCallId, @ApplicationId,
    @FellowshipCallShortlisterId, @GroupCode, @ActorIdentity,
    @ActorGroup, @ActorEntraObjectId
GetInternalApplicationMetricsByCall @FellowshipCallId, @ActorGroup
GetInternalApplicantMetricDetailByCall @FellowshipCallId, @ApplicationId, @ActorGroup
ActivateCitationMetricCutoffRunByCall @FellowshipCallId, @ImportRunId
RecordReportExportAuditByCall @FellowshipCallId, @AnalysisProfileCode,
    @ActorIdentity, @ActorGroup, @RowCount, @Outcome, @FailureStage
```

`SetInternalShortlistSelectionByCall` must require `InternalSelectionStatus='OPEN'`, exact application/call ownership, active roster membership, and `ActorEntraObjectId` equality with the roster owner. Administrator role does not bypass ownership. It writes the call-scoped selection, EHF-2026 legacy mirror when applicable, and append-only audit event atomically.

Create call-aware versions of the latest active metrics/detail/report/cutoff definitions introduced across migrations 009, 010, 017, 019, 020, 024, 025, 028-031, 034, and 036. Keep calculation expressions unchanged; replace only literal-call resolution with the call parameter and ensure every subquery remains within the application/call boundary. Preserve old signatures and their EHF-2026 behavior so the previous application release remains runnable after migration 042.

- [ ] **Step 6: Implement validator 042 and update inventories**

The validator creates calls A/B, different rosters, and applications; proves dynamic roster counts/order, an atomic two-row order swap, owner-only writes, admin non-owner denial, inactive denial, cross-call denial, report row isolation, and export audit call IDs. It validates exact migrated and post-write `EHF-2026` legacy/call-scoped parity, executes prior-release procedure signatures, verifies runtime DML denial, then rolls back synthetic data.

- [ ] **Step 7: Run focused and isolated SQL verification**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_migrations.py tests\test_shortlist_migration.py tests\test_sql_permissions.py tests\test_deployment_contract.py -q
powershell -NoProfile -File scripts\test-database.ps1
```

- [ ] **Step 8: Commit migration 042**

```powershell
git add database/migrations/042_call_scoped_reporting_shortlist.sql database/tests/042_validate_call_scoped_reporting_shortlist.sql tests/test_migrations.py tests/test_shortlist_migration.py tests/test_sql_permissions.py infra/install-ehf.py infra/bootstrap-ehf-database.py infra/sql-principal.py infra/test-sql-login.sh scripts/test-database.ps1 tests/test_deployment_contract.py
git commit -m "feat: scope reports and shortlists by call"
```

### Task 2: Parameterize metrics, details, and exports

**Delegation:** Primary agent owns repositories and audit. **Low-cost eligible:** after metadata interfaces are merged, one worker may own only the call-derived workbook label assertions in `tests/test_report_exports.py`.

**Files:**

- Modify: `app/metrics.py`
- Modify: `app/report_exports.py`
- Modify: `app/applicant_detail.py`
- Modify: `app/main.py`
- Modify: `tests/test_production_identity_metrics.py`
- Modify: `tests/test_metric_detail_route.py`
- Modify: `tests/test_report_exports.py`
- Modify: `tests/test_applicant_detail.py`

**Interfaces:**

```python
class MetricRepository(Protocol):
    def load(self, call_id: UUID, canonical_group: str) -> tuple[PreviewApplicantMetric, ...]: ...
    def load_detail(self, call_id: UUID, application_id: UUID, canonical_group: str) -> ApplicantDetail: ...

@dataclass(frozen=True, slots=True)
class ReportExportMetadata:
    fellowship_call_id: UUID
    call_code: str
    display_name: str
    analysis_profile_code: str
    citation_cutoff_label: str
    actor_identity: str
    actor_group: str
    generated_at_utc: datetime
```

- [ ] **Step 1: Write failing two-call repository/export tests**

Verify call ID appears in every SQL call, call-A records never enter call-B renderer/workbook, filenames are slug-derived and safe, metadata sheet uses selected-call values, and audit receives call ID/profile on success and failure.

- [ ] **Step 2: Run focused tests to verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_production_identity_metrics.py tests\test_metric_detail_route.py tests\test_report_exports.py tests\test_applicant_detail.py -q
```

- [ ] **Step 3: Implement call-aware metrics and export metadata**

Pass `call_id` into SQL procedures and remove Python defaults such as `call_code='EHF-2026'`. Make workbook headings, citation labels, metadata, and `Content-Disposition` derive from validated call context and active cutoff evidence. Keep formulas, plots, color assignment, callouts, accessibility descriptions, and safe Excel text unchanged.

- [ ] **Step 4: Run focused tests and workbook render check**

Run Step 2's tests. Generate synthetic call-A and call-B workbooks, open them with the existing workbook inspection path, and assert their rows, labels, chart series, and metadata remain separated.

- [ ] **Step 5: Commit report parameterization**

```powershell
git add app/metrics.py app/report_exports.py app/applicant_detail.py app/main.py tests/test_production_identity_metrics.py tests/test_metric_detail_route.py tests/test_report_exports.py tests/test_applicant_detail.py
git commit -m "feat: parameterize reports by fellowship call"
```

### Task 3: Replace hardcoded shortlisters with the dynamic roster

**Delegation:** Primary agent only — owner authorization and roster integration.

**Files:**

- Modify: `app/shortlist.py`
- Modify: `app/main.py`
- Modify: `tests/test_shortlist.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class CallShortlister:
    shortlister_id: UUID
    display_name: str
    display_order: int
    is_active: bool
    editable: bool

@dataclass(frozen=True, slots=True)
class ShortlistState:
    roster: tuple[CallShortlister, ...]
    assignments: Mapping[tuple[str, UUID], str]

class ShortlistRepository(Protocol):
    def load(self, call_id: UUID, actor_identity: str, actor_group: str,
             entra_object_id: UUID | None) -> ShortlistState: ...
    def set(self, call_id: UUID, application_id: UUID, shortlister_id: UUID,
            group: str | None, actor_identity: str, actor_group: str,
            entra_object_id: UUID | None) -> str | None: ...
    def configure(self, call_id: UUID, change: ShortlisterChange,
                  actor_identity: str, actor_group: str) -> CallShortlister: ...
```

- [ ] **Step 1: Write failing dynamic roster and owner tests**

Cover roster sizes 0/1/3/many, configured ordering and atomic swaps, same person in two calls, inactive rows, owner edit, administrator non-owner denial, clearing an assignment, and cross-call application/roster combinations. Cleared/unassigned entries are omitted from `ShortlistState.assignments`; values are always `A`, `B`, or `C`, never `None`, while historical inactive assigned rows retain their labels.

- [ ] **Step 2: Run focused tests to verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_shortlist.py -q
```

- [ ] **Step 3: Implement dynamic repository and canonical APIs**

Remove `RICKY_ENTRA_OBJECT_ID`, `MAGDA_ENTRA_OBJECT_ID`, `ADRIANO_ENTRA_OBJECT_ID`, `TRUSTEE_OBJECT_IDS`, and `editable_trustee`. Map roster rows from SQL and mark `editable=True` only where the active row's Entra object matches the signed-in identity.

Expose:

- `GET /api/internal/calls/{call_slug}/shortlisters`;
- administrator-only `POST /api/internal/calls/{call_slug}/shortlisters` for add/rename/reorder/deactivate; and
- `POST /api/internal/calls/{call_slug}/applicants/{application_id}/shortlist/{shortlister_id}` for owner A/B/C/clear writes.

Validate exact payload keys and same-origin writes. Do not expose another person's object ID to clients; APIs use opaque roster-entry IDs and display names.

The APIs support the roster editor rendered in Task 4. Configuration never grants an administrator ownership of another shortlister's A/B/C selections.

- [ ] **Step 4: Run focused tests**

Run Step 2's command. Expected: all dynamic roster, owner-only, and cross-call cases pass.

- [ ] **Step 5: Commit roster services and APIs**

```powershell
git add app/shortlist.py app/main.py tests/test_shortlist.py
git commit -m "feat: configure shortlisters per call"
```

### Task 4: Render dynamic responsive shortlisting

**Delegation:** Primary agent owns markup/behavior integration. **Low-cost eligible:** once markup selectors are fixed, delegate `public/assets/site.css` only for the specified responsive pass, with no HTML/JS changes.

**Files:**

- Modify: `app/internal_preview.py`
- Modify: `public/assets/shell.js`
- Modify: `public/assets/site.css`
- Modify: `tests/browser/shortlist.spec.py`
- Modify: `tests/browser/shell.spec.py`
- Modify: `tests/test_populated_preview.py`

- [ ] **Step 1: Write failing renderer/browser scenarios**

Require dynamic configured names/order, zero-roster empty state, one and many roster entries, administrator roster add/rename/reorder/deactivate controls, trustee configuration-control absence, owner A/B/C buttons only on the owner's entry, administrator non-owner read-only output, cleared/unassigned rendering, inactive historical label, long names, keyboard operation, live save/revert status, nested-control protection from row-modal opening, four skins, and no page overflow at 1920x1080, 1366x768, 720x900, and 390x844.

- [ ] **Step 2: Run focused browser tests to verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_populated_preview.py tests\browser\shortlist.spec.py tests\browser\shell.spec.py -q
```

- [ ] **Step 3: Implement roster-driven markup and behavior**

Iterate `ShortlistState.roster`; never enumerate person codes in the renderer. At widths/counts that fit, use generated roster columns. Otherwise render a single labelled shortlist cell containing a wrapping subgrid of `display name + assignment/control`. Buttons carry `shortlister_id`, application ID, and group only; JavaScript builds the canonical call-scoped endpoint from the current URL.

Render an administrator-only roster editor in `/internal/calls/{call_slug}/` with add, rename, atomic reorder, and deactivate actions. Trustees see the ordered roster and state but no configuration controls.

On save failure, restore the previous pressed state and announce a neutral failure. Ignore row open gestures originating inside shortlist buttons/groups. Keep 44-pixel targets and visible focus.

- [ ] **Step 4: Implement the responsive CSS pass**

Use fluid `minmax(0, ...)`, wrapping, and labelled mobile cards. Do not add a page-level horizontal scroller or fixed minimum table width. Preserve approximately 3% side margins and existing report plot layouts.

- [ ] **Step 5: Run renderer/browser scenarios**

Run Step 2's command and JavaScript syntax checks already used by the repository. Expected: all roster sizes and viewports pass without horizontal overflow.

- [ ] **Step 6: Commit dynamic shortlist presentation**

```powershell
git add app/internal_preview.py public/assets/shell.js public/assets/site.css tests/test_populated_preview.py tests/browser/shortlist.spec.py tests/browser/shell.spec.py
git commit -m "feat: render dynamic call shortlists"
```

### Task 5: Expose canonical call workspaces and verify parity

**Delegation:** Primary agent only.

**Files:**

- Modify: `app/main.py`
- Modify: `app/navigation.py`
- Modify: `tests/test_populated_preview.py`
- Modify: `tests/test_report_exports.py`
- Modify: `tests/test_shortlist.py`
- Modify: `CODEX_COORDINATION.md`

- [ ] **Step 1: Write failing canonical workspace and compatibility tests**

Require `/internal/calls/ehf-2026/` to render the exact current 2026 dataset under call-derived titles, a second call to show only its fixture, legacy report/detail/shortlist APIs to act only as explicit 2026 wrappers, and unknown/new calls never to flow through legacy endpoints.

- [ ] **Step 2: Run focused tests to verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_populated_preview.py tests\test_report_exports.py tests\test_shortlist.py -q
```

- [ ] **Step 3: Wire the canonical workspace**

Resolve call and READ grant before loading metrics/shortlists. Build report export, detail, shortlist, and document URLs from the selected slug. Remove visible `2026` literals unless they come from `EHF-2026` call metadata or its activated cutoff evidence.

- [ ] **Step 4: Run focused, full, browser, SQL, and deployment checks**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_populated_preview.py tests\test_report_exports.py tests\test_shortlist.py -q
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\browser\*.spec.py -q
powershell -NoProfile -File scripts\test-database.ps1
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest infra\test-install-ehf.py tests\test_deployment_contract.py -q
```

- [ ] **Step 5: Record and publish Plan 3**

```powershell
git add app/main.py app/navigation.py tests/test_populated_preview.py tests/test_report_exports.py tests/test_shortlist.py CODEX_COORDINATION.md
git commit -m "feat: activate call-scoped report workspaces"
git push origin main
git fetch origin main
git diff --exit-code origin/main
```
