# Codex coordination

## Repository state

- Repository: `aagaag/EHF-applications`
- Branch: `main`
- Bootstrap baseline: `7752e40b2126dd4b636f42e5e982537c79779b25`
- Current work: Foundation Task 4 complete; Task 5 secure HTTP runtime is next

## Working agreements

- Keep work on `main` and preserve the approved documents under `docs/superpowers/`.
- Record implementation handoffs here without personal data, credentials, access material, or applicant content.
- Run the focused test and then the full available test suite before the task commit.

## Handoff

Foundation Tasks 1–4 are complete. The repository now has a fail-closed typed configuration, immutable SQL migrations and validators, a least-privileged EHF SQL principal lifecycle, and disposable live verification for both the permission boundary and production user-mapping transaction. Exact commit `ae5436a` passed 165 local tests, the isolated ISAB01 verifier, the production-mapping harness, and independent security review; both live runs ended with zero test databases and zero test logins. Task 5 may add the secure HTTP runtime described in the approved foundation plan.
