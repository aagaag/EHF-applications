# Robust Applicant Publication Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, run, and deploy a reproducible parser that scans every applicant PDF, extracts order-independent bibliographic records, separates publication status from DOI resolution, and reconciles a validated full publication manifest.

**Architecture:** A local batch pipeline extracts ordinary and layout-preserving PDF text, detects publication regions, segments citation entries, labels fields through a loopback GROBID service with deterministic fallbacks, classifies status from explicit evidence, and reconciles candidates additively into the existing private manifest. The production importer remains append-only and is relaxed so a source-verified publication does not require a DOI.

**Tech Stack:** Python 3.13, `pypdf==6.10.0`, `httpx==0.28.1`, stdlib XML/JSON/CSV, GROBID `0.9.1-crf` in a pinned local Docker container, pytest, SQL Server, PowerShell, SSH.

**Spec:** `docs/superpowers/specs/2026-09-22-robust-publication-parser-design.md`

## Global Constraints

- Work directly on clean synchronized `main`; do not create a branch or worktree.
- Use the explicit repository Python runtime.
- Follow RED-GREEN-REFACTOR for every production-code behavior.
- Keep applicant PDFs, extracted citations, manifests, audits, and test artifacts outside Git.
- Do not upload applicant PDFs to public services.
- Preserve append-only publication evidence and existing manual review decisions.
- Stage only task-owned files and keep invitations/production mail disabled.

## Review Focus

- A DOI-less but complete journal citation must be eligible for `PUBLISHED`.
- A year in a separate left column and a multi-line body must remain one citation.
- A tightly set CV page with no blank lines must split on terminal-year/next-author boundaries.
- A contact header, narrative explanation, research highlight, or research-plan bibliography must not become an applicant publication.
- A repeated title appearing as both workshop paper and later preprint must not be collapsed without version/status evidence.

---

### Task 1: Decouple Publication Disposition from DOI Resolution

**Files:**
- Modify: `tests/test_publication_importer.py`
- Modify: `app/importer/publications.py`

**Interfaces:**
- Consumes: manifest `resolution.evidence.review_disposition`.
- Produces: validated explicit `PUBLISHED` decisions for DOI-less source-verified records while retaining `resolution.status` as metadata-resolution evidence.

- [ ] Add a failing loader test containing complete authors/title/journal/year metadata, no DOI, `resolution.status="UNRESOLVED"`, and an explicit `PUBLISHED` review decision.
- [ ] Run the focused test and confirm it fails on the current DOI/status coupling.
- [ ] Remove only the rule that forbids an explicit published disposition on a non-DOI-resolved record; retain DOI normalization, uniqueness, and conflict checks.
- [ ] Run `pytest tests/test_publication_importer.py -q` and confirm green.

### Task 2: Layout-Aware Document and Section Extraction

**Files:**
- Create: `app/importer/publication_extraction.py`
- Create: `tests/test_publication_extraction.py`

**Interfaces:**
- Produces: `PdfPageText`, `PublicationSection`, `PublicationCandidate`, `DocumentExtractionAudit`, `extract_document(path, applicant_name)`.

- [ ] Add failing de-identified tests for plain/layout mode selection, publication-heading normalization, excluded `References`/presentation sections, repeated headers/footers, empty PDFs, and all five representative entry layouts.
- [ ] Run the focused tests and confirm failures are caused by missing extraction APIs.
- [ ] Implement page extraction, section state, line cleanup, entry segmentation, source hashing, and document audit output.
- [ ] Run the focused tests and refactor only after green.

### Task 3: Order-Independent Citation Field Parsing and Classification

**Files:**
- Modify: `app/importer/publication_extraction.py`
- Modify: `tests/test_publication_extraction.py`

**Interfaces:**
- Consumes: `PublicationCandidate`.
- Produces: `ParsedPublication`, `GrobidCitationParser.parse(raw_citation)`, deterministic fallback fields, evidence score, and review disposition.

- [ ] Add failing TEI parsing tests for author/title/journal/volume/pages/year/DOI with different field orders and truncated authors.
- [ ] Add failing classification tests for published journal articles without DOI/pages, peer-reviewed conference papers, preprints/submitted manuscripts, in-preparation work, theses, and ambiguous fragments.
- [ ] Run the focused tests RED.
- [ ] Implement the loopback-only GROBID client, TEI adapter, conservative fallback extraction, applicant-author validation, evidence scoring, and fail-closed status rules.
- [ ] Run the focused tests GREEN and preserve raw citation/evidence in every result.

### Task 4: Full-Manifest Reconciliation

**Files:**
- Create: `app/importer/publication_reconciliation.py`
- Create: `tests/test_publication_reconciliation.py`
- Create: `app/importer/run_publication_extraction.py`

**Interfaces:**
- Consumes: source root, applicant/folder mapping from a private base manifest, `ParsedPublication` results, and the existing full manifest.
- Produces: private extraction audit JSON/CSV and a self-hashed full publication manifest accepted by `load_publication_manifest`.

- [ ] Add failing tests for DOI match, strict title/applicant/year match, manual-decision preservation, pending promotion, new stable work/occurrence IDs, duplicate rerun idempotency, source coverage, summary recomputation, and self-hash validation.
- [ ] Run reconciliation tests RED.
- [ ] Implement additive reconciliation, default citation-source rows, deterministic IDs, manifest summary/count recomputation, and CLI plan/run modes.
- [ ] Run reconciliation and importer tests GREEN.

### Task 5: Operator Workflow and Documentation

**Files:**
- Create: `scripts/extract-publications-2026.ps1`
- Modify: `docs/import-2026.md`
- Create or modify focused script-contract tests under `tests/`.

**Interfaces:**
- Consumes: private source root/base manifest/output directory and a loopback GROBID endpoint.
- Produces: pinned-container startup/health verification, parser invocation, private outputs, cleanup, and exact operator commands.

- [ ] Add failing contract tests proving the script pins GROBID, binds only loopback, never copies PDFs into Git, validates output permissions/paths, and stops on unhealthy parsing.
- [ ] Run focused tests RED.
- [ ] Implement the wrapper and document extraction, plan-validation, apply, verification, and rollback commands.
- [ ] Run focused tests GREEN.

### Task 6: Reprocess and Reconcile the Complete 2026 Corpus

**Files:**
- Private outputs only under `C:/Users/aag/Documents/ChatGPT/EHF-pubs/`.
- Modify exact production count constants and verification contracts only after the final private manifest is known.

**Interfaces:**
- Consumes: 153 source PDFs, current reviewed full manifest, local GROBID.
- Produces: corpus audit, reconciled manifest, final count contract, and discrepancy report.

- [ ] Start the pinned loopback GROBID container and record its immutable image digest.
- [ ] Run the parser across every applicant document and confirm all files receive an audit outcome.
- [ ] Reconcile against the current manifest; inspect every new affirmative row and every unmatched/low-confidence candidate from its page evidence.
- [ ] Confirm the known failures (Burja, Chopard, Shami Pour, Roese Mores, Panagopoulos) meet source counts/status expectations and that no applicant count silently decreases.
- [ ] Regenerate the full manifest, run plan-only import validation, and update exact count contracts with focused RED/GREEN tests.

### Task 7: Verify, Commit, Push, Deploy, Apply, and Validate Production

**Files:**
- Repository files from Tasks 1-5 plus final count-contract changes.
- Private manifest/audit from Task 6 remains outside Git.

**Interfaces:**
- Produces: deployed parser/importer release, applied append-only corpus repair, and verified production counts/statuses.

- [ ] Run parser, reconciliation, importer, migration, and operator-script focused tests.
- [ ] Run the complete pytest suite, `git diff --check`, syntax/compile checks, and deployment preflight.
- [ ] Review the complete diff for applicant data, credentials, unsafe file operations, classification overreach, and count drift.
- [ ] Commit with task-scoped subjects, push `main`, deploy the exact commit, and verify service health/static assets.
- [ ] Plan-validate and apply the private reconciled manifest through the privileged wrapper.
- [ ] Run production publication verification and direct checks for every applicant's published/preprint/pending counts, including the five named failures.
- [ ] Confirm invitations and production mail remain disabled; retain the previous release identifier and manifest hash as rollback/audit anchors.

## Self-Review

- Spec coverage: every architecture stage, status rule, privacy boundary, validation gate, and deployment/rollback requirement maps to a task.
- Placeholder scan: no deferred implementation placeholders remain.
- Type consistency: extraction results flow into parsing, then reconciliation, then the existing manifest loader.
- Review-focus coverage: Tasks 1-4 explicitly test all five listed failure classes.
