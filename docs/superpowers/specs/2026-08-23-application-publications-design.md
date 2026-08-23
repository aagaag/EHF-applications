# Application Publication Records Design

## Purpose

Add application-scoped publication records for the EHF 2026 fellowship call from the reviewed workbook and applicant dossiers. The import is additive: it creates missing records and fills blank canonical fields, but never replaces an existing non-blank value. Any disagreement is retained as an import exception for review.

The initial research manifest contains 36 applicants, 841 unique works, 883 source occurrences, and 2,523 citation-source observations. Google Scholar citation counts remain a manual review task because no supported bulk API is available. bioRxiv and medRxiv observations record source availability without inventing citation counts.

## Data Model

`dbo.ApplicationPublication` is the application-owned child table. Each row has a foreign key to `dbo.Application`, an import-run provenance key, a stable per-application identity hash, an optional normalized DOI, and the requested denormalized canonical fields: HTTP link, authors, title, journal, volume, pages, and publication year. A unique application/identity constraint prevents duplicate works, and a filtered application/DOI constraint prevents duplicate DOI rows for one applicant.

`dbo.ApplicationPublicationSourceOccurrence` is append-only evidence. It preserves every workbook or dossier citation occurrence, including its source type, locator, page, raw citation, and payload hash. Multiple occurrences can point to one canonical publication.

`dbo.PublicationMetadataObservation` is append-only source evidence for resolved metadata. It records the source, source identifier, the complete reviewed work-observation payload present in the import manifest, observation time, and payload hash without overwriting canonical values. Upstream API-response hashes remain bound inside that reviewed payload; raw third-party API envelopes are not required by this import contract.

`dbo.PublicationCitationObservation` is append-only citation-source evidence. Each record names Google Scholar, bioRxiv, or medRxiv and stores either a non-negative observed count or a status explaining why the count is absent. The initial Google Scholar status is `MANUAL_REQUIRED`; bioRxiv and medRxiv use evidence-backed availability statuses and null counts when the source does not publish a citation count.

All four tables are denied direct runtime DML and SELECT access. Administrative import code uses the existing privileged import lane. Append-only evidence tables reject updates and deletes. Canonical publication updates reject clearing or changing any non-null value while permitting a null value to be filled.

## Identity and Matching

Within one application, DOI-bearing works use SHA-256 over `doi\0` plus the lowercase normalized DOI. Works without a DOI use SHA-256 over `citation\0` plus a whitespace- and case-normalized representative citation. The importer first matches by normalized DOI, then by identity hash.

Applicants are resolved by exact full name within call `EHF-2026`; production identifiers are never hard-coded. Ambiguous or missing applicant matches fail before writes.

## Import Contract

The publication manifest is a separate, versioned import lane from the applicant-document importer. It is never committed because it contains applicant-derived material. A small PII-free fixture covers tests.

The importer strictly validates the manifest schema, self-hash, counts, uniqueness, foreign-key relationships, field types, citation-source coverage, and null initial citation counts. Unknown fields fail validation. Plan-only mode performs validation and emits the intended counts and conflicts without opening a database connection.

Apply mode fingerprints the original manifest bytes, reuses a completed identical import run, retries a failed identical run safely, and performs each applicant atomically. It inserts missing publications and evidence, fills only null canonical fields, and records non-blank discrepancies in `dbo.ImportException`. Reapplying the same manifest is idempotent.

## Manual Google Scholar Queue

The importer writes a CSV outside the repository with one row per publication. It contains applicant, stable work key, DOI, title, year, a Google Scholar title/DOI search URL, and blank reviewer fields for citation count, result URL, observation time, and reviewer. No automated Scholar scraping is used.

## Deployment and Verification

Migration `021` creates the schema and database validator `021` verifies keys, constraints, triggers, and permissions. Existing fixed migration and validator inventories advance from 20 to 21.

A PowerShell wrapper transfers exactly one validated manifest to a root-only staging file on ISAB01, runs plan or apply through the privileged import path, and removes the staging copy in a guaranteed cleanup path. A separate production verifier checks call/applicant coverage, publication/evidence counts, referential integrity, DOI uniqueness, citation statuses, import exceptions, and that invitation/mail activation remains disabled.

The final workflow uses one commit on `main` with subject `feat: add application publication records`, pushes that exact state, deploys it through the repository deployment script, applies the external manifest, generates the manual review CSV outside the repository, and verifies production.
