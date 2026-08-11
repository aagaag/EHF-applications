# Citation Plot Call-outs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every citation-plot applicant a distinct shared color and label the 15 most-cited plotted applicants by surname in the web and Excel reports.

**Architecture:** Add one dependency-free citation-plot model that owns citation fallback, surname extraction, deterministic distinct colors, plot eligibility, and top-15 ranking. The existing HTML/SVG and XLSX renderers consume that model so their identities, colors, and labels cannot diverge.

**Tech Stack:** Python 3, server-rendered HTML/SVG, `openpyxl`, pytest, Playwright, Microsoft Excel desktop for final workbook rendering.

## Global Constraints

- Work directly on `main`; do not create a branch or worktree.
- Preserve the current total-citations-with-Google-Scholar-fallback rule.
- Preserve all existing report data, authorization, filtering, sorting, table, modal, export-audit, and invitation behavior.
- Use the explicit repository Python runtime at `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`.
- Use test-driven development: each production behavior must first be demonstrated by a focused failing test.
- Do not use LibreOffice; Microsoft Excel is the workbook compatibility authority.

---

### Task 1: Shared citation point model

**Files:**
- Create: `app/citation_plots.py`
- Create: `tests/test_citation_plots.py`

**Interfaces:**
- Consumes: report records exposing `applicant`, `total_citations`, `google_scholar_citations`, and an requested age attribute.
- Produces: `CitationPlotPoint`, `applicant_surname(name)`, `citation_plot_points(records, age_field, label_limit=15)`.

- [ ] **Step 1: Write the failing shared-model tests**

Create tests asserting comma-form and ordinary surnames, suffix removal, total-citation fallback, exclusion of incomplete axes, unique deterministic `#RRGGBB` colors, consistent colors between age fields, and top-15 ordering with deterministic ties.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_citation_plots.py -q`

Expected: collection fails because `app.citation_plots` does not exist.

- [ ] **Step 3: Implement the minimum shared model**

Add a frozen `CitationPlotPoint` carrying source index, applicant, surname, age, citations, color, and `labelled`. Generate one unique palette entry per source record, select finite points for the requested age field, rank by descending citations/name/source index, and mark at most 15 labels.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the command from Step 2 and expect all shared-model tests to pass.

### Task 2: Accessible web SVG colors and call-outs

**Files:**
- Modify: `app/internal_preview.py`
- Modify: `public/assets/site.css`
- Modify: `tests/test_populated_preview.py`
- Modify: `tests/browser/shell.spec.py`

**Interfaces:**
- Consumes: `citation_plot_points(records, age_field)`.
- Produces: SVG markers with distinct `fill` colors and full accessible names; `.plot-callout` groups containing colored leader paths and surname text for the labelled points.

- [ ] **Step 1: Write failing HTML and browser behavior tests**

Use 18 complete synthetic applicants with unique citation totals and long hyphenated surnames. Assert two SVGs, 18 colored marker circles per SVG, 15 call-outs per SVG, labels for the 15 highest totals, no labels for the remaining three, full-name accessible marker descriptions, wrapped labels contained by the SVG and viewport, high-contrast marker/leader outlines in all four skins, no page overflow at desktop and phone widths, and zero Axe violations.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_populated_preview.py tests/browser/shell.spec.py -q`

Expected: the new marker-color and call-out assertions fail because the existing SVG uses one CSS fill and contains no call-outs.

- [ ] **Step 3: Implement SVG call-out lanes**

Replace the local point construction with the shared model. Preserve axes and report-card structure, expand the view box only as needed for left/right call-out lanes, assign vertically ordered slots on each side, draw haloed leader paths, wrap and fit escaped surname text within each lane, and make each marker keyboard-focusable with a full descriptive accessible label.

- [ ] **Step 4: Update scoped styles**

Keep marker opacity, allow SVG presentation colors to control marker fill, and add high-contrast marker outlines plus readable call-out label/leader styles that work in all four skins without relying on color alone.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the command from Step 2 and expect all focused HTML/browser tests to pass.

### Task 3: Native Excel marker colors and top-15 labels

**Files:**
- Modify: `app/report_exports.py`
- Modify: `tests/test_report_exports.py`

**Interfaces:**
- Consumes: `citation_plot_points(records, age_field)`.
- Produces: one one-point `openpyxl.chart.Series` per plottable applicant, matching marker colors, hidden legend, and series-name data labels only on the top-15 series.

- [ ] **Step 1: Write failing workbook chart tests**

Build a workbook from 18 complete records. Assert each chart has 18 one-point series, all marker foreground colors are distinct, colors match between both charts by source order, and exactly 15 series per chart enable series-name data labels with the expected surnames.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_report_exports.py -q`

Expected: assertions fail because each existing chart contains a single monochrome series without data labels.

- [ ] **Step 3: Implement one-point chart series**

Iterate over shared points for each age field. Reference the exact source-row x and citation cells, set the series title to the safe surname, apply the shared marker color with a dark contrasting outline, remove connecting lines, reserve label headroom on both axes, and attach a `DataLabelList(showSerName=True, dLblPos="r")` only when `point.labelled` is true.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2 and expect all workbook tests to pass.

### Task 4: Regression, visual QA, and handoff

**Files:**
- Modify: `CODEX_COORDINATION.md`

**Interfaces:**
- Consumes: completed web and workbook changes.
- Produces: verified repository state and a concise non-sensitive handoff note.

- [ ] **Step 1: Run the full suite**

Run: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q`

Expected: all tests pass with no warnings or errors.

- [ ] **Step 2: Perform visual verification**

Render the internal report at representative desktop and phone widths and inspect both plots for marker colors, readable top-15 surnames, leader-line correspondence, and horizontal overflow. Generate a synthetic workbook, open it in one controlled hidden Microsoft Excel instance, export chart previews, inspect both charts, then close the workbook and quit that exact automation instance in `finally`.

- [ ] **Step 3: Review the complete diff**

Confirm no applicant data, generated workbook, screenshot, credential, or test artifact is tracked; confirm the approved source specification and older plans are unchanged.

- [ ] **Step 4: Update coordination notes**

Append a non-sensitive summary of behavior and verification evidence to `CODEX_COORDINATION.md`.

- [ ] **Step 5: Commit the scoped files**

Stage only the design, plan, citation model, renderers, styles, tests, and coordination note. Commit with: `feat: label EHF citation scatter plots`.

- [ ] **Step 6: Do not push or deploy without explicit authorization**

Leave the verified commit on local `main` because the project-specific instructions require an explicit push authorization.
