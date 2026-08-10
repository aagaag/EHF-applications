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

The bootstrap does not import production records. Once the approved import workflow is present, preview an import before writing anything:

```powershell
$Python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python -m app.importer --source '<approved-source-directory>' --database EHFApplications --dry-run
```

Proceed only after the preview reconciles every expected applicant and document classification. The original source directory must remain unchanged; the importer must write only controlled application storage and an auditable result.

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
powershell -File scripts\deploy-isab01.ps1
powershell -File scripts\verify-isab01.ps1
```

If the post-activation health check fails, use the documented atomic rollback command after confirming the named previous release:

```powershell
powershell -File scripts\deploy-isab01.ps1 -Rollback
powershell -File scripts\verify-isab01.ps1
```

The deploy and rollback scripts are introduced by the foundation deployment task; until then, these commands are operational documentation rather than an enabled production path.

## Production invitation gate

Deployment and import never send applicant email. Production invitations stay disabled until all of the following are true:

1. Every imported applicant email address and every document classification has been reviewed.
2. Adriano Aguzzi has approved the exact sender identity and invitation message.
3. An internal delivery test has succeeded and its receipt is recorded.
4. Adriano Aguzzi has explicitly authorized production invitation sending after reviewing the final records and message.

Until that authorization is given, invitation and production-mail settings remain disabled. A test or deployment command must not enable them implicitly.
