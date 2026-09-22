# EHF Multi-Call Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The primary agent performs schema and authorization work; only a step explicitly marked **Low-cost eligible** may be delegated.

**Goal:** Establish database-enforced call ownership, typed call lifecycle/grants, frozen internal/public call contexts, and authorized call inventory/create/transition flows without changing current `EHF-2026` behavior.

**Architecture:** Migration 040 expands the existing `FellowshipCall` and `Applicant` model, backfills `EHF-2026`, and exposes execution-only stored procedures for resolving, listing, creating, and transitioning calls. A new `app.calls` boundary maps those procedures into immutable Python types; FastAPI uses that boundary for the call inventory and never derives call context from an object identifier.

**Tech Stack:** SQL Server 2025/T-SQL, Python 3.12, FastAPI, `pyodbc`, dependency-free server-rendered HTML, pytest, and browser scenarios.

**Spec:** `docs/superpowers/specs/2026-09-21-ehf-multi-call-architecture-design.md`

## Global Constraints

- Follow every constraint in `2026-09-22-ehf-multi-call-implementation-index.md`.
- Start from migration 039; this plan owns migration and validator 040.
- Preserve existing `FellowshipCallId` and `ApplicantId` values.
- Seed `EHF-2026` with `PublicSlug='ehf-2026'`, `AnalysisProfileCode='ehf-standard-v1'`, applicant review open, internal selection open, and invitations disabled.
- Only the canonical `EHF-Administrators` group may create or transition calls.
- Newly created calls are `DRAFT` with applicant review, internal selection, and invitations disabled.

## Review Focus

- Duplicate or unsafe slugs must be rejected before a call row is created.
- An applicant already linked to applications from two calls must abort the migration before any ownership backfill is committed.
- A trustee without an active grant must not resolve or list a call.
- A failed lifecycle transition must not change status, timestamps, or audit rows.
- Legacy `EHF-2026` metrics and shortlist procedures must remain callable until Plan 3 replaces them.

---

### Task 1: Add migration 040 call tenancy and access grants

**Delegation:** Primary agent only — database and authorization boundary.

**Files:**

- Create: `database/migrations/040_multi_call_foundation.sql`
- Create: `database/tests/040_validate_multi_call_foundation.sql`
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_applicant_schema.py`
- Modify: `tests/test_sql_permissions.py`
- Modify: `infra/install-ehf.py`
- Modify: `infra/bootstrap-ehf-database.py`
- Modify: `infra/sql-principal.py`
- Modify: `infra/test-sql-login.sh`
- Modify: `scripts/test-database.ps1`
- Modify: `tests/test_deployment_contract.py`

**Interfaces:**

- Produces: `dbo.FellowshipCall.PublicSlug`, `CompactTitle`, `ApplicantReviewStatus`, `InternalSelectionStatus`, `InvitationsEnabled`, and `AnalysisProfileCode`.
- Produces: `dbo.FellowshipCallGroupGrant(FellowshipCallId, GroupName, AccessRole, IsActive, ...)`.
- Produces: `dbo.Applicant.FellowshipCallId` and composite call/applicant ownership.
- Produces procedures: `ListAuthorizedFellowshipCalls`, `GetAuthorizedFellowshipCallBySlug`, `GetPublicFellowshipCallBySlug`, `CreateFellowshipCall`, `TransitionFellowshipCall`, and `SetFellowshipCallGroupGrant`.

- [ ] **Step 1: Write the failing migration inventory and contract tests**

Add the next migration and validator to the exact inventories and assert the essential contract:

```python
def test_multi_call_foundation_is_migration_040() -> None:
    migration = (MIGRATION_DIRECTORY / "040_multi_call_foundation.sql").read_text(
        encoding="utf-8"
    )
    for fragment in (
        "PublicSlug",
        "AnalysisProfileCode",
        "CREATE TABLE dbo.FellowshipCallGroupGrant",
        "ALTER TABLE dbo.Applicant",
        "CREATE PROCEDURE dbo.GetAuthorizedFellowshipCallBySlug",
        "CREATE PROCEDURE dbo.GetPublicFellowshipCallBySlug",
        "CREATE PROCEDURE dbo.CreateFellowshipCall",
        "CREATE PROCEDURE dbo.TransitionFellowshipCall",
    ):
        assert fragment in migration
    assert "EHF-2026" in migration
    assert "ehf-2026" in migration
    assert "ehf-standard-v1" in migration
```

Update the existing exact-list assertions from 39 to 40 migrations and validators.

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_migrations.py tests\test_applicant_schema.py tests\test_sql_permissions.py tests\test_deployment_contract.py -q
```

Expected: failure because migration/validator 040 and their inventory entries do not exist.

- [ ] **Step 3: Implement the additive schema and `EHF-2026` backfill**

Use `SET XACT_ABORT ON`. Add the new `FellowshipCall` columns nullable and backfill every existing call. Derive each slug deterministically from the lowercased `CallCode` only when it satisfies the final SQL/Python slug grammar; use current display/deadline/status data, set non-2026 review/selection stages to `DISABLED`, use `ehf-standard-v1`, and keep invitations disabled. Give `EHF-2026` its exact approved metadata and existing open review/selection state. Abort before mutation if any existing call cannot be mapped uniquely. Validate uniqueness and typed values, then make required columns non-null. Enforce the same grammar in SQL and Python:

```sql
CHECK (PublicSlug COLLATE Latin1_General_100_BIN2 NOT LIKE '%[^a-z0-9-]%'
       AND LEN(PublicSlug) BETWEEN 3 AND 80
       AND PublicSlug NOT LIKE '-%'
       AND PublicSlug NOT LIKE '%-'
       AND PublicSlug NOT LIKE '%--%')
CHECK (ApplicantReviewStatus IN ('DISABLED','OPEN','CLOSED'))
CHECK (InternalSelectionStatus IN ('DISABLED','OPEN','LOCKED'))
CHECK (AnalysisProfileCode IN ('ehf-standard-v1'))
UNIQUE (PublicSlug)
```

Before backfilling `Applicant.FellowshipCallId`, emit and validate a preflight count, then abort if any `ApplicantId` joins applications from more than one distinct call. Backfill through `Application`, make the column non-null, add `UNIQUE(FellowshipCallId, ApplicantId)`, and add a composite foreign key from `Application(FellowshipCallId, ApplicantId)` to the applicant pair without dropping the existing foreign keys. A repeated human in a later call receives a new `ApplicantId`; the two-call importer acceptance test in Plan 4 proves that matching name/email data never reuses the call-A applicant row in call B.

Create `FellowshipCallGroupGrant` with constrained roles `ADMINISTER` and `READ`, an active flag, audit columns, and unique `(FellowshipCallId, GroupName, AccessRole)`. Seed active administrator grants on every existing call and retain the approved trustee read grant on `EHF-2026`; do not make a synthetic/pilot call trustee-visible by accident.

- [ ] **Step 4: Implement execution-only call procedures**

Each procedure must validate the canonical actor group and use no dynamic SQL:

```sql
GetAuthorizedFellowshipCallBySlug
    @PublicSlug nvarchar(80), @ActorGroup nvarchar(128), @RequiredRole varchar(16)

GetPublicFellowshipCallBySlug
    @PublicSlug nvarchar(80)

ListAuthorizedFellowshipCalls
    @ActorGroup nvarchar(128)

CreateFellowshipCall
    @CallCode nvarchar(50), @PublicSlug nvarchar(80), @DisplayName nvarchar(200),
    @CompactTitle nvarchar(120), @ApplicationDeadlineUtc datetime2(7),
    @ActorIdentity nvarchar(255), @ActorGroup nvarchar(128)

TransitionFellowshipCall
    @FellowshipCallId uniqueidentifier, @CallStatus varchar(20),
    @ApplicantReviewStatus varchar(20), @InternalSelectionStatus varchar(20),
    @ActorIdentity nvarchar(255), @ActorGroup nvarchar(128),
    @ExpectedRowVersion binary(8)
```

`GetPublicFellowshipCallBySlug` returns only public call metadata and stage/deadline fields; it exposes no grants, counts, identities, or unpublished object IDs and returns no row when the call is not public at that stage. `ListAuthorizedFellowshipCalls` also returns applicant count, latest completed import time, activated analysis evidence, active roster count/state, and selection state. Migration 040 derives the legacy EHF-2026 roster summary; migration 042 replaces it with the new roster table.

`CreateFellowshipCall` inserts a DRAFT call plus administrator and trustee group grants in one transaction. `TransitionFellowshipCall` rejects any attempt to enable invitations, rejects illegal transitions, uses optimistic concurrency, and writes an `AuditEvent` containing the call ID and before/after states. An archived call is read-only.

Grant runtime `EXECUTE` only; deny runtime DML on the new table and newly call-owned applicant column through the existing table denials.

- [ ] **Step 5: Implement the validator and update every deployment inventory**

The validator must create a transaction-scoped synthetic call, prove group-filtered and public-safe lookup, reject invalid/adjacent/trailing-hyphen slugs, reject a duplicate slug, reject a trustee or invitation-enabling transition, prove legal lifecycle audit writes and archived-call write denial, verify call/applicant composite ownership, verify runtime DML denial, and roll back. Add both 040 files to every exact migration/validator list named above.

- [ ] **Step 6: Run focused and isolated database verification**

Run:

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_migrations.py tests\test_applicant_schema.py tests\test_sql_permissions.py tests\test_deployment_contract.py -q
powershell -NoProfile -File scripts\test-database.ps1
```

Expected: focused tests pass; the isolated database applies exactly 40 migrations, runs exactly 40 validators, and a second application is an idempotent no-op.

- [ ] **Step 7: Commit the schema foundation**

```powershell
git add database/migrations/040_multi_call_foundation.sql database/tests/040_validate_multi_call_foundation.sql tests/test_migrations.py tests/test_applicant_schema.py tests/test_sql_permissions.py infra/install-ehf.py infra/bootstrap-ehf-database.py infra/sql-principal.py infra/test-sql-login.sh scripts/test-database.ps1 tests/test_deployment_contract.py
git commit -m "feat: add multi-call database foundation"
```

### Task 2: Add the typed call catalog and resolver

**Delegation:** Primary agent only — authorization boundary.

**Files:**

- Create: `app/calls.py`
- Create: `tests/test_calls.py`
- Modify: `app/main.py`

**Interfaces:**

- Consumes: migration-040 procedures.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class CallContext:
    fellowship_call_id: UUID
    call_code: str
    public_slug: str
    display_name: str
    compact_title: str
    call_status: str
    applicant_review_status: str
    internal_selection_status: str
    invitations_enabled: bool
    analysis_profile_code: str
    application_deadline_utc: datetime
    applicant_review_deadline_utc: datetime | None

@dataclass(frozen=True, slots=True)
class PublicCallContext:
    public_slug: str
    call_code: str
    display_name: str
    application_deadline_utc: datetime
    applicant_review_deadline_utc: datetime | None
    applicant_review_status: str

@dataclass(frozen=True, slots=True)
class CallSummary:
    context: CallContext
    applicant_count: int
    latest_import_completed_at_utc: datetime | None
    activated_analysis_evidence_id: UUID | None
    active_shortlister_count: int
    roster_state: str

class CallCatalog(Protocol):
    def list_authorized(self, actor_group: str) -> tuple[CallSummary, ...]: ...
    def resolve(self, slug: str, actor_group: str, required_role: str) -> CallContext: ...
    def resolve_public(self, slug: str) -> PublicCallContext: ...
    def create(self, request: CreateCall, actor: str, actor_group: str) -> CallContext: ...
    def transition(self, slug: str, request: TransitionCall, actor: str,
                   actor_group: str) -> CallContext: ...
```

- [ ] **Step 1: Write failing type, mapping, and authorization tests**

Test exact summary/public/context row mapping, acceptance of a valid lowercase slug, rejection of uppercase or malformed slugs, rejection of unknown slugs, public lookup disclosure limits, rejection when the SQL repository returns no authorized row, administrator-first canonical group choice, lifecycle optimistic concurrency, and preservation of UTC-aware deadlines.

```python
def test_resolve_requires_an_authorized_exact_slug() -> None:
    catalog = InMemoryCallCatalog((CALL_2026, CALL_2027))
    assert catalog.resolve("ehf-2027", "EHF-Administrators", "READ") == CALL_2027
    with pytest.raises(LookupError):
        catalog.resolve("EHF-2027", "EHF-Administrators", "READ")
    with pytest.raises(PermissionError):
        catalog.resolve("ehf-2027", "unrelated", "READ")
```

- [ ] **Step 2: Run the focused test to verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_calls.py -q
```

Expected: import failure for `app.calls`.

- [ ] **Step 3: Implement immutable call types and repositories**

Implement `InMemoryCallCatalog` for tests and `SqlCallCatalog` using the migration-040 procedures. Validate slugs with one shared parser implementing `re.fullmatch(r"[a-z0-9](?:[a-z0-9]|-(?!-)){1,78}[a-z0-9]", slug)` before SQL. Map no row to `LookupError`; do not retry with `EHF-2026` or any application lookup. `resolve_public` uses only `GetPublicFellowshipCallBySlug` and returns `PublicCallContext`, never an authorized internal context.

Add `call_catalog` as an injected `create_app` dependency. Production construction uses `SqlCallCatalog` with the managed connection factory; test construction defaults to an empty fail-closed catalog.

- [ ] **Step 4: Run focused tests and existing construction contracts**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_calls.py tests\test_config.py tests\test_health.py tests\test_shell_contract.py -q
```

Expected: all pass and application construction remains fail-closed without a catalog.

- [ ] **Step 5: Commit the call catalog**

```powershell
git add app/calls.py app/main.py tests/test_calls.py
git commit -m "feat: resolve authorized fellowship calls"
```

### Task 3: Add the authorized call inventory and draft-call creation

**Delegation:** Primary agent owns routes and authorization. **Low-cost eligible:** after markup is fixed, a worker may own only `tests/browser/calls.spec.py` to add the stated responsive/keyboard cases.

**Files:**

- Create: `app/internal_calls.py`
- Create: `tests/test_call_admin.py`
- Create: `tests/browser/calls.spec.py`
- Modify: `app/main.py`
- Modify: `app/navigation.py`
- Modify: `public/assets/site.css`

**Interfaces:**

- Consumes: `CallCatalog.list_authorized`, `resolve`, `create`, and `transition`.
- Produces: `GET /internal/calls/`, `POST /api/internal/calls`, `GET /api/internal/calls/{call_slug}`, and administrator-only `POST /api/internal/calls/{call_slug}/lifecycle`.

- [ ] **Step 1: Write failing route tests**

Cover administrator and trustee inventory visibility, the complete readiness summary, unrelated-group neutral 404, trustee create/transition denial, invalid/duplicate slug 422 or 409 without mutation, successful DRAFT creation with invitations disabled, legal open/close/archive transitions, stale row-version rejection, invitation-enable rejection, illegal transition rollback, one audit event per success, and archived-workspace write denial.

```python
def test_trustee_can_list_but_cannot_create_call() -> None:
    client = TestClient(create_app(call_catalog=CATALOG, identity_resolver=trustee))
    assert client.get("/internal/calls/").status_code == 200
    assert client.post("/api/internal/calls", json=VALID_CALL).status_code == 404
    assert CATALOG.created == ()
```

- [ ] **Step 2: Run route tests to verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_call_admin.py -q
```

- [ ] **Step 3: Implement server-rendered inventory and create endpoint**

Render each authorized call as one complete semantic link to `/internal/calls/{slug}/`. Show title, code, deadline, applicant count, latest completed import, activated analysis evidence, roster count/state, call state, applicant-review state, selection state, and invitation-disabled status. Render the create form and lifecycle controls only for administrators. Validate exact create and lifecycle payloads, including the current row version; reject extra keys. Never expose an invitation-enable control.

Add the call inventory to the authorization-filtered navigation source. Preserve the F2 shell, authorization pills, 94% content width, 44-pixel controls, and no nested links inside call cards.

- [ ] **Step 4: Add browser scenarios**

Test whole-card keyboard activation, long titles, zero/many calls, readiness summaries, administrator create/lifecycle visibility, trustee form/control absence, archived read-only treatment, four skins, 1920x1080, 1366x768, 720x900, and 390x844 without horizontal page overflow.

- [ ] **Step 5: Run focused route/browser tests**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_call_admin.py tests\browser\calls.spec.py tests\test_shell_contract.py -q
```

- [ ] **Step 6: Commit the call inventory**

```powershell
git add app/internal_calls.py app/main.py app/navigation.py public/assets/site.css tests/test_call_admin.py tests/browser/calls.spec.py
git commit -m "feat: add fellowship call inventory"
```

### Task 4: Verify foundation compatibility and publish Plan 1

**Delegation:** Primary agent only.

**Files:**

- Modify: `CODEX_COORDINATION.md`

- [ ] **Step 1: Add explicit legacy compatibility tests**

Extend `tests/test_call_admin.py` to prove `/internal/` redirects to `/internal/calls/`, unknown slugs never redirect to 2026, and new calls are not reachable through any existing single-call endpoint before later plans deliberately wire them.

- [ ] **Step 2: Run the complete suite**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q
```

Expected: complete suite passes with exactly the current production behavior for `EHF-2026`.

- [ ] **Step 3: Run deployment dry-run contracts**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest infra\test-install-ehf.py tests\test_deployment_contract.py -q
powershell -NoProfile -File scripts\deploy-ehf.ps1 -WhatIf
```

- [ ] **Step 4: Record and commit the foundation handoff**

Append counts, migration number, test results, and commit IDs only; include no applicant data.

```powershell
git add CODEX_COORDINATION.md
git commit -m "docs: record multi-call foundation"
git push origin main
git fetch origin main
git diff --exit-code origin/main
```
