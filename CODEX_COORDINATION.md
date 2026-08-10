# Codex coordination

## Repository state

- Repository: `aagaag/EHF-applications`
- Branch: `main`
- Bootstrap baseline: `7752e40b2126dd4b636f42e5e982537c79779b25`
- Current work: Foundation Task 5 complete; Task 6 shared ISAB shell is next

## Working agreements

- Keep work on `main` and preserve the approved documents under `docs/superpowers/`.
- Record implementation handoffs here without personal data, credentials, access material, or applicant content.
- Run the focused test and then the full available test suite before the task commit.

## Handoff

Foundation Tasks 1–5 are complete. The repository now includes the accepted SQL foundation and a secure HTTP runtime with dependency-free liveness, bounded readiness, strict Host and request-framing validation, correlation IDs, redacted errors/logs, no-store caching, and browser security headers. Task 5 passed 193 local tests, 21 raw-ASGI adversarial probes, and independent specification/quality review with no findings. Task 6 may add the shared ISAB application shell and durable preferences described in the approved foundation plan.
