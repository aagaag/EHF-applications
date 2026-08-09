# EHF 2026 Import and Document Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Import and reconcile all 36 2026 applications and every source file without modifying the source folder, while making confidential recommendation disclosure structurally impossible in applicant APIs and downloads.

**Architecture:** A root-mediated, one-shot importer reads the approved Word register and call directory, produces a deterministic manifest, and hands controlled copies to a locked ingestion worker. Files enter quarantine, pass PDF validation and malware scanning, receive plaintext and encrypted-object hashes, and are written as AES-256-GCM encrypted immutable objects. SQL records every source occurrence, classification suggestion, manual classification decision, version, and audit event. Applicant document projections are allowlists over approved `APPLICANT_VISIBLE` versions; recommendations use separate views/procedures and never share an applicant query path.

**Tech Stack:** Python 3.12, `python-docx`, `pypdf`, `pypdfium2`, `cryptography`, `pyodbc`, ClamAV `clamdscan`, SQL Server, pytest, PowerShell, and systemd one-shot workers.

**Global Constraints:** Plan 1 must be complete; the source directory and Word register are read-only; filenames never determine authorization; every recommendation is confidential even when uploaded or forwarded by an applicant; every imported object starts invisible to applicants; no invitation can be enabled until all classifications and the registered email are manually reviewed; rejected or quarantined files never enter a download view; and production data must never be copied into Git or tests.

## Fixed source inputs

- Register: `C:\Users\aag\Stiftung Foundation ISAB\ISAB - Charles Weissmann Foundation\Fellowships\Call 2026\Call_2026_applicant_metrics.docx`
- Call root: `C:\Users\aag\Stiftung Foundation ISAB\ISAB - Charles Weissmann Foundation\Fellowships\Call 2026`
- Expected application count: `36`
- Known source-PDF inventory at design time: `153` PDFs; execution must recalculate rather than trust this count.

## Task 1: Extend the database for documents, classifications, and import provenance

**Files:**

- Create: `database/migrations/005_document_store.sql`
- Create: `database/migrations/006_import_provenance.sql`
- Create: `database/migrations/007_document_permissions.sql`
- Create: `database/tests/005_validate_document_store.sql`
- Create: `database/tests/006_validate_import_provenance.sql`
- Create: `database/tests/007_validate_document_permissions.sql`
- Create: `tests/test_document_schema.py`

**Step 1: Write failing schema and permission tests**

Require `DocumentSlot`, `Document`, `DocumentVersion`, `StoredObject`, `Recommendation`, `SourceOccurrence`, `ImportRun`, `ImportRow`, `ImportException`, and `ClassificationDecision`. Require classifications `UNREVIEWED`, `APPLICANT_VISIBLE`, `CONFIDENTIAL_RECOMMENDATION`, and `INTERNAL_ADMINISTRATIVE`. Require append-only source occurrences and versions, exactly one active approved version per slot, and a database rejection when a recommendation is projected as applicant-visible.

**Step 2: Run**

Run `python -m pytest tests/test_document_schema.py -q`.

Expected: failures for absent migrations.

**Step 3: Implement the schema**

Store an opaque short object key, key version, AES-GCM nonce/header version, plaintext SHA-256, ciphertext SHA-256, byte size, media type, page count, scan engine/signature, scan time/result, and immutable creation identity. Keep document classification separate from document type so `recommendation letter` always maps to the confidential class. Link each known letter to a separate internal `Recommendation` record whose arrival channel distinguishes direct referee delivery, applicant-forwarded material, and unknown legacy provenance without changing confidentiality. Preserve duplicate source occurrences as separate provenance rows even when hashes match.

Create two non-overlapping SQL projections:

- `vw_ApplicantVisibleDocumentVersion`: only manually reviewed, scan-clean, active `APPLICANT_VISIBLE` versions for the current applicant.
- `vw_InternalDocumentVersion`: all authorized internal classes and versions.

Grant no applicant-facing procedure access to the internal view. Add a pre-invitation procedure that fails unless every source occurrence has a reviewed classification and the applicant email has a reviewed status.

**Step 4: Verify**

Run `powershell -File scripts/test-database.ps1 -DatabaseName EHFApplications_Test`.

Expected: migrations `005`–`007` pass; attempts to expose a confidential recommendation or update/delete an immutable version fail.

**Step 5: Commit**

Commit message: `feat: add confidential document data boundary`

## Task 2: Build the application-encrypted object store

**Files:**

- Create: `app/documents/__init__.py`
- Create: `app/documents/store.py`
- Create: `app/documents/keys.py`
- Create: `app/documents/validation.py`
- Create: `app/documents/malware.py`
- Create: `tests/test_document_store.py`
- Create: `tests/test_pdf_validation.py`
- Create: `tests/test_malware.py`
- Create: `tests/fixtures/pdfs/manifest.json`
- Create: `infra/ehf-clamav.conf`

**Step 1: Write failing tests**

Cover round-trip encryption, random nonces, AAD binding to document/version/object IDs, key rotation, ciphertext tampering, wrong-object substitution, truncated files, atomic temporary-file promotion, duplicate plaintext hashes, and crash cleanup. Cover extension/MIME/signature mismatch, non-PDF input, encrypted/password-protected PDF, excessive byte/page limits, malformed cross-reference tables, embedded files, JavaScript/actions, and ClamAV clean/infected/unavailable outcomes.

Use generated synthetic PDFs only. Generate the EICAR fixture during the test and delete it in test cleanup; do not commit an antivirus test string or infected file.

**Step 2: Run**

Run `python -m pytest tests/test_document_store.py tests/test_pdf_validation.py tests/test_malware.py -q`.

Expected: missing-module failures.

**Step 3: Implement**

Use a versioned AES-256-GCM envelope with a 96-bit random nonce and AAD containing the fixed format version plus application/document/version/object IDs. Read the keyring from a systemd credential, never an environment value. Write to quarantine mode `0600`, validate and scan, encrypt to a temporary object in `/var/lib/ehf/o`, fsync, rename atomically, then commit metadata. On database failure, remove only the unregistered newly written object. Never log names, paths, hashes that could be public download handles, file contents, keys, or scan payloads.

Reject PDFs with active content or embedded files. Preserve digitally generated source pages as PDF vectors; do not rasterize accepted originals.

**Step 4: Re-run**

Expected: all object-store, validation, and malware tests pass, including fail-closed behavior when ClamAV is unavailable.

**Step 5: Commit**

Commit message: `security: encrypt and validate EHF documents`

## Task 3: Inventory the 2026 source tree without mutation

**Files:**

- Create: `app/importer/__init__.py`
- Create: `app/importer/inventory.py`
- Create: `app/importer/model.py`
- Create: `scripts/inventory-call-2026.ps1`
- Create: `tests/test_source_inventory.py`
- Create: `tests/fixtures/import/source-tree-manifest.json`

**Step 1: Write failing inventory tests**

Create a synthetic folder tree with applicant folders, nested synced-link directories, duplicate files, a `Selection Committee` folder, mixed-case PDF extensions, non-PDFs, and inaccessible entries. Assert stable normalized relative paths, SHA-256 per occurrence, no symlink traversal outside the root, duplicate reporting, separate internal-folder reporting, and byte-for-byte source immutability.

**Step 2: Implement**

Traverse recursively with resolved-path containment checks. Never follow a link outside the call root. Record every file occurrence and error; do not silently skip. Produce JSON and CSV manifests with short generated filenames under a caller-specified output directory outside the source tree. Exclude `Selection Committee` from applicant matching but retain its files in the internal inventory report.

**Step 3: Verify on fixtures**

Run `python -m pytest tests/test_source_inventory.py -q`.

Expected: all tests pass.

**Step 4: Perform a read-only production inventory**

Run:

```powershell
powershell -File scripts/inventory-call-2026.ps1 `
  -SourceRoot "C:\Users\aag\Stiftung Foundation ISAB\ISAB - Charles Weissmann Foundation\Fellowships\Call 2026" `
  -OutputRoot "$env:TEMP\ehf-i"
```

Expected: 36 applicant directory candidates, a recalculated file/PDF count, explicit duplicate and exception sections, and a post-run source-tree hash identical to the pre-run hash. Do not commit the manifest because it contains personal filenames.

**Step 5: Commit**

Commit message: `feat: inventory the 2026 call safely`

## Task 4: Parse the Word register and match exactly 36 applicants

**Files:**

- Create: `app/importer/register.py`
- Create: `app/importer/match.py`
- Create: `app/importer/normalize.py`
- Create: `tests/test_register_parser.py`
- Create: `tests/test_applicant_matching.py`
- Create: `tests/fixtures/import/register.docx`

**Step 1: Write failing parser/matching tests**

Build a synthetic Word table with the same column topology as the approved register. Test 36-row cardinality, preserved blanks as `None`, integer parsing without coercing malformed values, ORCID normalization, URL validation, degree/gender source preservation, duplicate names, diacritics, folder-name variants, ambiguous matches, and refusal to guess.

**Step 2: Implement**

Parse the first matching table by its normalized header signature, not fixed table index. Map applicant, degree, age, academic age, optional gender, first-/last-author/total papers, h-index, total citations, ORCID, Google Scholar citations, and identity certainty. Treat the Word ages as imported source observations only; the portal's derived ages come from birth month/year and PhD date after confirmation.

Match each row to one folder using normalized exact candidate keys and a reviewed alias map. Any zero, multiple, or cross-row folder match is an import exception and prevents application creation. Do not use fuzzy matching to resolve a production identity automatically.

**Step 3: Verify**

Run `python -m pytest tests/test_register_parser.py tests/test_applicant_matching.py -q`.

Expected: all tests pass; ambiguity tests fail closed.

**Step 4: Reconcile production inputs without writing SQL**

Run the importer in `--plan-only` mode. Expected: exactly 36 proposed applications and exactly one folder per row, or a named exception report that must be resolved before continuation.

**Step 5: Commit**

Commit message: `feat: reconcile the 2026 applicant register`

## Task 5: Suggest classifications and require human approval

**Files:**

- Create: `app/importer/classify.py`
- Create: `app/documents/classification.py`
- Create: `tests/test_classification.py`
- Create: `docs/document-classification.md`

**Step 1: Write failing tests**

Cover recommendation/referee/reference-letter filename variants and extracted first-page text, applicant CV/publication/research-plan/cover-letter variants, uncertain documents, forwarded letters, applicant-named recommendation files, and misleading filenames. Assert that suggestions never set visibility, every imported item remains `UNREVIEWED`, and any recommendation signal is prominently recorded for internal review.

**Step 2: Implement**

Create deterministic, explainable suggestions with evidence codes; do not use a generative model. Suggestions identify likely document type and likely confidentiality but never authorize applicant visibility. A classification decision requires an administrator identity, timestamp, explicit class, and reason when overriding a recommendation signal. The database always prohibits `CONFIDENTIAL_RECOMMENDATION` from applicant projections.

**Step 3: Verify**

Run `python -m pytest tests/test_classification.py -q`.

Expected: all recommendation variants remain non-visible until and after their confidential decision.

**Step 4: Commit**

Commit message: `feat: add review-only document classification`

## Task 6: Implement idempotent import and exception reporting

**Files:**

- Create: `app/importer/run.py`
- Create: `app/importer/report.py`
- Create: `scripts/import-call-2026.ps1`
- Create: `scripts/verify-import-2026.ps1`
- Create: `tests/test_import_idempotency.py`
- Create: `tests/test_import_transactions.py`
- Create: `docs/import-2026.md`

**Step 1: Write failing integration tests**

Test a successful synthetic import, rerun with identical sources, added source occurrence, changed source bytes at the same relative path, database failure after object write, scan failure, unmatched folder, duplicate row, and partial import rollback. Require the same source manifest hash to return the same completed import run and create no duplicate applications or document versions.

**Step 2: Implement**

Use an import-run fingerprint over register bytes, normalized source manifest, importer version, and call identifier. Insert each applicant and its typed imported observations with provenance. Copy/validate/scan/encrypt each PDF and register every occurrence. Record but do not coerce non-PDF or unreadable files. Commit per applicant only after all its objects and metadata are consistent; mark the run incomplete until all 36 are committed and global reconciliation passes.

Generate an internal HTML/CSV exception report with counts and short internal IDs, but no raw document text. The `--apply` switch must be explicit; default is plan-only.

**Step 3: Verify with synthetic data**

Run `python -m pytest tests/test_import_idempotency.py tests/test_import_transactions.py -q`.

Expected: all tests pass and the second identical run creates zero new records.

**Step 4: Execute production import only after Plans 1–2 are deployed**

Run `scripts/import-call-2026.ps1 -PlanOnly`, review the manifest, then run with `-Apply` through the documented root-mediated ISAB01 ingestion path. Expected: 36 applications, all source occurrences accounted for, zero unmatched/duplicate application identities, and every imported document `UNREVIEWED`.

**Step 5: Verify**

Run `scripts/verify-import-2026.ps1`.

Expected: database/object hash agreement, source immutability, no applicant-visible document yet, and an explicit list of items requiring classification.

**Step 6: Commit**

Commit message: `feat: import 2026 applications idempotently`

## Task 7: Add authorized downloads and sanitized combined packages

**Files:**

- Create: `app/documents/access.py`
- Create: `app/documents/package.py`
- Create: `app/routes/documents.py`
- Create: `tests/test_document_authorization.py`
- Create: `tests/test_applicant_package.py`
- Create: `tests/test_download_audit.py`

**Step 1: Write confidentiality-first failing tests**

For two applicants, administrators, and trustees, test listing, direct-ID guessing, active/old versions, revoked sessions, guessed object keys, range requests, package generation, and audit. Include a recommendation uploaded under an applicant filename and prove it cannot be listed, counted, inferred by error difference, downloaded, or included in the package.

**Step 2: Implement**

Resolve applicant downloads only through the applicant-visible SQL projection bound to the authenticated application ID. Resolve internal downloads through a separate role-checked query. Use short-lived, single-purpose, session-bound download grants stored only as hashes. Decrypt only after authorization and audit-intent creation; record success/failure without file contents.

Generate a fresh combined PDF from approved current applicant-visible pages only. Copy page content into a new writer, discard source metadata, attachments, JavaScript/actions, hidden file names, and internal identifiers, and write generic package metadata. Refuse package generation if any selected version is unscanned, unreviewed, inactive, or non-visible.

**Step 3: Verify**

Run `python -m pytest tests/test_document_authorization.py tests/test_applicant_package.py tests/test_download_audit.py -q`.

Expected: all positive tests pass; every recommendation path returns the same neutral not-found result as an unknown object; package inspection finds only allowlisted pages and generic metadata.

**Step 4: Run the complete suite and commit**

Run `python -m pytest -q`.

Expected: all Plans 1–2 tests pass.

Commit message: `security: enforce applicant document confidentiality`
