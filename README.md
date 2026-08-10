# Ernst Hadorn Foundation Charles Weissmann Fellowships Portal

This repository contains the secure EHF fellowship portal planned for
`ehf.isab.science`. The approved design is the [EHF applications portal design](docs/superpowers/specs/2026-08-09-ehf-applications-portal-design.md).

## Local setup

Use Python 3.12 and the repository runtime explicitly on this machine:

```powershell
$Python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python -m pip install -r app\requirements.txt -r app\requirements-dev.txt
```

Do not place credentials, applicant documents, PDFs, or generated import output in Git. The repository ignore rules cover those paths and file types.

## Tests

Run the complete available suite from the repository root:

```powershell
$Python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python -m pytest -q
```

For the repository bootstrap contract only:

```powershell
$Python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python -m pytest tests\test_repository_contract.py -q
```

## Import

The root-mediated 2026 workflow is PlanOnly unless `-Apply` is explicit. It requires private reviewed identity and folder-alias maps outside Git, reconciles all 36 rows before writing, and preserves every register observation for later applicant confirmation. See [import-2026.md](docs/import-2026.md) for the exact commands.

Use the pinned local runtime for preparation and tests:

```powershell
$Python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python -m pytest tests\test_source_inventory.py tests\test_register_parser.py tests\test_applicant_matching.py -q
```

Imported PDFs are scanned and encrypted. Every document begins `UNREVIEWED`; recommendation signals also receive an immutable confidential recommendation link. Import and deployment never make a document applicant-visible and never send an invitation.

## Deploy and rollback

Deployment targets ISAB01 only after the release has passed its focused tests and the full suite on a clean, synchronized `main`:

```powershell
$Python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
git fetch origin
$Branch = git branch --show-current
if ($Branch -ne 'main') {
    throw "Expected active branch main; found '$Branch'."
}
$Status = git status --short
if ($Status) {
    throw "Expected clean working tree; git status --short returned:`n$Status"
}
Write-Host 'Expected: main branch and empty git status --short output.'
git diff --exit-code origin/main
& $Python -m pytest -q
powershell -NoProfile -File scripts\deploy-isab01.ps1 -WhatIf
```

Apply only after the reviewed commit has been pushed, local `HEAD` equals
`origin/main`, the ISAB01 non-secret configuration/credential prerequisites are
available, and the approved protected SQL administrator credential **path** is
known. The complete procedure is in [deployment.md](docs/deployment.md).

If the post-activation health check fails, the installer restores the previous
release automatically. A later explicit rollback requires the named, validated
previous release:

```powershell
$PreviousCommit = '<validated 40-hex previous commit>'
powershell -NoProfile -File scripts\deploy-isab01.ps1 -Rollback $PreviousCommit
powershell -NoProfile -File scripts\verify-isab01.ps1 -ExpectedCommit $PreviousCommit
```

The deployment path does not configure Cloudflare, DNS, Access, invitations,
production mail, applicant data, or outbound communications. Applicant data is
loaded only by the separate root-mediated import procedure.
It creates and checksum-migrates only the exact `EHFApplications` database when
it is absent; it never creates, imports, or modifies any other database.

## Production invitation gate

Deployment and import never send applicant email. Production invitations stay disabled until all of the following are true:

1. Every imported applicant email address and every document classification has been reviewed.
2. Adriano Aguzzi has approved the exact sender identity and invitation message.
3. An internal delivery test has succeeded and its receipt is recorded.
4. Adriano Aguzzi has explicitly authorized production invitation sending after reviewing the final records and message.

Until that authorization is given, invitation and production-mail settings remain disabled. A test or deployment command must not enable them implicitly.
