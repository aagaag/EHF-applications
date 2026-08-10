# Codex coordination

## Repository state

- Repository: `aagaag/EHF-applications`
- Branch: `main`
- Bootstrap baseline: `7752e40b2126dd4b636f42e5e982537c79779b25`
- Current work: Foundation Task 6 complete; Task 7 atomic ISAB01 deployment is next

## Working agreements

- Keep work on `main` and preserve the approved documents under `docs/superpowers/`.
- Record implementation handoffs here without personal data, credentials, access material, or applicant content.
- Run the focused test and then the full available test suite before the task commit.

## Handoff

Foundation Tasks 1–5 are complete. The repository now includes the accepted SQL foundation and a secure HTTP runtime with dependency-free liveness, bounded readiness, strict Host and request-framing validation, correlation IDs, redacted errors/logs, no-store caching, and browser security headers. Task 5 passed 193 local tests, 21 raw-ASGI adversarial probes, and independent specification/quality review with no findings. Task 6 adds the shared ISAB application shell and durable preferences described in the approved foundation plan.

Foundation Task 6 is complete. The inspectable applicant and development-only internal previews use the official ISAB logo and shared responsive shell. Internal navigation, Help, cards, and authorization pills derive from one fail-closed role inventory with the exact EHF Entra group names; trustee rendering omits administrator operations. Appearance preferences are identity-scoped and SQL-backed through a narrow read procedure without direct table access. The accepted correction passed 205 tests, five browser/accessibility scenarios, syntax checks, and independent final review with no findings. Task 7 may add the atomic ISAB01 deployment and rollback path while keeping invitations and production mail disabled.
