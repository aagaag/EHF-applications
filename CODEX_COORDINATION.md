# Codex coordination

## Repository state

- Repository: `aagaag/EHF-applications`
- Branch: `main`
- Bootstrap baseline: `7752e40b2126dd4b636f42e5e982537c79779b25`
- Current work: Tasks 7–9 add atomic deployment, confidential document storage, and the reviewed 2026 import

## Working agreements

- Keep work on `main` and preserve the approved documents under `docs/superpowers/`.
- Record implementation handoffs here without personal data, credentials, access material, or applicant content.
- Run the focused test and then the full available test suite before the task commit.

## Handoff

Foundation Tasks 1–5 are complete. The repository now includes the accepted SQL foundation and a secure HTTP runtime with dependency-free liveness, bounded readiness, strict Host and request-framing validation, correlation IDs, redacted errors/logs, no-store caching, and browser security headers. Task 5 passed 193 local tests, 21 raw-ASGI adversarial probes, and independent specification/quality review with no findings. Task 6 adds the shared ISAB application shell and durable preferences described in the approved foundation plan.

Foundation Task 6 is complete. The inspectable applicant and development-only internal previews use the official ISAB logo and shared responsive shell. Internal navigation, Help, cards, and authorization pills derive from one fail-closed role inventory with the exact EHF Entra group names; trustee rendering omits administrator operations. Appearance preferences are identity-scoped and SQL-backed through a narrow read procedure without direct table access. The accepted correction passed 205 tests, five browser/accessibility scenarios, syntax checks, and independent final review with no findings.

Foundation Tasks 7–9 add an immutable `/opt/ehf/r/<40-hex-commit>` deployment path, an atomic `/opt/ehf/current` symlink, a locked loopback-only service, exact EHF Nginx site, encrypted PDF storage, immutable recommendation confidentiality, import provenance, and a root-mediated PlanOnly/Apply workflow for the 2026 legacy call. The importer reconciles 36 reviewed folder aliases, preserves all register observations, leaves every document `UNREVIEWED`, and cannot send mail or invitations. Applicant source files, identity maps, reports, call identifiers, and credentials remain outside Git. Deployment still keeps Cloudflare/DNS/Access unchanged and invitations/production mail false.

The 2026 authorization/report update renames the two canonical internal roles while preserving their Entra object IDs, adds administrator-first dual-membership coverage, removes only the redundant `Preview surface` card copy, and adds one-source responsive metrics, two plots, and an audited in-memory XLSX export. Microsoft Excel opened and rendered the three-sheet/two-chart workbook successfully. The first production attempt stopped safely before activation because SQL Server rejected the unquoted `rowCount` JSON alias in migration 010; the alias is now quoted and covered by a regression test. Pre-deployment verification passes 326 application tests, 33 deployment checks, 128 edge tests, the live Entra reconciliation postcondition, and the exact Cloudflare Access status. Applicant invitations and production mail remain disabled.

The internal report presentation now follows Workspaces directly, with the redundant Applications destination and card rows removed. Every report row opens a complete 13-field detail dialog on double-click or Enter/Space, restores focus on close, and renders missing values in bold red. The focused interaction/accessibility checks and the full 326-test suite pass; applicant invitations and production mail remain disabled.

Every Reports field title now has adjacent ascending and descending triangle controls. Text fields sort locale-aware, numeric fields sort numerically, missing values remain last in both directions, and the active column exposes its sort direction accessibly. Desktop and phone visual regression checks confirm that the controls reflow without horizontal overflow; applicant invitations and production mail remain disabled.
