# EHF Multi-Call Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Authentication, authorization, SQL, and object-access tasks remain with the primary agent.

**Goal:** Bind applicant identities, invitations, sessions, access requests, internal review operations, and document authorization to an explicit fellowship call while preserving neutral failure behavior and `EHF-2026` compatibility.

**Architecture:** Migration 041 adds call keys and composite constraints to applicant access/session/identity records and adds versioned call-aware procedures beside the preserved EHF-2026 SQL surface. Python session types carry the immutable call ID; canonical applicant and internal-review URLs resolve public or authorized call context first and compare it with every token, session, application, confirmation, and document relationship.

**Tech Stack:** SQL Server/T-SQL, Python dataclasses and protocols, FastAPI, secure cookies, Entra object IDs, opaque invitation tokens, pytest, and browser scenarios.

**Spec:** `docs/superpowers/specs/2026-09-21-ehf-multi-call-architecture-design.md`

## Global Constraints

- Plan 1 is committed, pushed, and green before this plan begins.
- Follow all global constraints in the implementation index.
- This plan owns migration and validator 041.
- Never reveal whether a mismatched call, token, session, application, confirmation, document, or Entra identity exists.
- Retain `SameSite=Lax` only for the Entra session cookie; retain `SameSite=Strict` for CSRF and preserve all same-origin write checks.
- Legacy applicant/API paths are explicit `EHF-2026` wrappers only; no new call is reachable through them.

## Review Focus

- A token issued for call A on call B's URL must expose no identity and create no challenge/session.
- A valid session for call A must fail on every call B page and API.
- One Entra object mapped once in A and once in B must resolve only with the supplied call ID.
- An access request for call A must not provision an application from B.
- Cross-call confirmation/document IDs must be indistinguishable from nonexistent IDs.

---

### Task 1: Add migration 041 call-bound applicant access and sessions

**Delegation:** Primary agent only.

**Files:**

- Create: `database/migrations/041_call_scoped_applicant_access.sql`
- Create: `database/tests/041_validate_call_scoped_applicant_access.sql`
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

- Adds `FellowshipCallId` to `ApplicantAccessRequest`, `ApplicantInvitation`, `ApplicantSession`, and `ApplicantEntraIdentity`.
- Replaces global Entra uniqueness with `UNIQUE(FellowshipCallId, EntraObjectId)` while retaining one mapping per application.
- Adds versioned call-aware applicant access/auth procedures while preserving every prior-release procedure name and signature as an explicit `EHF-2026` compatibility surface.

- [ ] **Step 1: Write failing migration and schema tests**

```python
def test_call_scoped_access_migration_removes_global_entra_uniqueness() -> None:
    sql = (MIGRATION_DIRECTORY / "041_call_scoped_applicant_access.sql").read_text(
        encoding="utf-8"
    )
    assert "DROP CONSTRAINT UQ_ApplicantEntraIdentity_Object" in sql
    assert "FellowshipCallId, EntraObjectId" in sql
    for procedure in (
        "GetApplicationForEntraApplicantByCall",
        "RequestApplicantAccessByCall",
        "ProvisionApplicantAccessRequestByCall",
        "CreateEntraApplicantSessionByCall",
        "GetApplicantSessionByCall",
    ):
        assert f"CREATE OR ALTER PROCEDURE dbo.{procedure}" in sql
```

Update exact inventories to 41.

- [ ] **Step 2: Run focused tests to verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_migrations.py tests\test_applicant_schema.py tests\test_sql_permissions.py tests\test_deployment_contract.py -q
```

- [ ] **Step 3: Implement additive columns, backfill, and composite constraints**

Add each call column nullable, backfill every existing row to the call of its related application or to the unique `EHF-2026` call for unprovisioned historical access requests, validate no orphan/mismatch, then make it non-null where the record is call-owned.

Add supporting unique keys on `Application(FellowshipCallId, ApplicationId)` and on call-owned parents before adding composite foreign keys. Drop only the global `ApplicantEntraIdentity.EntraObjectId` uniqueness and replace it with call-scoped uniqueness. Do not drop token/session hash uniqueness.

- [ ] **Step 4: Add call-aware access, invitation, and session procedures**

Use these exact call-aware signatures:

```sql
GetApplicationForEntraApplicantByCall @FellowshipCallId, @EntraObjectId
RequestApplicantAccessByCall @FellowshipCallId, @RequestedEmail, @RequestedDisplayName
ListPendingApplicantAccessRequestsByCall @FellowshipCallId
ReviewApplicantAccessRequestByCall @FellowshipCallId, @ApplicantAccessRequestId, ...
ProvisionApplicantAccessRequestByCall @FellowshipCallId, @ApplicantAccessRequestId, @ApplicationId, @EntraObjectId, ...
GetActiveApplicantInvitationByCall @FellowshipCallId, @InvitationTokenSha256, ...
CreateApplicantVerificationChallengeByCall @FellowshipCallId, @ApplicantInvitationId, ...
VerifyApplicantInvitationCodeByCall @FellowshipCallId, @ApplicantInvitationId, ...
CreateApplicantInvitationSessionByCall @FellowshipCallId, @ApplicantInvitationId, ...
CreateEntraApplicantSessionByCall @FellowshipCallId, @EntraObjectId, ...
GetApplicantSessionByCall @FellowshipCallId, @SessionTokenSha256, @IdleExpiresAtUtc
```

Every application/identity/request join must include call equality. Invitation lookup and verification procedures return the invitation/application call ID and accept the expected call ID before recording a challenge or session. A mismatch throws the same unavailable error as a missing record. Do not enable delivery or invitation creation in production.

Leave the previous call-less procedure signatures intact for the previous application release. They remain fixed `EHF-2026` compatibility wrappers or unchanged legacy definitions, and a contract test invokes those signatures after migration 041. New code calls only the `ByCall` procedures.

- [ ] **Step 5: Implement validator 041 and update inventories**

Within a rolled-back validator transaction, create two calls and two applications for the same synthetic Entra object. Prove each explicit call resolves its own application; no new call-aware lookup omits call ID; cross-call provisioning and invitation verification fail; a call-A session lookup under B returns no row; legacy procedure signatures still execute for EHF-2026; direct runtime DML remains denied.

- [ ] **Step 6: Run focused and isolated SQL verification**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_migrations.py tests\test_applicant_schema.py tests\test_sql_permissions.py tests\test_deployment_contract.py -q
powershell -NoProfile -File scripts\test-database.ps1
```

- [ ] **Step 7: Commit migration 041**

```powershell
git add database/migrations/041_call_scoped_applicant_access.sql database/tests/041_validate_call_scoped_applicant_access.sql tests/test_migrations.py tests/test_applicant_schema.py tests/test_sql_permissions.py infra/install-ehf.py infra/bootstrap-ehf-database.py infra/sql-principal.py infra/test-sql-login.sh scripts/test-database.ps1 tests/test_deployment_contract.py
git commit -m "security: scope applicant access by call"
```

### Task 2: Carry call identity through applicant auth repositories

**Delegation:** Primary agent only.

**Files:**

- Modify: `app/auth/applicant.py`
- Modify: `app/applicant/access.py`
- Modify: `app/applicant/sql_pilot.py`
- Modify: `tests/test_invitation_tokens.py`
- Modify: `tests/test_entra_applicant_identity.py`
- Modify: `tests/test_applicant_access_requests.py`
- Modify: `tests/test_pilot_sql_repositories.py`

**Interfaces:**

- Consumes: migration-041 procedures.
- Changes session/auth signatures to require `fellowship_call_id: UUID`.

```python
@dataclass(frozen=True, slots=True)
class ApplicantSessionContext:
    fellowship_call_id: UUID
    application_id: UUID
    csrf_token_hash: bytes
    idle_expires_at: datetime
    absolute_expires_at: datetime
    invitation_id: UUID | None
    entra_object_id: UUID | None
    synthetic_actor_identity: str | None = None

class ApplicantAuthService:
    def authenticate(self, fellowship_call_id: UUID, session_token: str) -> ApplicantSessionContext | None: ...
    def establish_entra(self, fellowship_call_id: UUID, entra_object_id: UUID) -> NewApplicantSession | None: ...
```

- [ ] **Step 1: Write failing two-call auth and access tests**

```python
def test_same_entra_identity_resolves_independently_per_call() -> None:
    repository = InMemoryApplicantAuthRepository()
    repository.map_entra(CALL_A, ENTRA_ID, APPLICATION_A)
    repository.map_entra(CALL_B, ENTRA_ID, APPLICATION_B)
    assert service.establish_entra(CALL_A, ENTRA_ID).application_id == APPLICATION_A
    assert service.establish_entra(CALL_B, ENTRA_ID).application_id == APPLICATION_B
```

Also require invitation A to be unavailable under B, session A to fail under B, and access request A to reject application B.

- [ ] **Step 2: Run focused tests to verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_invitation_tokens.py tests\test_entra_applicant_identity.py tests\test_applicant_access_requests.py tests\test_pilot_sql_repositories.py -q
```

- [ ] **Step 3: Implement call-aware in-memory and SQL repositories**

Key in-memory Entra mappings by `(fellowship_call_id, entra_object_id)` and session mappings by token plus stored call. Bind invitation records, pre-auth contexts, challenges, and delivery attempts to the same call. Add the SQL invitation repository boundary against the migration-041 call-aware procedures, while keeping delivery disabled by configuration. In `SqlEntraApplicantAuthRepository`, pass call ID into `application_for_entra`, `put_session`, and `session`; in `SqlApplicantAccessRepository`, pass call ID into `request`, `actionable`, `review`, and `provision`.

Never offer an overload that omits call ID. Convert no-row and call mismatch to the existing neutral `None`/`LookupError` contract; do not reveal a conflicting call.

- [ ] **Step 4: Run focused tests**

Run the same command as Step 2. Expected: all pass.

- [ ] **Step 5: Commit repository call binding**

```powershell
git add app/auth/applicant.py app/applicant/access.py app/applicant/sql_pilot.py tests/test_invitation_tokens.py tests/test_entra_applicant_identity.py tests/test_applicant_access_requests.py tests/test_pilot_sql_repositories.py
git commit -m "security: bind applicant sessions to calls"
```

### Task 3: Canonicalize applicant pages and APIs

**Delegation:** Primary agent owns route behavior. **Low-cost eligible:** after the canonical base-path contract is merged, a worker may update one applicant HTML file and its one focused browser test at a time.

**Files:**

- Modify: `app/routes/applicant_auth.py`
- Modify: `app/routes/applicant_access.py`
- Modify: `app/routes/applicant_entra.py`
- Modify: `app/routes/applicant_data.py`
- Modify: `app/routes/applicant_review.py`
- Modify: `app/routes/applicant_documents.py`
- Modify: `app/routes/applicant_finalize.py`
- Modify: `app/main.py`
- Modify: `public/applicant/verify.html`
- Modify: `public/applicant/request-access.html`
- Modify: `public/applicant/index.html`
- Modify: `public/applicant/review.html`
- Modify: `public/applicant/documents.html`
- Modify: `public/applicant/final-review.html`
- Modify: `public/assets/applicant-auth.js`
- Modify: `public/assets/applicant-access.js`
- Modify: `public/assets/applicant-review.js`
- Modify: `public/assets/applicant-documents.js`
- Modify: `public/assets/applicant-finalize.js`
- Modify: `tests/test_applicant_response_contract.py`
- Modify: `tests/test_applicant_access_requests.py`
- Modify: `tests/test_applicant_review_routes.py`
- Modify: `tests/test_applicant_document_routes.py`
- Modify: `tests/test_applicant_finalize_routes.py`
- Modify: `tests/browser/applicant_auth.spec.py`

**Interfaces:**

- Consumes: `CallCatalog.resolve(slug, actor_group, role)` for internal users and `CallCatalog.resolve_public(slug)` for public applicant routes.
- Produces canonical `/calls/{call_slug}/applicant/...`, `/api/calls/{call_slug}/applicant/...`, `/calls/{call_slug}/request-access`, `/api/calls/{call_slug}/applicant-access-requests`, and `/calls/{call_slug}/a/{invitation_token}` routes.

- [ ] **Step 1: Write failing URL/session/token mismatch tests**

Assert canonical call A success, call B neutral denial with call-A token/session/access request, unknown slug denial, dynamic title/deadline response, call-bound public access-request creation, and exact EHF-2026 legacy redirect. Assert response bodies and timing-safe status classes do not identify the real call.

- [ ] **Step 2: Run focused route tests to verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_applicant_response_contract.py tests\test_applicant_access_requests.py tests\test_applicant_review_routes.py tests\test_applicant_document_routes.py tests\test_applicant_finalize_routes.py tests\browser\applicant_auth.spec.py -q
```

- [ ] **Step 3: Add call slug to each route registrar and handler**

Register canonical decorators with `{call_slug}` and resolve the call before reading cookies, tokens, application IDs, or request bodies. Pass `call.fellowship_call_id` to every auth/service method. A mismatch returns the same neutral response used for missing authorization.

The session probe returns public metadata needed by shared pages:

```json
{
  "authenticated": true,
  "call": {
    "slug": "ehf-2026",
    "code": "EHF-2026",
    "title": "Ernst Hadorn Transitional Fellowships 2026",
    "reviewDeadlineUtc": null
  }
}
```

No response includes another call's identifiers.

- [ ] **Step 4: Rebase applicant HTML and JavaScript links**

Derive the API/page base from the canonical pathname or returned session metadata; do not hardcode `EHF-2026`. The request-access page posts only to its path's resolved call. Preserve Turnstile validation, all existing CSRF headers, no-store behavior, object-ID validation, upload limits, keyboard behavior, and finalization locks.

Legacy `/a/{token}` may resolve the token only far enough to issue a neutral 303 to its exact `EHF-2026` canonical URL; all other legacy applicant pages redirect explicitly to `/calls/ehf-2026/applicant/...`. Legacy APIs invoke only the `EHF-2026` wrapper and never accept a call override.

- [ ] **Step 5: Run focused route/browser tests**

Run Step 2's command plus:

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_applicant_object_authorization.py tests\test_security_headers.py -q
```

- [ ] **Step 6: Commit canonical applicant routes**

```powershell
git add app/routes/applicant_access.py app/routes/applicant_auth.py app/routes/applicant_data.py app/routes/applicant_documents.py app/routes/applicant_entra.py app/routes/applicant_finalize.py app/routes/applicant_review.py app/main.py public/applicant/documents.html public/applicant/final-review.html public/applicant/index.html public/applicant/request-access.html public/applicant/review.html public/applicant/verify.html public/assets/applicant-access.js public/assets/applicant-auth.js public/assets/applicant-review.js public/assets/applicant-documents.js public/assets/applicant-finalize.js tests/test_applicant_access_requests.py tests/test_applicant_response_contract.py tests/test_applicant_review_routes.py tests/test_applicant_document_routes.py tests/test_applicant_finalize_routes.py tests/test_applicant_object_authorization.py tests/browser/applicant_auth.spec.py
git commit -m "feat: add call-scoped applicant routes"
```

### Task 4: Scope internal review and document operations

**Delegation:** Primary agent only.

**Files:**

- Modify: `app/routes/applicant_access.py`
- Modify: `app/routes/internal_approval.py`
- Modify: `app/applicant/approval.py`
- Modify: `app/documents/store.py`
- Modify: `tests/test_internal_applicant_preview.py`
- Modify: `tests/test_applicant_approval.py`
- Modify: `tests/test_internal_document_access.py`
- Modify: `tests/test_applicant_object_authorization.py`
- Modify: `tests/test_applicant_access_requests.py`

**Interfaces:**

- Consumes: resolved internal `CallContext` and call-aware services from Tasks 1-3.
- Produces canonical `/api/internal/calls/{call_slug}/applicant-access-requests` and `/api/internal/calls/{call_slug}/applicants/...` operations.

- [ ] **Step 1: Write failing cross-call object tests**

For each access request, application preview, confirmation, document version, package, review artifact, accept/reject action, and correction return, present a valid call-A ID under call B and assert neutral unavailability, no object read, no store open/decrypt, and no audit mutation.

- [ ] **Step 2: Run focused tests to verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\test_internal_applicant_preview.py tests\test_applicant_approval.py tests\test_internal_document_access.py tests\test_applicant_object_authorization.py tests\test_applicant_access_requests.py -q
```

- [ ] **Step 3: Require call context in every internal service/repository call**

Update service protocols so call ID is the first argument for call-owned operations. SQL procedures invoked by these services use a call-aware `ByCall` definition from migration 041; do not change a prior-release procedure signature. Document authorization verifies call -> application -> slot/document -> version before opening the opaque object key.

- [ ] **Step 4: Run focused tests and raw authorization probes**

Run Step 2's command plus the existing edge/object authorization probes in `tests/test_internal_document_access.py` and `tests/test_applicant_object_authorization.py`. Expected: same-call behavior passes; all cross-call probes are neutral and side-effect free.

- [ ] **Step 5: Commit internal object scoping**

```powershell
git add app/routes/applicant_access.py app/routes/internal_approval.py app/applicant/approval.py app/documents/store.py tests/test_internal_applicant_preview.py tests/test_applicant_approval.py tests/test_internal_document_access.py tests/test_applicant_object_authorization.py tests/test_applicant_access_requests.py
git commit -m "security: enforce call ownership on internal objects"
```

### Task 5: Verify and publish Plan 2

**Delegation:** Primary agent only.

**Files:**

- Modify: `CODEX_COORDINATION.md`

- [ ] **Step 1: Run the complete Python and browser suites**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests\browser\*.spec.py -q
```

- [ ] **Step 2: Run the isolated database and deployment contract checks**

```powershell
powershell -NoProfile -File scripts\test-database.ps1
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest infra\test-install-ehf.py tests\test_deployment_contract.py -q
```

- [ ] **Step 3: Record counts and publish**

```powershell
git add CODEX_COORDINATION.md
git commit -m "docs: record call-scoped access verification"
git push origin main
git fetch origin main
git diff --exit-code origin/main
```
