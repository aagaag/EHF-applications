# Publication Journal Scatter Plot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add and deploy an accessible applicant-modal scatter plot whose x-axis is publication year, y-axis is current OpenAlex 2-year journal citedness, and bubble area represents current paper citations.

**Architecture:** Extend the existing private OpenAlex snapshot with primary-journal source evidence, persist that evidence in the existing append-only citation observation JSON, and expose it through a forward-only SQL projection. Render the third chart server-side with the existing dependency-free SVG pattern, then backfill all reviewed 2026 publications and verify production coverage.

**Tech Stack:** Python 3.12, SQL Server migrations and validators, FastAPI server-rendered HTML, inline accessible SVG, CSS, pytest, Playwright, PowerShell deployment/import wrappers, OpenAlex REST API.

**Spec:** `docs/superpowers/specs/2026-09-21-publication-journal-scatter-design.md`

## Global Constraints

- Work directly on clean synchronized `main`; do not create a branch or worktree.
- Use `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe` for local Python commands.
- Follow strict red-green-refactor TDD for every implementation change.
- Preserve the existing modal content, publication table behavior, first-/last-author semantics, F2 shell, four skins, and responsive rules.
- Label the metric exactly `OpenAlex 2-year journal citedness`; never call it Clarivate Journal Impact Factor.
- Keep private manifests, snapshots, credentials, applicant documents, and import outputs outside Git.
- Keep applicant invitations and production mail disabled throughout collection, import, deployment, and verification.
- Do not add browser-to-OpenAlex calls, a recurring scheduler, new runtime dependencies, or a second journal-metric database subsystem.

## Review Focus

- An accepted work whose primary source is a repository, conference, book series, or malformed object must render in the `N/A` lane without a fabricated metric; Task 1 tests this collector boundary and Task 4 tests the rendering.
- An OpenAlex source returning a negative, non-finite, string, or absent citedness value must be rejected to `NULL` without failing the whole modal; Tasks 1 and 2 test collection and import validation.
- Multiple papers and applicants sharing one journal must cause one Source lookup per collection run while preserving a separate evidence value for every paper; Task 1 tests deduplication.
- Coincident bubbles, zero citations, and missing citations must remain individually accessible and use honest area scaling; Task 4 tests SVG order, radius, labels, and fallback entries.
- Existing pre-enrichment observations must remain queryable and project `NULL` journal fields until refreshed; Task 3 validates migration compatibility and latest-observation selection.

---

### Task 1: Collect OpenAlex Journal Metrics

**Files:**
- Modify: `app/importer/open_citation_collector.py`
- Modify: `app/importer/open_citations.py`
- Test: `tests/test_open_citation_collector.py`

**Interfaces:**
- Consumes: accepted OpenAlex work JSON from `match_openalex_candidate`, the existing `OfficialCitationApiClient.get_json(url)` method, and OpenAlex Source objects.
- Produces: snapshot fields `journal_openalex_id`, `journal_openalex_name`, `journal_source_type`, `journal_two_year_mean_citedness`, `journal_source_updated_date`, and `journal_metric_observed_at_utc` on every OpenAlex row.

- [ ] **Step 1: Write failing collector tests**

Add tests that provide two accepted work records sharing `https://openalex.org/S123`, assert one `/sources/S123` request, and assert both rows contain the same validated journal evidence. Add parameterized tests for source types other than `journal`, absent `primary_location.source`, and metric values `None`, `-1`, `"3.2"`, `NaN`, and `Infinity`; these rows must retain the work match but emit blank metric fields.

```python
assert client.source_requests == ["https://api.openalex.org/sources/S123"]
assert rows[0]["journal_openalex_id"] == "https://openalex.org/S123"
assert rows[0]["journal_two_year_mean_citedness"] == "4.25"
assert rows[1]["journal_two_year_mean_citedness"] == "4.25"
```

- [ ] **Step 2: Run collector tests and verify RED**

Run:

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_open_citation_collector.py -q
```

Expected: failures because journal fields and deduplicated Source lookups do not exist.

- [ ] **Step 3: Add snapshot fields and journal-source collection**

Extend `OPEN_CITATION_FIELDS` after `annual_citation_counts`. Add a small validated value object and helpers with these contracts:

```python
@dataclass(frozen=True, slots=True)
class OpenAlexJournalMetric:
    source_id: str
    name: str
    source_type: str
    two_year_mean_citedness: float | None
    source_updated_date: str
    observed_at_utc: str

def collect_openalex_journal_metrics(
    rows: Sequence[dict[str, str]],
    matched_candidates: dict[str, dict[str, Any]],
    client: OfficialCitationApiClient,
    *,
    observed_at_utc: str,
) -> dict[str, OpenAlexJournalMetric]: ...
```

Extract only canonical `https://openalex.org/S<digits>` primary-source IDs from accepted work matches, deduplicate them, request `https://api.openalex.org/sources/S<digits>?select=id,display_name,type,summary_stats,updated_date`, and accept `summary_stats.2yr_mean_citedness` only when it is a finite nonnegative JSON number and `type == "journal"`. Serialize floats with stable decimal text and blanks for unavailable fields. Semantic Scholar rows keep every journal field blank.

- [ ] **Step 4: Run collector tests and verify GREEN**

Run the Task 1 command. Expected: all collector tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add app/importer/open_citation_collector.py app/importer/open_citations.py tests/test_open_citation_collector.py
git commit -m "feat: collect OpenAlex journal citedness"
```

### Task 2: Validate and Persist Journal Evidence

**Files:**
- Modify: `app/importer/open_citations.py`
- Modify: `scripts/verify-open-citations-2026.ps1`
- Test: `tests/test_open_citation_importer.py`
- Test: `tests/test_open_citation_ops.py`

**Interfaces:**
- Consumes: the Task 1 snapshot schema.
- Produces: journal evidence inside each OpenAlex `PublicationCitationObservation.EvidenceJson` under stable snake-case keys and bounded production coverage output.

- [ ] **Step 1: Write failing importer and verifier tests**

Extend the canonical CSV fixture with the six journal fields. Assert `load_open_citation_reviews` accepts a valid journal record, rejects mismatched source IDs, non-HTTPS OpenAlex IDs, future/invalid dates, non-journal metrics, negative/non-finite metrics, and any journal evidence on `NOT_FOUND` rows. Assert the repository evidence contains:

```python
{
    "journal_openalex_id": "https://openalex.org/S123",
    "journal_openalex_name": "Example Journal",
    "journal_source_type": "journal",
    "journal_two_year_mean_citedness": 4.25,
    "journal_source_updated_date": "2026-09-20",
    "journal_metric_observed_at_utc": "2026-09-21T08:00:00.000000Z",
}
```

Add an operations assertion that the verifier prints and bounds journal-source, valid-metric, `N/A`, missing-year, and latest-observation counts.

- [ ] **Step 2: Run importer/operations tests and verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_open_citation_importer.py tests/test_open_citation_ops.py -q
```

Expected: schema/evidence assertions fail because journal evidence is not parsed or stored.

- [ ] **Step 3: Implement strict journal-evidence parsing**

Add optional typed fields to `OpenCitationReview`, validate the canonical OpenAlex source-ID expression `https://openalex.org/S[0-9]+`, require all identity/type/date fields when a metric is present, and parse the metric through `Decimal` before converting to a finite nonnegative float. Preserve legacy snapshot compatibility only for existing pre-feature snapshots; newly collected canonical snapshots use the expanded exact field list.

When inserting `EvidenceJson`, include journal keys only for OpenAlex observations and JSON numeric citedness rather than a string. Keep payload hashing over the complete evidence so repeat imports remain idempotent.

- [ ] **Step 4: Extend production verification**

Update `scripts/verify-open-citations-2026.ps1` to parse journal evidence with SQL `JSON_VALUE`/`TRY_CONVERT`, print the seven counts required by the spec, reject invalid numeric/source combinations, and avoid hard-coding a valid-metric count until the reviewed production snapshot establishes it. Keep the existing exact 847-row and safety-gate assertions.

- [ ] **Step 5: Run importer/operations tests and verify GREEN**

Run the Task 2 command. Expected: all targeted tests pass.

- [ ] **Step 6: Commit Task 2**

```powershell
git add app/importer/open_citations.py scripts/verify-open-citations-2026.ps1 tests/test_open_citation_importer.py tests/test_open_citation_ops.py
git commit -m "feat: persist OpenAlex journal evidence"
```

### Task 3: Project Journal Metrics into Applicant Details

**Files:**
- Create: `database/migrations/034_applicant_journal_metrics.sql`
- Create: `database/tests/034_validate_applicant_journal_metrics.sql`
- Modify: `app/metrics.py`
- Modify: `infra/install-ehf.py`
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_applicant_schema.py`
- Modify: `tests/test_pilot_sql_repositories.py`
- Test: `tests/test_metric_detail_route.py`

**Interfaces:**
- Consumes: the latest OpenAlex `EvidenceJson` journal keys from Task 2.
- Produces: four nullable fields on `Publication`: `journal_openalex_id: str | None`, `journal_openalex_name: str | None`, `journal_two_year_mean_citedness: float | None`, and `journal_metric_observed_at_utc: str | None`.

- [ ] **Step 1: Write failing migration and repository tests**

Advance migration expectations from 33 to 34 and package both new SQL files. Assert migration 034 alters `dbo.GetInternalApplicantMetricDetail`, keeps the same authorization check, selects the latest OpenAlex observation, and projects:

```sql
JSON_VALUE(latest.EvidenceJson,'$.journal_openalex_id'),
JSON_VALUE(latest.EvidenceJson,'$.journal_openalex_name'),
TRY_CONVERT(decimal(18,6),JSON_VALUE(latest.EvidenceJson,'$.journal_two_year_mean_citedness')),
JSON_VALUE(latest.EvidenceJson,'$.journal_metric_observed_at_utc')
```

Add repository fixtures with the four extra columns and assert the `Publication` object carries them. Include an old observation with absent keys and assert all four values are `None`.

- [ ] **Step 2: Run migration/repository tests and verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_migrations.py tests/test_applicant_schema.py tests/test_pilot_sql_repositories.py tests/test_metric_detail_route.py -q
```

Expected: migration count, package list, SQL projection, and dataclass-field tests fail.

- [ ] **Step 3: Add migration 034 and validator**

Create a forward-only `ALTER PROCEDURE dbo.GetInternalApplicantMetricDetail` based on migration 030, append the four journal columns after `AuthorsText`, and preserve `OUTER APPLY TOP (1)` ordering. Use `TRY_CONVERT` for the metric and return `NULL` for missing legacy evidence. The validator executes the procedure for authorized roles inside a rollback transaction, rejects unauthorized roles, and confirms the procedure definition contains every new JSON key.

- [ ] **Step 4: Extend the Python projection**

Add the four fields to `Publication` and map row indexes 9–12 defensively in `app.metrics._publication`. Parse the metric with `_number`; leave missing columns compatible with synthetic repositories used by existing tests.

- [ ] **Step 5: Run migration/repository tests and verify GREEN**

Run the Task 3 command. Expected: all targeted tests pass.

- [ ] **Step 6: Commit Task 3**

```powershell
git add database/migrations/034_applicant_journal_metrics.sql database/tests/034_validate_applicant_journal_metrics.sql app/metrics.py infra/install-ehf.py tests/test_migrations.py tests/test_applicant_schema.py tests/test_pilot_sql_repositories.py tests/test_metric_detail_route.py
git commit -m "feat: project applicant journal metrics"
```

### Task 4: Render the Accessible Bubble Chart

**Files:**
- Modify: `app/applicant_detail.py`
- Modify: `public/assets/site.css`
- Test: `tests/test_applicant_detail.py`
- Test: `tests/browser/shell.spec.py`

**Interfaces:**
- Consumes: Task 3 `Publication` journal fields and existing author-position/citation fields.
- Produces: `_journal_scatter_chart(detail: ApplicantDetail) -> str` rendered as the third `.applicant-detail-chart`.

- [ ] **Step 1: Write failing renderer tests**

Add publications covering positive, zero, and missing citations; numeric metric, missing metric, invalid year; lead, middle, and last authors; HTML-special characters; and coincident year/metric values. Assert:

```python
assert 'data-journal-scatter' in html
assert '>OpenAlex 2-year journal citedness</text>' in html
assert 'data-journal-metric-status="unavailable"' in html
assert 'data-author-position="first"' in html
assert 'Bubble area represents OpenAlex citations' in html
assert '1 paper omitted because its publication year is unavailable.' in html
```

Parse circle radii and assert `pi * r²` increases linearly with citation count after the minimum area. Assert exact same-year x coordinates, largest-first DOM order, one accessible list item per valid-year publication, and escaped labels.

- [ ] **Step 2: Run renderer tests and verify RED**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_applicant_detail.py -q
```

Expected: failures because the third chart is absent.

- [ ] **Step 3: Implement the scatter renderer**

Add `_journal_scatter_chart` with a 720×220 viewBox, exact integer-year x scale, numeric y scale starting at zero, a separated `N/A` lane when needed, and radius calculation:

```python
minimum_area = 36.0
maximum_extra_area = 900.0
area = minimum_area + maximum_extra_area * (citations / maximum_citations)
radius = round(math.sqrt(area / math.pi), 2)
```

Sort renderable points by radius descending before emitting circles. Reuse `_author_position`; emit red semantic classes only for `first`, `last`, or `sole`. Add `<title>`, `aria-label`, `tabindex="0"`, a screen-reader list, snapshot-date text, plotted/omitted counts, and the compact empty state. Escape all source strings through `_text`/`escape`.

- [ ] **Step 4: Add minimal approved styling**

Change the desktop chart grid to `repeat(3, minmax(0, 1fr))`; retain the existing one-column rule at 800px. Add styles for scatter fill, lead-author outline, unavailable dashed outline, focus, legend, and screen-reader-only list without changing existing bar-chart or modal tokens.

- [ ] **Step 5: Run renderer tests and verify GREEN**

Run the Task 4 unit command. Expected: all renderer tests pass.

- [ ] **Step 6: Write and run browser tests**

Update the existing chart-layout test to expect three same-row figures at 1920×1080 and 1366×768. Add tablet/phone assertions that figures stack, the modal has no horizontal overflow, every bubble is keyboard focusable with a complete accessible name, red outline is visible in all four skins, and double-click/Enter on publication rows still opens exactly once.

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/browser/shell.spec.py -q
```

Expected: all browser tests pass.

- [ ] **Step 7: Commit Task 4**

```powershell
git add app/applicant_detail.py public/assets/site.css tests/test_applicant_detail.py tests/browser/shell.spec.py
git commit -m "feat: chart applicant journal citedness"
```

### Task 5: Full Verification, Production Backfill, and Deployment

**Files:**
- Modify if required by established count: `scripts/verify-open-citations-2026.ps1`
- Update: `CODEX_COORDINATION.md`

**Interfaces:**
- Consumes: completed Tasks 1–4, the private publication manifest outside Git, `/etc/ehf/openalex-api-key`, and `/etc/ehf/sql-admin-password`.
- Produces: synchronized `main`, an immutable deployed release, a fresh private production OpenAlex snapshot, active journal metrics, and verified live modal data.

- [ ] **Step 1: Run focused and full local verification**

```powershell
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_open_citation_collector.py tests/test_open_citation_importer.py tests/test_open_citation_ops.py tests/test_migrations.py tests/test_applicant_schema.py tests/test_pilot_sql_repositories.py tests/test_metric_detail_route.py tests/test_applicant_detail.py tests/browser/shell.spec.py -q
& 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q
git diff --check
```

Expected: zero failures and no whitespace errors.

- [ ] **Step 2: Inspect the complete diff and update the coordination handoff**

Record the new OpenAlex evidence keys, migration 034, chart behavior, exact test counts, and the fact that invitations/mail remain disabled. Confirm only task files are modified.

- [ ] **Step 3: Commit and push the completed implementation**

```powershell
git add CODEX_COORDINATION.md app database infra public scripts tests
git commit -m "feat: add applicant journal scatter plot"
git push origin main
```

- [ ] **Step 4: Deploy migration and application code**

```powershell
$head=(git rev-parse HEAD).Trim()
powershell -NoProfile -File scripts/deploy-ehf.ps1 -Apply -SqlAdminCredentialPath '/etc/ehf/sql-admin-password'
powershell -NoProfile -File scripts/verify-ehf.ps1 -ExpectedCommit $head
```

Expected: migration 034 validates, the immutable release activates, readiness passes, and invitation/mail gates remain false.

- [ ] **Step 5: Collect a private enriched OpenAlex snapshot**

Use the recovered private 847-work publication manifest at `C:\Users\aag\Documents\ChatGPT\ehf-pub.json`. Write the new snapshot to the short private path `C:\Users\aag\Documents\ChatGPT\ehf-oa-j.csv`.

```powershell
powershell -NoProfile -File scripts/collect-open-citations-2026.ps1 -ManifestPath 'C:\Users\aag\Documents\ChatGPT\ehf-pub.json' -OutputPath 'C:\Users\aag\Documents\ChatGPT\ehf-oa-j.csv' -Source OPENALEX
```

Expected: exactly 847 rows, one per reviewed work, with bounded journal-metric coverage and no secret or applicant document written to Git.

- [ ] **Step 6: Plan and apply the enriched snapshot**

```powershell
powershell -NoProfile -File scripts/import-open-citations-2026.ps1 -ManifestPath 'C:\Users\aag\Documents\ChatGPT\ehf-pub.json' -SnapshotPath 'C:\Users\aag\Documents\ChatGPT\ehf-oa-j.csv'
powershell -NoProfile -File scripts/import-open-citations-2026.ps1 -ManifestPath 'C:\Users\aag\Documents\ChatGPT\ehf-pub.json' -SnapshotPath 'C:\Users\aag\Documents\ChatGPT\ehf-oa-j.csv' -Apply -SqlAdminCredentialPath '/etc/ehf/sql-admin-password'
powershell -NoProfile -File scripts/verify-open-citations-2026.ps1 -SqlAdminCredentialPath '/etc/ehf/sql-admin-password'
```

Expected: PlanOnly and Apply succeed, every work has one current OpenAlex observation, and valid journal metrics plus explicit `N/A` cases satisfy the verifier.

- [ ] **Step 7: Perform live data and visual verification**

Query `dbo.GetInternalApplicantMetricDetail` through the authorized root-mediated verification path for at least one applicant with multiple cited journals, Hung Ho-Xuan, a paper with zero/missing citations, and a paper in the `N/A` lane. Confirm the response contains no confidential document data. Open the authenticated modal at 1920×1080, 1366×768, tablet, and phone widths; inspect all four skins, keyboard-focus every point, and verify no horizontal overflow.

- [ ] **Step 8: Re-run deployment and production contracts**

```powershell
$head=(git rev-parse HEAD).Trim()
powershell -NoProfile -File scripts/verify-ehf.ps1 -ExpectedCommit $head
powershell -NoProfile -File scripts/verify-review-artifacts-2026.ps1 -SqlAdminCredentialPath '/etc/ehf/sql-admin-password'
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

Expected: service, artifact counts, OpenAlex coverage, clean worktree, and synchronized commit all pass.
