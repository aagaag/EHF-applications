# EHF Production Security and Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Put the completed portal into production at `ehf.isab.science` with path-correct Cloudflare protection, EHF-specific internal identities, coordinated SQL/document backups, monitoring, a synthetic pilot, reconciled 2026 records, and an explicit final gate before any real applicant invitation is sent.

**Architecture:** The existing `isab-dev` Cloudflare Tunnel publishes one proxied DNS hostname and sends traffic to the ISAB01 Nginx virtual host; no inbound Internet route reaches ISAB01. Exact `/internal/*` and `/api/internal/*` destinations use Cloudflare Access with the two active EHF groups. Applicant routes remain reachable without Entra but are protected by WAF, bot controls, Turnstile, edge rate limits, and matching origin limits. The app still enforces all identity/authorization. Immutable document objects and SQL are backed up under one application snapshot manifest and restored together in an isolated network.

**Tech Stack:** `aagaag/EHF-applications`, `aagaag/isab-cloudflare-edge`, Cloudflare API/Tunnel/Access/Turnstile/WAF/rate limiting, Microsoft Entra/Graph, SQL Server backups, Synology Active Backup, Hyper-V checkpoints, systemd, Nginx, Icinga-compatible health monitoring, pytest, Playwright, and PowerShell/Python verification scripts.

**Global Constraints:** Plans 1–4 must be complete; all work uses clean synchronized `main` branches in the owning repositories; Cloudflare is configured through reviewed idempotent API scripts; the public hostname must not be routed through a broad shared Worker that bypasses application authorization; internal Access and applicant public paths must not overlap incorrectly; no origin-bypass route is permitted; real applicant records never enter synthetic tests; selection committee remains unassigned; backups must restore both SQL and every referenced encrypted object; and no production applicant email is sent without Adriano Aguzzi's separate final authorization.

## Task 1: Add the EHF hostname to the authoritative Cloudflare repository

**Repositories and files:**

- In `aagaag/isab-cloudflare-edge`, create: `scripts/ehf-tunnel.py`
- In `aagaag/isab-cloudflare-edge`, create: `scripts/ehf-tunnel.test.py`
- In `aagaag/isab-cloudflare-edge`, create: `scripts/deploy-ehf-tunnel.ps1`
- In `aagaag/isab-cloudflare-edge`, create: `scripts/sync-ehf-dns.mjs`
- In `aagaag/isab-cloudflare-edge`, create: `scripts/sync-ehf-dns.test.mjs`
- In `aagaag/isab-cloudflare-edge`, modify: `docs/HOSTNAME_INVENTORY.md`
- In `aagaag/isab-cloudflare-edge`, modify: `docs/DEPLOYMENT_OWNERSHIP.md`
- In `aagaag/isab-cloudflare-edge`, modify: `docs/OPERATING_MODEL.md`
- In `aagaag/isab-cloudflare-edge`, modify: `CODEX_COORDINATION.md`
- In `aagaag/EHF-applications`, create: `docs/cloudflare.md`

**Step 1: Verify both repository baselines**

Fetch both remotes. Confirm each checkout is on GitHub's default `main`, clean, and equal to `origin/main`. If not, stop and report the conflict before editing.

**Step 2: Write failing DNS/tunnel tests**

Require exactly one proxied `ehf.isab.science` CNAME to the existing `isab-dev` tunnel, one tunnel ingress rule to `http://10.10.20.29:80` with the EHF host header, correct rule order before the catch-all, and no A/AAAA origin record. Reject duplicate hostname rules, wrong origin, unproxied DNS, Worker proxying, and broad origin reachability.

**Step 3: Implement idempotent API-backed configuration**

Follow the current Events/Finances 2 script patterns. Read Cloudflare credentials only through the repository's approved protected path. Plan mode prints bounded non-secret changes; apply mode creates/reconciles exact DNS and tunnel ingress and re-reads live state for verification.

**Step 4: Test and commit the edge changes**

Run the new Python/Node tests and `npm run check:auth-policy`.

Expected: exact EHF route passes; existing hostname policies remain unchanged.

Commit message in the edge repository: `feat: register the EHF applications hostname`

Push edge `main`; do not apply live DNS yet.

## Task 2: Configure path-specific Cloudflare Access for internal users

**Repositories and files:**

- In `aagaag/isab-cloudflare-edge`, create: `scripts/configure-ehf-access.mjs`
- In `aagaag/isab-cloudflare-edge`, create: `scripts/configure-ehf-access.test.mjs`
- In `aagaag/isab-cloudflare-edge`, modify: `scripts/verify-auth-policy.mjs`
- In `aagaag/isab-cloudflare-edge`, modify: `docs/HOSTNAME_INVENTORY.md`
- In `aagaag/isab-cloudflare-edge`, modify: `CODEX_COORDINATION.md`
- In `aagaag/EHF-applications`, modify: `docs/permissions.md`

**Step 1: Write failing overlap and membership tests**

Require exact self-hosted Access destinations for `ehf.isab.science/internal/*` and `ehf.isab.science/api/internal/*`; one reusable `ehf-applications-authorized-users` Access group containing only the exact Entra group IDs from `infra/identity/ehf-identity.json`; and no exact-email/domain/general-ISAB-group exception. Require applicant/static/health routes not to be captured by the internal app. Reject any unmanaged overlapping Access application.

**Step 2: Implement fail-closed reconciliation**

Create/reconcile the Access group and two path applications, verify distinct expected audiences where applicable, and output the audience values into the deployment's non-secret identity manifest. Keep session duration bounded and require the configured Entra identity provider. Do not assign `EHF-Applications-Selection-Committee`.

**Step 3: Verify and commit**

Run `node --test scripts/configure-ehf-access.test.mjs` and `npm run check:auth-policy`.

Expected: intended groups pass; administrator/trustee negative siblings and selection committee fail; applicant paths remain outside Access.

Commit message in edge repository: `security: protect EHF internal routes`

Push `main`; application code must be deployed and validating the new audience before live Access apply.

## Task 3: Configure WAF, Turnstile, bot, and edge rate limits

**Repositories and files:**

- In `aagaag/isab-cloudflare-edge`, create: `scripts/configure-ehf-security.mjs`
- In `aagaag/isab-cloudflare-edge`, create: `scripts/configure-ehf-security.test.mjs`
- In `aagaag/isab-cloudflare-edge`, modify: `docs/HOSTNAME_INVENTORY.md`
- In `aagaag/EHF-applications`, create: `tests/security/test_edge_contract.py`
- In `aagaag/EHF-applications`, modify: `docs/cloudflare.md`

**Step 1: Write failing security-policy tests**

Require managed WAF rules, DDoS/proxy status, challenge rules for suspicious applicant authentication/form traffic, strict rate limits for code requests, OTP verification, downloads, uploads, and a broader host-level ceiling. Require a Turnstile widget/secret pair scoped to the EHF hostname and origin-side token verification. Reject rules that cache personal pages, expose the origin, bypass internal Access, or challenge static accessibility assets indiscriminately.

**Step 2: Implement idempotent rules**

Use named EHF rules with exact expressions and explicit precedence. Keep thresholds in checked-in non-secret policy constants and matching origin limits; never store the Turnstile secret in Git. Provision the secret through a systemd credential. Ensure Cloudflare failure or Turnstile verification failure denies the sensitive action without revealing account existence.

**Step 3: Verify and commit**

Run the security script tests and application edge-contract tests.

Expected: synthetic valid flow passes; threshold violations return `429`/challenge; origin-side limits still work with direct local requests; internal routes demand Access.

Commit message in edge repository: `security: harden EHF public entry points`

## Task 4: Add coordinated backup, integrity verification, and isolated restore

**Files:**

- Create: `database/migrations/016_backup_history.sql`
- Create: `database/tests/016_validate_backup_history.sql`
- Create: `app/operations/backup_manifest.py`
- Create: `infra/ehf-backup.service`
- Create: `infra/ehf-backup.timer`
- Create: `infra/ehf-backup-verify.service`
- Create: `infra/ehf-backup-verify.timer`
- Create: `scripts/backup-ehf.sh`
- Create: `scripts/verify-backup-ehf.sh`
- Create: `scripts/restore-test-ehf.sh`
- Create: `tests/test_backup_manifest.py`
- Create: `tests/test_restore_contract.py`
- Create: `docs/backup-recovery.md`

**Step 1: Write failing consistency tests**

Require one snapshot ID to bind SQL backup metadata, schema migration level, every referenced encrypted object key/ciphertext hash, object count/bytes, backup start/end, and verification result. Test missing/extra/corrupt objects, incomplete SQL backup, changed keyring version, interrupted run, retention, and restore to the wrong/broad path.

**Step 2: Implement safe backup**

Because document versions are immutable, take a SQL application lock for snapshot cut, record the current object high-water mark, release the lock, copy exactly the immutable object set and keyring escrow under the existing protected backup authority, then create/verify the SQL full backup and signed/checksummed manifest. A completed snapshot is published only after all hashes verify. Never put key material in the manifest or normal backup log.

Schedule a daily backup and daily integrity verification. Integrate the EHF database, `/var/lib/ehf/o`, and protected key escrow into the existing ISAB01/Synology/Hyper-V protection while documenting that checkpoints are not independent backups.

**Step 3: Implement isolated restore**

Restore only to an explicitly named `EHFApplications_RestoreTest_${date}` database and a newly created short temporary object root. Validate containment before any cleanup. Start the restored app on loopback with production mail/invitations disabled and no production network route. Verify database constraints and decrypt/hash every object, then remove only the verified isolated targets.

**Step 4: Verify**

Run unit tests, one full backup, and one isolated restore test.

Expected: all SQL rows and object hashes reconcile; no production state changes; restore evidence is recorded without applicant content.

**Step 5: Commit**

Commit message: `feat: add coordinated EHF backup and recovery`

## Task 5: Add monitoring, privacy-safe logging, and operational alerts

**Files:**

- Create: `app/operations/health.py`
- Create: `app/operations/alerts.py`
- Create: `infra/ehf-monitor.service`
- Create: `infra/ehf-monitor.timer`
- Create: `tests/test_monitoring.py`
- Create: `tests/test_log_redaction.py`
- Create: `docs/monitoring.md`
- Create: `docs/privacy-and-retention.md`

**Step 1: Write failing tests**

Cover app/database/object store/ClamAV/tunnel reachability, backup freshness, disk capacity, failed authentication bursts, upload rejection bursts, failed mail delivery, certificate/secret/key expiry metadata, and authorization failures. Assert alerts contain counts and opaque event IDs only—no applicant name/email, token, code, filename, document content, contribution text, or recommendation status.

**Step 2: Implement**

Publish personal-data-free liveness/readiness and a protected administrator health view. Send operational alerts only through a separately configured administrator channel after an internal test; otherwise record visible dashboard alerts. Retain structured security/audit events per the approved policy and keep raw access logs minimized/redacted. Do not implement destruction until a retention schedule is separately approved; preserve the schema's future anonymization/destruction capability.

**Step 3: Verify and commit**

Run `python -m pytest tests/test_monitoring.py tests/test_log_redaction.py -q`.

Expected: simulated failures are visible and privacy-safe; healthy state is explicit.

Commit message: `feat: monitor EHF portal operations`

## Task 6: Complete independent security, accessibility, and responsive acceptance tests

**Files:**

- Create: `tests/security/test_permission_matrix.py`
- Create: `tests/security/test_confidentiality_matrix.py`
- Create: `tests/security/test_session_attacks.py`
- Create: `tests/security/test_upload_attacks.py`
- Create: `tests/browser/accessibility.spec.py`
- Create: `tests/browser/responsive.spec.py`
- Create: `tests/browser/complete_workflows.spec.py`
- Create: `scripts/run-acceptance.ps1`
- Create: `docs/acceptance-evidence.md`

**Step 1: Build a synthetic zebra dataset**

Create exactly synthetic records that deliberately vary names/lengths/scripts, missing fields, zero/high citations, birth months, PhD dates, optional gender values, document completeness, recommendation arrival paths, versions, stale sessions, role memberships, and row versions. Clearly mark all records `SYNTHETIC`; use generated PDFs with no real source text.

**Step 2: Run the complete security matrix**

Test applicants A/B, Adriano-equivalent admin, Margaryta-equivalent admin, Ricky-equivalent trustee, Magda-equivalent trustee, selection committee, expired guest, unauthenticated user, and direct origin caller. Exercise every route and object type. Recommendation tests include applicant-uploaded/forwarded letters and guessed IDs/URLs/packages.

**Step 3: Run UI/accessibility/responsive tests**

Test keyboard-only navigation, focus order/return, labels, dialogs/drawer/Escape, live regions, chart alternatives, four skins, inversion, high contrast, reduced motion, 200% zoom, long labels, empty/error/loading/locked states, and 1440×900, 1024×768, 720×900, 390×844. Verify 3% margins and no unintended horizontal overflow.

**Step 4: Run**

Run `powershell -File scripts/run-acceptance.ps1 -Dataset Zebra`.

Expected: all tests pass; report contains counts, test IDs, screenshots of synthetic data only, and no secrets.

**Step 5: Commit**

Commit message: `test: prove EHF security and accessibility`

## Task 7: Deploy, activate edge protection, and run the synthetic pilot

**Files:**

- Create: `scripts/pilot.ps1`
- Create: `scripts/verify-production.ps1`
- Modify: `CODEX_COORDINATION.md`
- Modify: `docs/deployment.md`

**Step 1: Deploy application with all external communication disabled**

Deploy exact clean `origin/main` to ISAB01 with `INVITATIONS_ENABLED=false` and `PRODUCTION_MAIL_ENABLED=false`. Verify systemd, Nginx, SQL permission denials, ClamAV, storage, and readiness.

**Step 2: Apply live Cloudflare configuration**

From clean `isab-cloudflare-edge/main`, apply Access, security, DNS, and tunnel scripts in that order. Re-read live Cloudflare state after every apply. Confirm the origin has no public inbound route and direct IP/alternate Host requests fail.

**Step 3: Run the synthetic pilot**

Use non-production email sink identities and the zebra dataset. Exercise both administrator roles, both trustee roles, two applicants, classifications, corrections, uploads, packages, exports, plots, lock/reopen, revocation, and backup/restore. Do not use a real applicant address or document.

**Step 4: Verify production path**

Run `powershell -File scripts/verify-production.ps1 -SyntheticOnly`.

Expected: `ehf.isab.science` is healthy through Cloudflare; internal paths require exact groups; applicant paths require token+OTP; WAF/rate limits/Turnstile work; all synthetic workflows pass; sending remains disabled.

**Step 5: Commit**

Commit message: `ops: record the EHF synthetic pilot`

## Task 8: Reconcile the 36 production records and complete manual review

**Files:**

- Create: `scripts/reconcile-call-2026.ps1`
- Create: `docs/call-2026-release-checklist.md`
- Modify: `CODEX_COORDINATION.md`

**Step 1: Run automated reconciliation**

Verify exactly 36 applications, one source folder per register row, every source occurrence registered, every object hash valid, missing register values preserved as missing, and all table/plot calculations reproducible. Compare exported metrics with the approved Word source while recognizing that newly applicant-confirmed values remain separately versioned.

**Step 2: Complete administrator review**

Adriano Aguzzi or Margaryta Schaltegger reviews every registered applicant email and every document classification in the internal portal. The pre-invitation database gate must report zero unreviewed emails, zero unreviewed documents, zero unresolved import identity errors, and zero applicant-visible recommendations.

**Step 3: Verify trustees and revocation**

Confirm Ricky Weissman and Magda Polymenidou can read/export but cannot mutate or communicate. Remove a synthetic trustee from the group and confirm immediate revocation. Confirm selection committee remains denied.

**Step 4: Record release evidence**

Store only counts, stable internal event IDs, timestamps, commit IDs, and pass/fail results in the checklist. Do not store applicant names, emails, filenames, or document content in Git.

**Step 5: Commit**

Commit message: `ops: reconcile the 2026 EHF call`

## Task 9: Configure and test the approved mail sender without contacting applicants

**Files:**

- Create: `app/communications/graph.py`
- Create: `app/communications/worker.py`
- Create: `infra/ehf-mail-worker.service`
- Create: `infra/ehf-mail-worker.timer`
- Create: `tests/test_graph_mail.py`
- Create: `tests/test_mail_worker.py`
- Create: `scripts/test-mail.ps1`
- Modify: `docs/identity-onboarding.md`

**Step 1: Write failing transport tests**

Test HTML and text parts, exact sender/recipient/subject/body/link, generated-by footer, no tokens in logs, provider success/retry/permanent failure, idempotency, trustee denial, worker credential isolation, and disabled flags. Assert the web process has no Graph credential and only the locked mail worker can claim ready messages.

**Step 2: Implement a least-privileged mail adapter**

After Adriano Aguzzi approves the exact Foundation sender identity, create a dedicated certificate-backed Graph application with the narrowest mailbox-scoped `Mail.Send` permission available. Use the existing Graph/broker policy rather than exposing a secret. Render the personalized URL only inside the worker, send HTML by default with a plain-text alternative and required host footer, and record only provider message ID/status/time.

**Step 3: Send one internal test only**

Keep `INVITATIONS_ENABLED=false`. Use `scripts/test-mail.ps1` to send one clearly marked synthetic invitation to Adriano Aguzzi's reviewed internal address. This is not an applicant email. Check delivery, HTML/link rendering, sender alignment, SPF/DKIM/DMARC result, and footer. Store the non-secret delivery receipt ID in the release gate.

**Step 4: Verify**

Run mail tests and the full suite. Expected: test delivered once, no applicant outbox item is claimable, no credential/token logged.

**Step 5: Commit**

Commit message: `feat: add approved EHF mail delivery`

## Task 10: Final invitation gate and explicit handoff

**Files:**

- Create: `database/migrations/017_release_gate.sql`
- Create: `database/tests/017_validate_release_gate.sql`
- Create: `scripts/prepare-invitations.ps1`
- Create: `scripts/enable-invitations.ps1`
- Modify: `docs/call-2026-release-checklist.md`

**Step 1: Implement the database-backed gate**

Require: approved sender; internal delivery receipt; successful current backup/restore; successful acceptance run against the deployed commit; 36 reconciled applications; every email reviewed; every classification reviewed; zero visible recommendations; valid deadlines; and an explicit approval event naming Adriano Aguzzi. No environment flag alone can bypass this procedure.

**Step 2: Prepare but do not send**

Run `scripts/prepare-invitations.ps1`. It generates 36 administrator-review previews and hashed invitation records, but sends nothing. Adriano Aguzzi reviews recipient/sender/subject/HTML/link/deadline and the release checklist.

**Step 3: Stop for explicit authorization**

Report that the portal is ready and ask Adriano Aguzzi to authorize production invitation sending explicitly. Do not infer approval from design approval, implementation approval, prior mail tests, or the word `approved` given earlier in the project.

**Step 4: Enable only after that separate authorization**

After explicit authorization, copy the exact release-gate ID printed by `scripts/prepare-invitations.ps1`, record the approval event, and pass that value to `scripts/enable-invitations.ps1 -ReleaseGateId`. The script enables worker claiming for the reviewed invitation batch only; it does not broaden future-call or arbitrary-message authorization.

**Step 5: Verify delivery and retain safe rollback**

Monitor delivery status and retries, disable the batch on systematic failure, and never invalidate successful applicant tokens during an application rollback. Verify one-time use, expiry, and administrator-visible outcomes without logging links/codes.

**Step 6: Commit final non-personal evidence**

Commit message: `ops: activate the approved 2026 invitation batch`

Push `main`, verify GitHub and deployed commit equality, and update `CODEX_COORDINATION.md` with counts/status only.
