# EHF Multi-Call Implementation Plan Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement these plans task-by-task. The primary agent may delegate only the explicitly marked low-risk one- or two-file steps to `low_cost_worker` and remains responsible for integration, security, deployment, and verification.

**Goal:** Convert the deployed single-call EHF portal into one database-backed, call-scoped platform supporting independent applicant pools and independently configured shortlister rosters without changing the current `EHF-2026` results.

**Architecture:** A typed `CallContext` is resolved from every canonical URL and passed through authorization, repositories, and SQL procedures. Additive SQL migrations introduce call ownership, group grants, applicant/session binding, and dynamic shortlister rosters while explicit `EHF-2026` compatibility wrappers preserve rollback. Shared analysis, plotting, import, and export code operates only on the selected call.

**Tech Stack:** Python 3.12, FastAPI/Uvicorn, SQL Server 2025, `pyodbc`, plain HTML/CSS/JavaScript, `openpyxl`, PowerShell, pytest, Playwright-style browser scenarios, Nginx, systemd, and the existing immutable Hestia deployment workflow.

**Spec:** `docs/superpowers/specs/2026-09-21-ehf-multi-call-architecture-design.md`

## Global Constraints

- Work directly on synchronized GitHub `main`; do not create a branch or worktree.
- Before every task, fetch `origin/main`, require an empty worktree, and require local `HEAD == origin/main`.
- Use `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe` for Python.
- Use test-driven development: write the narrowest behavior test, run it red, implement the minimum, then run focused and full suites.
- Keep all runtime and development dependencies exactly pinned; add no dependency unless the approved design cannot be implemented without it.
- Preserve every existing migration and approved specification byte-for-byte except the already approved status update in the multi-call specification.
- Keep one service and one `EHFApplications` database; do not create a per-call database, deployment, or document root.
- Preserve every `EHF-2026` identifier, document key/hash, import record, analysis result, A/B/C shortlist group, and audit event.
- Require explicit call context at every call-owned boundary; never infer a default from an application ID, email address, Entra identity, or first database row.
- Preserve owner-only shortlist editing even for administrators.
- Keep production invitations and production mail disabled throughout implementation and deployment.
- Keep schema changes expand-compatible until a later separately reviewed cleanup; the previous application release must remain a valid rollback target.

## Review Focus

1. A valid application or document ID presented under the wrong call slug must produce the same neutral unavailable response as a missing object; Plans 2 and 3 add route and SQL tests.
2. One Entra object mapped to applications in two calls must resolve only through the requested call and must fail when no call is supplied; Plan 2 adds repository and route tests.
3. An administrator who is not the roster owner must be unable to change another shortlister's A/B/C group; Plan 3 tests route and SQL enforcement.
4. Migration and compatibility work must preserve the complete `EHF-2026` baseline, including migration-038 shortlist groups; Plans 1, 3, and 4 add parity checks.
5. Archived, selection-locked, inactive-roster, incomplete-analysis, and failed-export states must reject writes without partial mutation; Plans 1, 3, and 4 pin these failure paths.

---

## Execution order

Execute and review the plans in this order. A later plan starts only after the preceding plan's focused and full tests pass and its commit is pushed to `origin/main`.

| Order | Plan | Independently testable outcome | Depends on |
| --- | --- | --- | --- |
| 1 | [Call tenancy foundation](2026-09-22-ehf-multi-call-foundation.md) | Migration 040, call registry/grants, typed resolver, and administrator call inventory/create flow | Approved spec and migration 039 |
| 2 | [Call-scoped access](2026-09-22-ehf-multi-call-access.md) | Migration 041, call-bound applicant identity/session/access and neutral cross-call object authorization | Plan 1 |
| 3 | [Reports and shortlisting](2026-09-22-ehf-multi-call-reports-shortlist.md) | Migration 042, call-scoped metrics/exports, dynamic per-call roster, owner-only A/B/C editing, and responsive UI | Plans 1-2 |
| 4 | [Operations and production rollout](2026-09-22-ehf-multi-call-operations-rollout.md) | Generic imports/verifiers, two-call acceptance, parity proof, pushed release, production migration, and live verification | Plans 1-3 |

## Coordination and delegation

The primary agent owns migrations 040-042, authorization, authentication, cross-call object checks, integration commits, production deployment, rollback, and live verification.

Only steps explicitly labelled **Low-cost eligible** may be delegated. A delegated worker receives exclusive ownership of the named one or two files, is told that other agents share the repository, and must stop if the work expands beyond the supplied interface. The primary agent reviews every patch and reruns the relevant verification.

Permitted low-cost work after its dependency is stable:

- focused unit or browser tests in one named test file;
- a CSS-only responsive pass against fixed generated markup;
- one generic PowerShell wrapper plus its focused contract test; or
- call-derived copy replacement in one renderer or template.

Schema, SQL authorization, session/token handling, Entra mapping, roster ownership, deployment, and production verification are never delegated to a low-cost worker.

## Cross-plan completion gate

Before production deployment:

1. Run every focused command named in all four plans.
2. Run the complete Python suite with the explicit runtime.
3. Run all browser scenarios and JavaScript syntax checks.
4. Run the isolated SQL migration/validator workflow and deployment contract suite.
5. Run `scripts\deploy-ehf.ps1 -WhatIf` from a clean synchronized commit.
6. Push the exact commit and re-fetch to prove `HEAD == origin/main`.
7. Deploy through `ehf-hestia` with the protected SQL administrator credential path, never a secret value.
8. Run the live verifier against the exact 40-hex commit and record non-personal evidence in `CODEX_COORDINATION.md`.
9. Confirm applicant invitations and production mail remain disabled.
