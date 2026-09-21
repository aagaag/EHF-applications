# Applicant Review Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract and securely serve proposal, curriculum, and publication-list PDFs from each applicant package, add three new-tab modal buttons, and add a sortable citations column to the modal publication table.

**Architecture:** Reviewed page-range manifests create sanitized derivative PDFs in the existing encrypted document store and bind them to dedicated internal-review slots with append-only provenance. A category-specific authorised endpoint serves only those derivatives. The modal remains a track-record view with three external PDF links, while its publication list uses existing citation counts and client-side numeric sorting.

**Tech Stack:** Python 3.13, FastAPI, SQL Server T-SQL, pypdf, vanilla JavaScript/CSS, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-21-applicant-review-artifacts-design.md`

## Global Constraints

- Work directly on `main`; do not create or switch branches or worktrees.
- Follow RED-GREEN TDD for every implementation change.
- Use `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe` for Python.
- Do not commit applicant documents, extraction manifests containing applicant names, import output, credentials, or test artifacts.
- Preserve source files and recommendation confidentiality.
- Keep production applicant invitations disabled.

## Review Focus

- A combined package may contribute disjoint page ranges; the derivative must preserve declared segment order.
- Missing or stale source hashes must stop import before any artifact is activated.
- A category route must never fall back to a whole package or recommendation document.
- Missing citation counts must remain last for both ascending and descending sorts.
- New-tab links must be inert until an application id is selected and must prevent opener access.

---

### Task 1: Page-range PDF extraction

**Files:**
- Create: `app/documents/extract.py`
- Modify: `app/documents/package.py`
- Test: `tests/test_pdf_extract.py`

**Interfaces:**
- Consumes: ordered `(pdf_bytes, first_page, last_page)` segments using one-based inclusive pages.
- Produces: `build_pdf_extract(segments: tuple[PdfSegment, ...], *, title: str, subject: str) -> bytes`.

- [ ] **Step 1: Write the failing tests**

Add tests proving two disjoint ranges are emitted in declared order, bounds are rejected, empty/encrypted inputs fail closed, unsafe keys are removed, and neutral metadata replaces source metadata.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_pdf_extract.py -q`
Expected: FAIL because `app.documents.extract` does not exist.

- [ ] **Step 3: Implement the minimum extractor**

Define:

```python
@dataclass(frozen=True, slots=True)
class PdfSegment:
    payload: bytes
    first_page: int
    last_page: int

def build_pdf_extract(
    segments: tuple[PdfSegment, ...], *, title: str, subject: str
) -> bytes:
    ...
```

Reuse the existing unsafe-key removal logic from `package.py`; validate one-based inclusive ranges before adding pages.

- [ ] **Step 4: Run focused and full tests**

Run: `python -m pytest tests/test_pdf_extract.py tests/test_applicant_package.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit subject: `feat: extract reviewed applicant PDF sections`

### Task 2: Artifact schema, repository, and secure route

**Files:**
- Create: `database/migrations/032_internal_review_artifacts.sql`
- Create: `database/tests/032_validate_internal_review_artifacts.sql`
- Modify: `app/applicant/documents.py`
- Modify: `app/applicant/sql_pilot.py`
- Modify: `app/routes/internal_approval.py`
- Modify: `tests/test_internal_document_access.py`
- Modify: `tests/test_pilot_sql_repositories.py`
- Modify: `tests/test_sql_permissions.py`
- Modify: `tests/test_applicant_schema.py`

**Interfaces:**
- Consumes: existing document-store records and `internal_download` authorization/audit behaviour.
- Produces: `internal_review_artifacts(application_id, actor, actor_group)` and `internal_review_artifact(application_id, category, actor, actor_group)` plus `/review-artifacts/{category}/view`.

- [ ] **Step 1: Write failing schema and service tests**

Assert an append-only provenance table, category/source/page constraints, runtime direct-table denial, execute grants, strict category allowlisting, 404 for missing artifacts, and requested/succeeded/failed audit outcomes.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_internal_document_access.py tests/test_pilot_sql_repositories.py tests/test_sql_permissions.py tests/test_applicant_schema.py -q`
Expected: FAIL because migration 032, repository methods, and route are missing.

- [ ] **Step 3: Implement schema and access path**

Create `InternalReviewArtifactProvenance`, `ListInternalReviewArtifacts`, and `GetInternalReviewArtifact`; deny runtime table access and grant only procedure execution. Return category availability without document text. Serve inline PDFs only through the existing reviewer-group authorization and audit pipeline.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_internal_document_access.py tests/test_pilot_sql_repositories.py tests/test_sql_permissions.py tests/test_applicant_schema.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit subject: `feat: serve secure applicant review artifacts`

### Task 3: Curated legacy extraction and encrypted ingestion

**Files:**
- Create: `app/importer/review_artifacts.py`
- Create: `app/importer/run_review_artifacts.py`
- Create: `tests/test_review_artifact_importer.py`
- Create: `scripts/import-review-artifacts-2026.ps1`
- Create: `scripts/verify-review-artifacts-2026.ps1`

**Interfaces:**
- Consumes: a private JSON manifest containing application locator hashes, source occurrence hashes, categories, and page ranges; the immutable Call 2026 source folder; Task 1 extractor; Task 2 provenance procedures.
- Produces: encrypted dedicated review-artifact document versions and a bounded aggregate verification report.

- [ ] **Step 1: Write failing importer tests**

Cover manifest schema, path containment, source SHA-256 verification, recommendation-signal rejection, idempotency, closed/non-visible slots, encrypted storage, and rollback on any failed artifact.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_review_artifact_importer.py -q`
Expected: FAIL because the importer does not exist.

- [ ] **Step 3: Implement planning and apply modes**

Require explicit `--manifest`, `--source-root`, and `--sql-admin-credential-file` arguments. Planning validates every source and renders no database writes. Apply performs one transaction per complete manifest only after all PDFs have been generated, validated, scanned, and encrypted.

- [ ] **Step 4: Build and privately review the production manifest**

Use the Call 2026 folder and database source-occurrence hashes. Record only opaque application identifiers and hashes. Verify every first/last page visually and reject any range containing recommendation material. Keep the manifest outside Git.

- [ ] **Step 5: Run focused tests and dry-run verification**

Run: `python -m pytest tests/test_review_artifact_importer.py tests/test_pdf_extract.py -q`
Expected: PASS, followed by a plan result whose aggregate counts match the reviewed manifest.

- [ ] **Step 6: Commit**

Commit subject: `feat: import curated applicant review PDFs`

### Task 4: Modal PDF buttons and citation sorting

**Files:**
- Modify: `app/internal_preview.py`
- Modify: `app/applicant_detail.py`
- Modify: `public/assets/shell.js`
- Modify: `public/assets/site.css`
- Modify: `tests/test_applicant_detail.py`
- Modify: `tests/browser/shell.spec.py`

**Interfaces:**
- Consumes: category availability and routes from Task 2; `Publication.citation_count` already populated by the detail repository.
- Produces: three safe new-tab artifact links and a semantic sortable publication table.

- [ ] **Step 1: Write failing renderer and browser tests**

Assert that the modal has no tablist/embed, contains Application/Curriculum/Publication list links with `_blank` and `noopener noreferrer`, and binds the selected application id. Assert Title, Journal/year, and Citations headers; numeric citation cells and sort values; ascending/descending controls; stable ties; and missing values last.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_applicant_detail.py tests/browser/shell.spec.py -q`
Expected: FAIL on the old tabs/embed and absent citations column/sort controls.

- [ ] **Step 3: Implement minimal markup, sorting, and styles**

Render citation counts as text plus `data-publication-citations`; render missing values as an em dash with a missing marker. Bind the three category URLs when the modal opens. Implement stable numeric sorting using original row index as the tie breaker and append missing rows after observed rows for both directions.

- [ ] **Step 4: Run focused browser and unit tests**

Run: `python -m pytest tests/test_applicant_detail.py tests/browser/shell.spec.py -q`
Expected: PASS with zero accessibility violations.

- [ ] **Step 5: Commit**

Commit subject: `feat: add applicant PDF actions and citation sorting`

### Task 5: Full verification and production deployment

**Files:**
- Modify only if a failing verification requires a RED-GREEN correction to files owned above.

**Interfaces:**
- Consumes: Tasks 1-4 and the private reviewed manifest.
- Produces: migrated production, imported artifacts, active release, aggregate post-deployment evidence, and a preserved rollback release.

- [ ] **Step 1: Run the full local suite**

Run: `python -m pytest -q`
Expected: PASS with no warnings attributable to this change.

- [ ] **Step 2: Run production preflight and database validation**

Run the repository verification scripts, migration tests through 032, and the review-artifact importer in plan mode. Expected: all checks PASS and source hashes unchanged.

- [ ] **Step 3: Deploy atomically**

Push `main`, deploy the exact pushed commit with `scripts/deploy-ehf.ps1`, apply migration 032, import the private reviewed artifacts, then switch the active release only after health checks pass.

- [ ] **Step 4: Verify production behaviour**

Confirm the active commit, health endpoint, authorised artifact endpoints, aggregate three-category coverage, modal links, citation sorting in both directions, missing-value placement, and no recommendation exposure. Expected: all checks PASS without printing applicant names or document text.

- [ ] **Step 5: Record rollback evidence**

Record the prior release identifier and confirm it remains intact. Do not enable applicant invitations.
