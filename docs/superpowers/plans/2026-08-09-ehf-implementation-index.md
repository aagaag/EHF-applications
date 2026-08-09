# EHF Fellowship Portal Implementation Plan Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Deliver the approved Ernst Hadorn Foundation Charles Weissmann Fellowships portal at `ehf.isab.science` without exposing confidential recommendations or sending a production applicant email before Adriano Aguzzi's final authorization.

**Architecture:** A dedicated FastAPI application runs on ISAB01 behind Nginx and the existing outbound-only Cloudflare Tunnel. It uses a separate `EHFApplications` database in the local Microsoft SQL Server and an application-encrypted, append-only PDF object store. Applicant routes use opaque invitation tokens plus email OTP; internal routes use Cloudflare Access, ISAB Entra identities, and EHF-specific group authorization. All authoritative mutations are transactional and audited.

**Tech Stack:** Python 3.12, FastAPI/Uvicorn, Microsoft ODBC Driver 18 and `pyodbc`, SQL Server, plain progressive-enhancement HTML/CSS/JavaScript, `pypdf`, `cryptography`, `openpyxl`, ClamAV, Nginx, systemd, Cloudflare Tunnel/Access/Turnstile/WAF, pytest, and Microsoft Playwright for end-to-end browser tests.

**Global Constraints:** Work only on each repository's GitHub default `main` branch; stop on local/GitHub conflicts; preserve the approved specification; use the F2 `WEB_HANDBOOK.md` and current dashboard group-pill implementation as the ISAB interface authority; deny access by default; keep EHF data isolated from every other ISAB database and service; never expose a recommendation to an applicant; never modify the 2026 source directory; and keep production invitation sending disabled until Adriano Aguzzi gives a separate final authorization after reviewing the imported records and message.

## Execution order

Implement these plans in order. A later plan may begin only after the dependency named below is committed, pushed, and verified.

| Order | Plan | Outcome | Dependency |
| --- | --- | --- | --- |
| 1 | [Foundation and runtime](2026-08-09-ehf-foundation-runtime.md) | Tested application skeleton, SQL boundary, audit model, ISAB shell, and atomic ISAB01 deployment | Approved design |
| 2 | [2026 import and document security](2026-08-09-ehf-import-documents.md) | Idempotent 36-record import, encrypted immutable files, classification review, safe downloads, and applicant-only PDF packages | Plan 1 |
| 3 | [Internal administration portal](2026-08-09-ehf-internal-portal.md) | EHF Entra roles, read-only trustee experience, operational admin table, reports, exports, and communication previews | Plans 1–2 |
| 4 | [Applicant review portal](2026-08-09-ehf-applicant-portal.md) | Token-plus-OTP access, complete review/correction/confirmation workflow, controlled uploads, and final submission | Plans 1–3 |
| 5 | [Production security and rollout](2026-08-09-ehf-production-rollout.md) | Cloudflare controls, backups, recovery, onboarding, synthetic pilot, 36-record reconciliation, and gated production activation | Plans 1–4 |

## Shared repository layout

The plans use this stable layout in `aagaag/EHF-applications`:

```text
app/                    FastAPI application and pinned requirements
database/migrations/    Ordered, idempotent SQL Server migrations
database/tests/         SQL permission and invariant tests
docs/                   Architecture, permissions, operations, privacy, and plans
infra/                  Nginx, systemd, SQL-login, backup, and install definitions
public/                 Shared ISAB shell, page entry points, CSS, JavaScript, logo
scripts/                Local and ISAB01 deployment/import/verification commands
tests/                  Python, contract, security, accessibility, and browser tests
```

The Cloudflare hostname and authorization inventory remains owned by `aagaag/isab-cloudflare-edge`; Plan 5 names each required cross-repository file.

## Cross-plan acceptance gates

Each plan must satisfy all of the following before its completion commit:

1. Run its focused tests first, then the complete repository test suite.
2. Confirm no source, fixture, log, snapshot, or test report contains a real applicant document, OTP, invitation token, secret, or recommendation text.
3. Confirm every database mutation uses a stored procedure or narrowly granted object and commits before success is shown.
4. Confirm every protected response sends `Cache-Control: private, no-store` and appropriate security headers.
5. Confirm whole-card and whole-row controls, keyboard behavior, 44-pixel targets, 94% content width, narrow-card reflow, four skins, reduced motion, and no horizontal overflow.
6. Stage only the files belonging to the completed task, commit them to `main`, push, and verify GitHub `origin/main` contains the exact commit.
7. Record deployment or handoff state in `CODEX_COORDINATION.md` without personal data or secrets.

## Production stop conditions

Stop without enabling real invitations if any of these remains true:

- a document classification is unreviewed;
- an applicant email is unreviewed;
- any applicant authorization or recommendation-confidentiality negative test fails;
- SQL and file backup restore has not passed in an isolated recovery location;
- the Foundation-approved sender identity is absent;
- the internal delivery test has not passed; or
- Adriano Aguzzi has not explicitly authorized production applicant invitations after final review.
