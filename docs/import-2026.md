# 2026 EHF import

The 2026 importer is deliberately PlanOnly by default. It does not send mail, create invitations, make a document applicant-visible, or write source material to Git. Every imported document version is `UNREVIEWED` until an administrator records a separate classification decision.

## Root-mediated ISAB01 path

Use a locally prepared source-package directory, a separate reviewed `identity-parts.json` file, and a reviewed `folder-aliases.json` file. The maps are required because the Word register has one full-name field and the legacy applicant folders do not consistently use full legal names. Keep both maps outside the repository. The helper `scripts\build-identity-map.py` uses the reviewed folder aliases to preserve compound family-name suffixes; the resulting fields remain provisional until each applicant explicitly confirms or corrects them. The identity map format is:

```json
{
  "Example Applicant": {"given_names": "Example", "family_name": "Applicant"}
}
```

The folder-alias map format is:

```json
{"call":"2026","aliases":{"Example Applicant":"Applicant"}}
```

After Plans 1–2 are deployed on ISAB01, create a non-writing reconciliation plan:

```powershell
powershell -NoProfile -File scripts\import-call-2026.ps1 `
  -SourcePackage 'C:\approved\call-2026' `
  -IdentityPartsPath 'C:\approved\identity-parts.json' `
  -FolderAliasesPath 'C:\approved\folder-aliases.json' `
  -CallId '<fellowship-call-guid>'
```

The script creates a temporary tar archive, transfers it into a unique mode-0700 directory below `/home/aag/.ehf-transfer`, verifies mode-0600 files, and asks ISAB01 root to extract it into a new mode-0700 `/root/ehf-import/call-2026.*` directory. The transfer and copied maps are removed after the operation. Nothing is committed or copied into Git.

Review the printed source-manifest hash, fingerprint, count of 36 planned applications, and the internal HTML/CSV exception report. The report contains only exception codes, counts, and short internal IDs; it contains no names, paths, document text, or raw hashes.

Only after that review, run the same command with `-Apply`. Apply uses the protected root-only SQL administrator credential path on ISAB01, validates/scans/encrypts PDFs, creates each applicant transaction only when all its metadata is consistent, and records every non-PDF or failed admission as a source occurrence requiring review.

```powershell
powershell -NoProfile -File scripts\import-call-2026.ps1 `
  -SourcePackage 'C:\approved\call-2026' `
  -IdentityPartsPath 'C:\approved\identity-parts.json' `
  -FolderAliasesPath 'C:\approved\folder-aliases.json' `
  -CallId '<fellowship-call-guid>' `
  -SqlAdminCredentialPath '/root/.config/finances2/sql-sa' `
  -Apply
```

Verify database/object agreement after Apply:

```powershell
powershell -NoProfile -File scripts\verify-import-2026.ps1 `
  -CallId '<fellowship-call-guid>' `
  -SqlAdminCredentialPath '/root/.config/finances2/sql-sa'
```

Expected result: 36 imported applications, all 162 source occurrences accounted for, eight reviewed call-level administrative exclusions, one explicitly recorded empty legacy PDF, every non-empty PDF admitted as `UNREVIEWED`, and zero applicant-visible documents. A failed run can be retried with the same fingerprint; a completed run is reused idempotently. Any unmatched folder, duplicate register row, non-empty admission failure, source inventory issue, or missing reviewed name part blocks completion.

## Publication records

Publication records use a separate manifest lane from the document import. The reviewed `publication-import-manifest.json` contains applicant-derived citations and must remain outside the repository. The initial accepted contract is exactly 36 applicants, 841 application publications, 883 dossier source occurrences, and 2,523 citation-source status observations.

Create a validation plan and a manual Google Scholar queue without database writes:

```powershell
powershell -NoProfile -File scripts\import-publications-2026.ps1 `
  -ManifestPath 'C:\approved\publication-import-manifest.json' `
  -ScholarQueuePath 'C:\Users\aag\Documents\ChatGPT\EHF-pubs\google-scholar-review.csv'
```

The helper transfers only the manifest into unique mode-0700 staging directories, verifies mode-0600 files, validates the manifest self-hash and exact relationships, writes the queue outside Git, and removes both transfer and root staging data. The queue contains one row per paper and blank fields for the manual Google Scholar citation count, result URL, observation time, and reviewer. It does not scrape Google Scholar.

After the plan succeeds, apply the identical manifest through the protected root SQL path:

```powershell
powershell -NoProfile -File scripts\import-publications-2026.ps1 `
  -ManifestPath 'C:\approved\publication-import-manifest.json' `
  -ScholarQueuePath 'C:\Users\aag\Documents\ChatGPT\EHF-pubs\google-scholar-review.csv' `
  -SqlAdminCredentialPath '/root/.config/finances2/sql-sa' `
  -Apply
```

The importer creates missing publication rows, fills only null canonical fields, preserves every non-null database value, and hashes each discrepancy into `ImportException`. Reapplying identical completed input is a no-op. Verify the deployed result with:

```powershell
powershell -NoProfile -File scripts\verify-publications-2026.ps1 `
  -SqlAdminCredentialPath '/root/.config/finances2/sql-sa'
```

Google Scholar review remains manual. bioRxiv and medRxiv statuses retain null counts when those services do not expose a citation count; Crossref metadata must never be substituted for a requested-source citation count.
