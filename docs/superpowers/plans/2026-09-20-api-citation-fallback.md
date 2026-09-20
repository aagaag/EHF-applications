# API-only Citation Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish fair, non-missing EHF 2026 citation totals from one complete Semantic Scholar cutoff snapshot when OpenAlex cannot be collected.

**Architecture:** Extend the official citation collector with a Semantic Scholar source mode and preserve strict DOI/title/applicant matching. Import append-only observations as today, then activate one complete source-specific cutoff run through a new audited database record. The overview and detail procedures read only that active run and never fall back to Google Scholar.

**Tech Stack:** Python 3.12, httpx, CSV snapshots, SQL Server migrations/procedures, FastAPI, pytest and Playwright.

**Spec:** `docs/superpowers/specs/2026-09-20-api-citation-fallback-design.md`

## Global Constraints

- Google Scholar must not be queried, scraped, browser-automated, manually reviewed, or used as a metric source.
- Use only official APIs and the existing strict DOI/title/year/applicant evidence rules.
- One active cutoff source applies to the complete EHF-2026 verified `RESOLVED` + `PUBLISHED` work set.
- Activation requires an `OBSERVED` nonnegative count for every eligible work from one completed import run.
- Failed, rate-limited, malformed, mixed-source, and incomplete runs leave the active metric untouched and never display zero.
- Snapshots, manifests, credentials, and collected evidence remain outside Git; observations and run records are append-only.
- Run TDD with `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`; keep dependencies pinned; deploy only clean `main`.

## Review Focus

- Semantic Scholar 429 after partial pages: abort and do not create an importable snapshot.
- DOI match with applicant mismatch: reject it unless the DOI is exact.
- One `NOT_FOUND` eligible work: retain audit evidence but do not activate the metric.
- Existing OpenAlex data: never contributes to a Semantic Scholar active total.
- Semantic Scholar total-only evidence: never renders a fabricated annual citation chart.

---

### Task 1: Source-aware official citation collection

**Files:**
- Modify: `app/importer/open_citation_collector.py`
- Modify: `app/importer/collect_open_citations.py`
- Modify: `scripts/collect-open-citations-2026.ps1`
- Test: `tests/test_open_citation_collector.py`

**Interfaces:**
- Consumes: `PublicationManifest`, `OfficialCitationApiClient`, `CitationApiMatch`.
- Produces: `collect_semantic_scholar_rows(manifest, client, *, reviewer, progress) -> tuple[dict[str, str], ...]` and CLI `--source {OPENALEX,SEMANTIC_SCHOLAR}`.

- [ ] **Step 1: Write failing collector tests**

```python
def test_semantic_scholar_collection_emits_one_observed_row_per_doi_work(monkeypatch):
    rows = collect_semantic_scholar_rows(manifest, SemanticClient())
    assert rows[0]["source_code"] == "SEMANTIC_SCHOLAR"
    assert rows[0]["citation_status"] == "OBSERVED"
    assert rows[0]["citation_count"] == "17"

def test_semantic_scholar_rate_limit_aborts_without_rows(monkeypatch):
    with pytest.raises(OpenCitationCollectionError, match="api.semanticscholar.org.*429"):
        collect_semantic_scholar_rows(manifest, RateLimitedClient())
```

Add fixtures for a title/year/family-name match and a rejected author mismatch. Add a CLI test proving `--source SEMANTIC_SCHOLAR` writes no OpenAlex rows.

- [ ] **Step 2: Verify RED**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_open_citation_collector.py -q`

Expected: FAIL because the Semantic Scholar collection/source dispatch is absent.

- [ ] **Step 3: Implement the bounded collector**

```python
def collect_semantic_scholar_rows(
    manifest: PublicationManifest,
    client: OfficialCitationApiClient,
    *, reviewer: str = "EHF Semantic Scholar cutoff collector 2026.7",
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[dict[str, str], ...]:
    # Use official DOI batch requests; use paced title search only when no DOI exists.
    # Emit _row(work, "SEMANTIC_SCHOLAR", ...) exactly once for every work.
```

Send an optional `SEMANTIC_SCHOLAR_API_KEY` only to Semantic Scholar requests. Raise `OpenCitationCollectionError` on network/API/429 failure and write no partial output. Add `-Source` to the PowerShell wrapper and remote CLI invocation. Add no Google Scholar request, queue, browser call, or dependency.

- [ ] **Step 4: Verify GREEN**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_open_citation_collector.py -q`

Expected: PASS, including strict match and rate-limit-abort cases.

- [ ] **Step 5: Commit**

```bash
git add app/importer/open_citation_collector.py app/importer/collect_open_citations.py scripts/collect-open-citations-2026.ps1 tests/test_open_citation_collector.py
git commit -m "feat: collect Semantic Scholar cutoff citations"
```

### Task 2: Homogeneous snapshot import and activation request

**Files:**
- Modify: `app/importer/open_citations.py`
- Modify: `app/importer/run_open_citations.py`
- Test: `tests/test_open_citation_importer.py`

**Interfaces:**
- Consumes: Task 1’s one-source snapshot rows.
- Produces: `OpenCitationImportResult(source_code: str, eligible_count: int, observed_count: int, not_found_count: int, ...)` and `SqlOpenCitationRepository.apply` that activates only complete source runs.

- [ ] **Step 1: Write failing importer tests**

```python
def test_snapshot_rejects_mixed_openalex_and_semantic_scholar_rows():
    with pytest.raises(OpenCitationImportError, match="exactly one source"):
        load_open_citation_reviews(mixed_source_snapshot, manifest)

def test_incomplete_semantic_snapshot_is_audited_but_not_activated():
    result = run_open_citation_import(manifest_bytes, one_not_found_snapshot, mode=ImportMode.APPLY, repository_factory=factory)
    assert result.not_found_count == 1
    assert "ActivateCitationMetricCutoffRun" not in factory.connection.statements
```

Add a complete-Semantic fixture asserting all rows use one `ImportRunId` and activate after completion.

- [ ] **Step 2: Verify RED**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_open_citation_importer.py -q`

Expected: FAIL because mixed source snapshots are accepted and there is no activation request.

- [ ] **Step 3: Implement strict import state**

Require exactly one `source_code` across all manifest works. Change the importer version to `2026.7-source-cutoff`. Complete the import first; only then execute `dbo.ActivateCitationMetricCutoffRun @ImportRunId=?` when `observed_count == eligible_count` and `not_found_count == 0`. Preserve incomplete observations without activation.

- [ ] **Step 4: Verify GREEN**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_open_citation_importer.py -q`

Expected: PASS, including incomplete and mixed snapshot guards.

- [ ] **Step 5: Commit**

```bash
git add app/importer/open_citations.py app/importer/run_open_citations.py tests/test_open_citation_importer.py
git commit -m "feat: activate complete citation cutoff runs"
```

### Task 3: Audited database cutoff projection

**Files:**
- Create: `database/migrations/031_citation_metric_cutoff_runs.sql`
- Create: `database/tests/031_validate_citation_metric_cutoff_runs.sql`
- Modify: `database/tests/001_validate_database_contract.sql`
- Modify: `scripts/test-database.ps1`, `infra/install-ehf.py`, `infra/bootstrap-ehf-database.py`, `infra/sql-principal.py`, `infra/test-sql-login.sh`
- Modify: `tests/test_migrations.py`, `tests/test_applicant_schema.py`

**Interfaces:**
- Consumes: a completed `dbo.ImportRun` and source-specific `dbo.PublicationCitationObservation` rows.
- Produces: `dbo.ActivateCitationMetricCutoffRun @ImportRunId` and `dbo.GetInternalApplicationMetrics` driven only by one active cutoff run.

- [ ] **Step 1: Write failing migration tests**

```python
def test_current_migration_tip_includes_citation_metric_cutoff_runs():
    assert migrations[-1].path.name == "031_citation_metric_cutoff_runs.sql"

def test_cutoff_validator_requires_complete_observed_source_run():
    assert "COUNT(CASE WHEN observation.CitationStatus=''OBSERVED''" in validator
    assert "THROW" in validator
```

Add SQL fixtures proving incomplete/mixed import runs cannot activate, one active record exists for EHF-2026, and the metrics procedure has no legacy-profile or Google Scholar fallback.

- [ ] **Step 2: Verify RED**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_migrations.py tests\test_applicant_schema.py -q`

Expected: FAIL because migration 031 and its validator do not exist.

- [ ] **Step 3: Implement migration 031**

Create append-only `dbo.CitationMetricCutoffRun` with source, completed import run, cutoff timestamp, eligible/observed/not-found counts, activation timestamp, and one-active-run-per-call enforcement. `dbo.ActivateCitationMetricCutoffRun` verifies one source and one `OBSERVED` count for every eligible verified published publication from its completed import run. Alter `dbo.GetInternalApplicationMetrics` to select that run’s `ImportRunId` and `SourceCode`; return `NULL` if none is active. Update exact release inventories to 31.

- [ ] **Step 4: Verify GREEN**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_migrations.py tests\test_applicant_schema.py tests\test_database_bootstrap.py -q`

Expected: PASS, including the 31-migration contract.

- [ ] **Step 5: Commit**

```bash
git add database/migrations/031_citation_metric_cutoff_runs.sql database/tests/031_validate_citation_metric_cutoff_runs.sql database/tests/001_validate_database_contract.sql scripts/test-database.ps1 infra/install-ehf.py infra/bootstrap-ehf-database.py infra/sql-principal.py infra/test-sql-login.sh tests/test_migrations.py tests/test_applicant_schema.py
git commit -m "feat: project an active citation cutoff run"
```

### Task 4: Honest source-labelled presentation

**Files:**
- Modify: `app/metrics.py`, `app/internal_preview.py`, `app/applicant_detail.py`
- Test: `tests/test_citation_plots.py`, `tests/test_populated_preview.py`, `tests/test_applicant_detail.py`, `tests/test_production_identity_metrics.py`, `tests/browser/shell.spec.py`

**Interfaces:**
- Consumes: active source label and source evidence from Task 3 procedures.
- Produces: overview text such as `656 (Semantic Scholar)` and an annual-history notice instead of synthetic bars for total-only sources.

- [ ] **Step 1: Write failing presentation tests**

```python
def test_overview_labels_active_semantic_scholar_total():
    assert "656 (Semantic Scholar)" in render_internal_preview(principal, simulation=True, records=(semantic_record,))

def test_detail_hides_annual_chart_without_yearly_evidence():
    html = render_applicant_detail(semantic_detail, current_year=2026)
    assert "Citations by year" not in html
    assert "Annual citation history is unavailable for Semantic Scholar." in html
```

Add a browser regression that opens the modal, sees the source label and notice, and sees no zero-valued annual chart.

- [ ] **Step 2: Verify RED**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_citation_plots.py tests\test_populated_preview.py tests\test_applicant_detail.py tests\test_production_identity_metrics.py tests\browser\shell.spec.py -q`

Expected: FAIL because the UI is hard-coded to OpenAlex and always renders annual citation bars.

- [ ] **Step 3: Implement source-aware rendering**

Carry the active source through `PreviewApplicantMetric` and `ApplicantDetail`. Render the approved source mapping verbatim. Render annual bars only when OpenAlex evidence supplies yearly counts; otherwise render the specified neutral notice. Preserve `NULL` as unavailable, never zero.

- [ ] **Step 4: Verify GREEN**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_citation_plots.py tests\test_populated_preview.py tests\test_applicant_detail.py tests\test_production_identity_metrics.py tests\browser\shell.spec.py -q`

Expected: PASS, including browser layout/accessibility coverage.

- [ ] **Step 5: Commit**

```bash
git add app/metrics.py app/internal_preview.py app/applicant_detail.py tests/test_citation_plots.py tests/test_populated_preview.py tests/test_applicant_detail.py tests/test_production_identity_metrics.py tests/browser/shell.spec.py
git commit -m "feat: label active citation source"
```

### Task 5: Deploy and refresh the complete Semantic Scholar cutoff

**Files:**
- Modify: `docs/import-2026.md`
- Test: `infra/test-install-ehf.py`, `tests/test_deployment_contract.py`

**Interfaces:**
- Consumes: deployed Tasks 1–4 and the private 2026 publication manifest.
- Produces: an active complete `SEMANTIC_SCHOLAR` cutoff or no metric change.

- [ ] **Step 1: Write failing operational contract tests**

```python
def test_refresh_instructions_exclude_google_scholar_and_require_complete_semantic_snapshot():
    assert "Google Scholar" not in semantic_refresh_section
    assert "SEMANTIC_SCHOLAR" in semantic_refresh_section
    assert "all eligible works" in semantic_refresh_section
```

- [ ] **Step 2: Verify RED**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest infra\test-install-ehf.py tests\test_deployment_contract.py -q`

Expected: FAIL because the API-only fallback activation procedure is undocumented.

- [ ] **Step 3: Document and execute guarded refresh**

Document: deploy clean `main`; collect `SEMANTIC_SCHOLAR` outside Git; validate plan-only; import append-only through the protected credential path; confirm active source and observed/eligible equality; verify overview totals. Do not execute a Google Scholar command. On collection/import/activation failure, retain unavailable metrics and report the failed stage without throttle-evasion retries.

- [ ] **Step 4: Verify and deploy**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q`

Expected: PASS. Push clean `main`, deploy with `scripts\deploy-ehf.ps1 -Apply -SqlAdminCredentialPath '/etc/ehf/sql-admin-password'`, then verify immutable release revision, service health, schema 31, active `SEMANTIC_SCHOLAR`, and eligible/observed equality through the protected server path.

- [ ] **Step 5: Commit**

```bash
git add docs/import-2026.md infra/test-install-ehf.py tests/test_deployment_contract.py
git commit -m "docs: operate API-only citation fallback"
```

## Self-review

- Spec coverage: Tasks 1–2 implement API-only collection/import; Task 3 implements complete-cohort activation; Task 4 presents the source honestly; Task 5 deploys and refreshes without Google Scholar.
- Placeholder scan: no unfinished markers or unspecified implementation steps remain.
- Type consistency: Task 1 emits `dict[str, str]` rows; Task 2 validates `OpenCitationReview`; Task 3 activates `ImportRunId`; Task 4 consumes the active source from SQL.
- Review focus coverage: Task 1 covers rate limiting and mismatch; Task 2 covers partial/mixed snapshots; Task 3 covers source isolation; Task 4 covers annual-history absence.
