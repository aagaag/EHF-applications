# Codex session history — ehf-applications

> Source: 92 archived Codex sessions, 2026-08-09 → 2026-08-24. Generated from the session archive on 2026-09-17. GitHub remains the source of truth; items marked superseded may no longer apply.
> Full session transcripts for this history live in the local Codex-session archive (`threads/ehf-applications/...`), searchable from Hermes via the `codex-session-archive` skill.

## Overview
EHF-applications is the Charles Weissmann (Ernst Hadorn) Foundation fellowship portal for ISAB: a FastAPI app served loopback-only by Uvicorn on ISAB01, fronted by Nginx and Cloudflare Access/Tunnel, backed by SQL Server database `EHFApplications` with a least-privileged `ehf_app` login. These sessions built the foundation (repo/coordination contract, typed fail-closed config, migration runner, least-privilege SQL boundary, secure HTTP runtime, atomic ISAB01 deploy/rollback), the confidential 2026 dossier import, the Entra applicant portal with admin preview and synthetic workspace, and the citation/publication analytics pipeline. Off-repo work covered the `isab-cloudflare-edge` Access/Tunnel configuration, Azure cost containment, Planner/Outlook tasks, and payroll analysis.

## Operational facts
- Repo `aagaag/EHF-applications`, remote `https://github.com/aagaag/EHF-applications.git`, branch `main`; working copy `C:\Users\aag\Documents\ChatGPT\EHF-applications`.
- Edge repo `isab-cloudflare-edge` at `C:\Users\aag\Documents\GitHub\isab-cloudflare-edge`, remote `https://github.com/aagaag/isab-cloudflare-edge.git`.
- Python runtime `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`; Git Bash `C:\Program Files\Git\bin\bash.exe`; Node `C:\Program Files\nodejs\node.exe`.
- Host ISAB01 `aag@10.10.20.29` (aka `isab-db01`); SQL Server `tcp:127.0.0.1,1433`; `sqlcmd` `/opt/mssql-tools18/bin/sqlcmd`.
- App runtime: systemd `ehf.service`, release `/opt/ehf/current` → `/opt/ehf/r/<40-hex>`, env file `/etc/ehf/ehf.env`, Uvicorn `127.0.0.1:8086`, Nginx `infra/ehf.nginx.conf`, `client_max_body_size 27m`.
- Credential paths (locations only): `/etc/ehf/sql-admin-password`, `/etc/ehf/sql-app-password`, `/etc/ehf` dir, `/root/.config/finances2/sql-sa`, env `EHF_SQL_ADMIN_PASSWORD_FILE`; clamd socket `/run/ehf/clamd.sock` mode `0660`.
- Deploy: `scripts/deploy-isab01.ps1 -Apply -SqlAdminCredentialPath '/etc/ehf/sql-admin-password'` (33 safety checks, atomic symlink switch); verify `scripts/verify-isab01.ps1 -ExpectedCommit <40-char>`; SQL harness `scripts/test-database.ps1 -ServerInstance ISAB01`, DB name must start `EHFApplications_Test`.
- Production hostname `ehf.isab.science`; tunnel `488ac19a-fef0-43c9-a074-41b3704fce11`, origin `http://10.10.20.29:80`, remoteConfigVersion 16; Cloudflare account `e4ec09ddaaba478f6067111512f06dc6`; Entra IdP `74693dda-cd39-4833-b6a0-605f623afc7b`; internal Access audience `fdfc08a1ee631a829262a79a7acb88e329616b5a501439f09152a4b26c424111`; applicant audience `847f3e25d6…` (truncated in logs).
- Entra: tenant `8226a4c2-10fa-4742-b4c0-f4fdb97a0534`; groups `8e199674-d599-45e1-9daa-d138a0b40753`, `fc584ecb-8be3-4f70-89d0-a5f0ae37f21a`; `EHF-Applicants` `55caf353-80bb-4805-81f0-e31b6fc84b23`; admin/trustee groups canonical names `EHF-Applications-Administrators` / `EHF-Applications-Trustees`.
- Config prefix `EHF_`; `EHF_ENVIRONMENT=production`; `EHF_APPLICANT_PORTAL_ENABLED=true`; `EHF_INVITATIONS_ENABLED=false`; `EHF_PRODUCTION_MAIL_ENABLED=false`; `EHF_DOCUMENT_ROOT=/var/lib/ehf/documents`; `EHF_QUARANTINE_ROOT=/var/lib/ehf/quarantine`; `EHF_APPLICANT_GROUP_ID`, `EHF_TURNSTILE_SITE_KEY`, `EHF_CLOUDFLARE_ACCESS_AUDIENCE`.
- Migration inventory: 001–003 (core/audit/preferences), 004 audit+preference hardening, 005 application permissions, 006 user preference read, 007 document store, 008 import provenance, 009 document permissions, 013 applicant confirmations, 016 Entra applicant workflow, 017 applicant form simplification, 018 applicant admin preview, 019 synthetic applicant workspace, 020 synthetic pilot, 021 application publications, 022 applicant publication preview, planned 023 publication citation sources.
- Published-003 integrity: migration SHA-256 `472fdfb22cb2ea46f786059905e8c1f9491b7081e145bb8731f9b0c6dd4349ac`, git blob `7a40251f5dc774443e5a895e5fdc66dce3f8c013`; validator SHA-256 `da5b321af3e99299181f0fe6cd7ad54236d8859ea44d4cbf9e6547a33df72d12`, blob `0700f5292cb570bad4b8e39ef2c1260daf3…`.
- Pins: `python-docx==1.2.0`, `openpyxl==3.1.5`, `pytest==9.1.1`, `httpx==0.28.1`, `playwright==1.62.0`, `axe-playwright-python==0.1.8`, `cryptography 49.0.0`, `pypdf 6.10.0`, `pypdfium2 5.12.1`, `pdfplumber 0.11.9`.
- Deployed commits seen: `0c5064020aff01d64c317be7460b9946edae033b` (`0c50640`), then `94374c9f372a843dfb0cdd660eaec0bfedd01b07`; GitHub tips observed: `ff39264ee2aa03b7a9f24c11c594d56c3c40010c`, `88c9227ead5be5e4e960976d34457294bf7c0754`, `f1316e10f686b7d21e775deafa4d59f75c8b7689`.
- SQL error numbers in use: 52021, 52025, 52130, 52133, 52135, 52136, 52143 (→ `CorrectionRequired`), 52144, 52430–52435, 52810, 52900, 52910–52914, 53707, 53710/53711/53713, 53910, 53914, 53917, 53920–53922, 53924, 53925, 4060.
- Logo asset: 19,932 bytes, SHA-256 `D70B7722957A3ACCD8D4E16BB6BFCD8E48A153DE82C3C496CC34EE183645CC0E`.
- Citation plotting: 15 top-cited callouts, 4 web skins, first palette collision ranks 1/988 (`#DD2C4E`), hue step 137.507764.
- Publication corpus: 36 applicants, 848 unique works, 883 occurrences, 841 final, 2,523 status rows; manifest SHA-256 `74b87c020ffbb5cf63bf8ccd33bcb76b804401894c8a098e79014c241f0c8937`.
- Microsoft 365: Planner plan `el_gRiSSUU-Ts0aJRwSd5ZgAEVmC`, bucket `RZU5NpkhzE6HDnGB5iA7opgAIj3p`, assignee `d5c5fb6a-f9c3-456c-97b1-20b450647f8c`; default Outlook originator `adriano.aguzzi@isab.science` (policy in `C:\Users\aag\.codex\AGENTS.md`, line 320).
- Monitoring: Icinga `icinga.lan` / `10.10.20.18`, workstation `AagHomeOffice` / `10.10.20.25`, key `/var/lib/nagios/.ssh/aaghomeoffice_monitor`, forced command `C:/ProgramData/CodexHardwareMonitor/scripts/Get-HardwareMonitorNagios.ps1`, check every minute.
- Azure: subscription `e8a0b21b-32a5-4970-9729-67242ee7ace8`, budget `ISAB-Monthly-90-CHF` (CHF 90; alerts 45/72/90 actual + 72/90 forecast).

## Milestones
- 2026-08-09 — Two Planner tasks created (coworker payroll, two clocking devices, due 2026-08-10); initial Codex heartbeat automation deleted (019fe7bd).
- 2026-08-10 — Foundation Task 1: repo bootstrap + coordination contract, commits `f6aad590f30541c0a26e973c43ad17542b7a2d82`, `13f05de4dec28a65e79cdd3a7a219f87152d4778` (019fe9ae); reviewed and re-reviewed (019fe9b4, 019fe9b8).
- 2026-08-10 — Foundation Task 2: typed fail-closed config `app/config.py`, `infra/ehf.env.example`; commits `fd03230142858e1afffe1107446880542bc17378`, `465c0e2b6d0efc3f3ebf5cdccf99d012e6b8a9e6` (019fe9b9, 019fe9c0, 019fe9c8).
- 2026-08-10 — Task 3 migration runner/DDL + SQL validators (019fe9e0); audit/preference hardening redelivered as additive migration 004, commit `d5534a6076303db783946ab64d44b8811b3f55f9` (019fe9cb, 019fe9ef, 019fe9ff).
- 2026-08-10 — Task 3 validator harness rounds 3–5: `-I` fix, per-failure transactions, safe cleanup order; commits `ea27e9d3…`, `45671d551c23d2852071491cf8dae4271c3454ec`, `b4a7c8ce748d3d59a6e8f7ba06b75cdaf08ffab8` (019fea06, 019fea17).
- 2026-08-10 — Task 4 least-privileged SQL boundary: `infra/sql-principal.py`, `infra/setup-sql-login.sh`, `infra/test-sql-login.sh`, migration 005; iterated through review rounds `b09b8bf`, `3c02ecb`, `cb7cc06`, `8d892db`, `43abba3`, `ae5436a`, `7574ae3` (019fea02, 019fea2b, 019fea6a, 019feab3, 019feabd, 019feae6, 019feafa, 019feb0e).
- 2026-08-10 — Task 5 secure HTTP runtime: health endpoints, host/Content-Length/disconnect hardening; commits `5b95c52`, `ce917c4`, `3c02722` (019feb2d, 019feb37, 019feb46).
- 2026-08-10 — Task 6 shared ISAB shell + durable preferences; correction commits `33db51e`, `48a0106`, migration 006; final review PASS (019feb4c, 019feb5f, 019feb77).
- 2026-08-10 — Task 7 ISAB01 deployment/rollback tooling, commits `bb44a70`, `599820d`, `infra/bootstrap-ehf-database.py`, `infra/install-isab01.py`, `scripts/deploy-isab01.ps1` (019feb7f); deployment retry fix reviewed (019febd6).
- 2026-08-10 — Import Tasks 1–5 (inventory/register parsing/classification) and Tasks 1–2 of document plan: migrations 007–009, encrypted object store, PDF/malware adapters (019feb89, 019feb8a); import Task 6 idempotent plan/apply (019feb9a); independent review (019feb9a, 019febaf, 019febc5, 019febc8).
- 2026-08-10 — Cloudflare edge EHF Access configurator added, hardened, tunnel gate added: `scripts/configure-ehf-access.mjs`, `.test.mjs`, deployment gate in `deploy-events-tunnel.ps1` (019febce, 019febd0, 019febf7).
- 2026-08-10 — Azure spend contained: caps applied (billable 384 GiB → 82 GiB), `ISABOrderingDev` frozen, O2 group retired (019feca2).
- 2026-08-10 — Applicant missing-items email template drafted as unsent Outlook draft from `adriano.aguzzi@isab.science` (019fed08).
- 2026-08-11 — Internal Applications page reworked (cards removed, report-row modals, per-field sorting, completeness filter); commits `1e94c74`, `976d1c9`, `f1316e1` (019fefb8).
- 2026-08-11 — Daily cost of delayed lab space computed: CHF 3,102.04/calendar day (019fefce).
- 2026-08-11 — Applicant portal rolled out on ISAB01 with migrations 017–020, Entra guest identity, synthetic workspace; commits `88c9227`, `361d2200…`, `693c8b8`, `b2b10dd`, `a0f826d`, `09438f7`, `57bc4a7`, `ddcb2d4` (019feff0).
- 2026-08-11 — Citation scatterplot callouts (shared `CitationPlotPoint` model), commit `19d9022af58df66ff8483b63d03effde77ed9594`; reviewed merge-ready (019feff0, 019ff004).
- 2026-08-18 — Merge-blocker re-checks and portal reviews: form simplification (017), admin preview (018), canonical routes/`/assets/*` bypass, root 403 diagnosis (01a012b7, 01a01319, 01a0136b, 01a013f4, 01a01430).
- 2026-08-18 — Synthetic applicant workspace: audit + design 019 (01a014f5), validator transaction repair commits `1795ea9`, `83d65f7`, `0c50640` (01a014fd), SQL boundary fix `4cecfff`/`a0f826d` with reviews (01a0150a, 01a01517, 01a0151d), Task 2 sessions `b517345`, `bb5b73f` (01a0151f), Task 3 routes `da36ebf`/`3f86ce4` (01a0152a, 01a0153a).
- 2026-08-21 — Cloudflare `403` on `https://ehf.isab.science/` fixed by restoring hostname-wide internal Access app; commit `6e70c78` "fix: restore EHF root Access boundary" (01a0228b).
- 2026-08-23 — Publication pipeline: DOI inventory (01a02d9a), workbook/Scholar extraction (01a02d9a), schema mapping for 021/022 (01a02e36), folder extraction (01a02e36), zero-count dossiers (01a02e3d), v3 dedup/audit (01a02e41), Crossref enrichment (01a02e4a, 01a02e4d), import manifest (01a02e60), Scholar/OpenAlex checks (01a02e7a), reviews + Scholar shard 0 (01a02e96), publication subform + shard 3 (01a02ecc), captcha-free citation comparison (01a02d99, 01a02d99).
- 2026-08-24 — Scattergram callout placement reviewed across five iterations (01a0319e); `/applicant/review` 404 diagnosed as intentional fail-closed behavior, deployed commit `94374c9f372a843dfb0cdd660eaec0bfedd01b07` (01a03206).

## Decisions & rationale
- Work directly on `main`, no branches/worktrees, no push (controller pushes); strict TDD with captured RED before implementation.
- Applied migrations are checksum-immutable; hardening ships as a new additive migration (003 → 004; 004 → 005; 006 taken → 007–009) because the runner enforces raw-byte SHA-256 and rejects drift.
- Config accepts only absolute credential-file paths; secrets read lazily from files; diagnostics use an explicit redacted allowlist; production mail gate requires approved sender + transport allowlist (Microsoft Graph) + delivery-test receipt.
- Least privilege: dedicated `ehf_app` login mapped to `EHFApplicationRuntime`, procedure-scoped `EXECUTE AS`, `DENY IMPERSONATE`, exhaustive DML/metadata denial probes; `CREATE USER FOR LOGIN` implicitly grants CONNECT so `REVOKE CONNECT` follows; cleanup authorized only by suffix-bound names + DB marker tokens.
- Never trust `X-Forwarded-Host`; parse raw `Host`; inspect `Content-Length` as raw header list; run readiness probes off the event loop with wall-clock deadline and bounded concurrency.
- Applicant portal: one session-bound dynamic portal, Entra object ID ↔ one application, immutable; applicant edits require admin/trustee approval; synthetic records blocked from invitations, provisioning, approval/promotion, reports/exports and uploads.
- Cloudflare: hostname-wide internal Access app is the parent (`HOST/*`) with more-specific `/applicant/*` and `/assets/*` rules; `/assets/*` ingress (no `originRequest.access`) must precede the protected tunnel rule.
- Recommendations confidentiality enforced via authoritative `dbo.Recommendation` linkage AND `DocumentType`, made append-only by trigger; `SourceOccurrence` must not link a `DocumentVersion` owned by another application.
- Citation sourcing: Semantic Scholar primary, OpenAlex dropped from visible labels, Google Scholar only as a per-paper link; CAPTCHA is never bypassed — stop, checkpoint atomically, resume from verified records only.
- Publication schema: `Application` → `ApplicationPublication` → append-only `PublicationMetadataObservation`/`PublicationCitationObservation`, `UNIQUE(ApplicationId, Doi)`, soft-remove via `IsActive`; do not extend `_CITATION_SOURCES`; add migration 023 instead.
- Scatterplot callouts use deterministic occupied-box placement with local leaders and a documented 36-applicant bounded layout that raises `ValueError` when placement is impossible.
- Azure: no data deleted, resizes kept ≥72% headroom, `autoPauseDelay` 15, `ISABOrderingProd` left online pending migration to ISAB01; Dev-first→Prod promotion rule superseded.

## Bugs
Fixed:
- `$Python` undefined in runnable README blocks; missing branch/clean-status check before deploy — fixed in `13f05de4dec28a65e79cdd3a7a219f87152d4778`.
- Config path escapes: `relative_to` accepting `..` (`/run/credentials/ehf.service/../../../var/lib/ehf/sql-password`); document/quarantine root aliasing; mail gate accepting arbitrary strings.
- `@DatabaseName` omitted from `sys.sp_executesql` params (`infra/sql-principal.py:543`, Msg 137, exit 15) — fixed at `:548` in `cb7cc06`.
- `ALTER USER ... WITH LOGIN` unsupported (error 33016); `CREATE USER FOR LOGIN` implicit direct CONNECT — replaced by drop/create + `REVOKE CONNECT`.
- `sqlcmd` missing `-I` (QUOTED_IDENTIFIER); validator doomed outer transactions (Msg 3930); `REVERT` before rollback in 019 validator catch paths (`1795ea9`, `83d65f7`, `0c50640`).
- Task 5: unbounded readiness wait, forwarded-host trust, collapsed `Content-Length`, disconnect reaching routes, exceptions escaping middleware (`3c02722`).
- `SameSite=Strict` sign-in loop (`88c9227`); `/applicant/review` 404 (`361d2200…`); assets 403 (`693c8b8`); validator `42S22 SlotLabel`; NULL `@ActorGroup` (`a0f826d`); Entra `custom.oid`.
- Synthetic workspace: invitation sessions rejected (`app/main.py:234-245`); `*.html` static aliases served to wrong administrator; malformed SQL session rows accepted.
- Publication preview: `SqlPreferenceRepository` wrong column indexes; wrong-author title matches; false `NOT_FOUND`; citation matrix; queue overwrite (`[IO.File]::Move` 3-arg).
- Cloudflare: `/` unauthenticated by any Access app (403) — fixed in `6e70c78`; `/assets/*` bypass not delivered (tunnel ingress) — fixed by ordered `^/assets/.*$` rule.
- Longer-term: 60/153 PDF non-blocking rejections, 8 root items unpersisted, failed-run fingerprint collision, root-owned store objects, world-readable `/tmp` staging, identity-map family-name mismatches — resolved or downgraded by the follow-up pass.

OPEN:
- `ProvisionApplicantAccessRequest` (`016_entra_applicant_workflow.sql:400`) non-atomic, no `ApplicationId`/`ApplicantEntraIdentity` insert, no caller.
- Group removal does not revoke live sessions; 24 h session retains access (`app/routes/applicant_entra.py:27`, 016:475).
- `PromoteApprovedApplicantDrafts` (016:1362) overwrites Foundation-verified Google Scholar counts.
- `clinicalWorkPercent = 0` allowed in `app/applicant/fields.py:137` but constrained 0.01–100 in 016:1341 — promotion rolls back.
- SQL errors 52133/52135/52136 unhandled (`sql_pilot.py:631` maps only 52430–52435).
- Migration 019 non-synthetic session exclusion untested for `LastSeenAtUtc`/Entra sessions.
- Phase-0 `EXECUTE AS` cleanup absent if an impersonated procedure errors (`019_validate_...sql`).
- Importer reruns do not update existing metrics (`app/importer/run.py:349-360`); occurrence counts disagree (docs 162/8 vs verifier `164/10`).
- Two diagnostic strings still say `022` in `scripts/test-database.ps1:43,47`; dead OpenAlex code in `open_citation_collector.py`.
- Stale "sixteen validators" documentation conflict.
- 251 unresolved DOI-like candidates; 307 unresolved and 15 ambiguous works; 4 ambiguous records and 9 DOI-overlap groups unverified; Ogulur near-duplicate pair unconfirmed; 31 workbook discrepancies.
- `ISAB01` unresolved from the workstation (SQL error 53) — live SQL validator never executed for several rounds.
- 14 uncommitted worktree changes on `main`; several commits unpushed.

## Pitfalls
- `project.isab.science` / `ISAB01` hostname does not resolve from the workstation (`SQL error 53` — Named Pipes); live verification must run on the server.
- Windows clean clones rewrite `database/migrations/003_audit_and_preferences.sql` to CRLF and break checksum validation; use `git -c core.autocrlf=false`.
- `pytest tests/browser` collects 0 tests; browser specs are `*.spec.py` and must be enumerated explicitly, and need an injected `<base href="https://ehf.example/">`.
- `rg` glob arguments fail on Windows (`os error 123`) — pass directories; look-around needs `--pcre2`; `-F` for `${...}`.
- PowerShell: `"$Path:$Start"` raises ParserError — use `${Path}`; empty-pipe `ParserError`; `ConvertFrom-Json` fails on case-differing OpenAlex keys (use `-AsHashTable`).
- Tests using fake cursors/source-string assertions hid real defects (unbound `@DatabaseName`, stale validator order); green suites are not lifecycle evidence.
- Running the full suite while other agents edit the tree yields false failures (importer, `app/main.py` concurrent edits).
- `api.crossref.org` blocked by URL safety checks (non-retryable); use PubMed/DOI URLs.
- Google Scholar triggers CAPTCHA quickly; aborted runs produce all-`NOT_FOUND` output that must be discarded.
- Cloudflare path wildcards do not cover the parent/root URL; Bypass disables Access but `cloudflared` still rejects requests without a valid `Cf-Access-Jwt-Assertion`.
- `wait_agent` timeouts clamp to 10 s minimum; subagent dispatch needs `[features] multi_agent = true` in `~/.codex/config.toml`.
- `C:\Users\aag\.codex\skills\.system\superpowers\using-superpowers\SKILL.md` does not exist; use the plugin cache path.
- Word COM automation: `SendUsingAccount` does not persist after save/reopen; leave no orphan `WINWORD` processes.

## Open items
- [OPEN] Wire Cloudflare/Entra identity resolver and role-scoped SQL repository before deployment; provision Access app/audience, DNS/Tunnel route, metrics path (019febc5, 019febc8).
- [OPEN] Fix and re-verify the five applicant-workflow Important items above, with a real-SQL zero-value approval test (01a012b7).
- [OPEN] Add defense-in-depth tests: group removal → 404, object-ID mismatch → 404, legacy invitation session on each canonical route; tunnel route-order test; unauthenticated production asset probe (01a01319).
- [OPEN] Shard 3 Scholar verification incomplete (Shami Pour, Lorenzini profile IDs `null`); implement migration `023` + validator with `openalex_citation_count/status`, `semantic_scholar_citation_count/status` (01a02ecc).
- [OPEN] Add populated-queue and 303-cookie browser regressions; capture OpenAlex batch timestamps immediately (01a02e96).
- [OPEN] Add browser regression asserting distinct non-overlapping scatterplot label bounds at desktop and mobile (01a0319e).
- [OPEN] Review/reconcile 2026 identity map (36 people) and block Apply until exact; 336 dossier DOIs still absent from the database (01a014d5, 01a02d9a).
- [OPEN] Resolve 4 ambiguous records, 9 DOI-overlap groups, 251 unresolved candidates, 307 unresolved/15 ambiguous works, and 31 workbook discrepancies (01a02e41, 01a02e4a, 01a02e4d, 01a02e60).
- [OPEN] Run the isolated SQL verifier and confirm zero leftover test DBs/logins (`0|0`) for the current commit (019fea02, 019feabd, 019feafa).
- [OPEN] Add validator asserting tunnel route order `/assets/*` scope and catch-all 404 (01a01319).
- [OPEN] Optional hardening: apply-mode Cloudflare migration test from the prior `/internal/*` app; optional `/` Access regression test (01a0228b).
- [OPEN] Add tests for hard-interruption incomplete-venv removal/rebuild and refusal of active incomplete venv (019febd6).
- [OPEN] Wire invitation/mail flags, persistent adapters, OTP, mail queue; fix failing `test_release_sixteen_adds_a_synthetic_only_pilot_and_pending_approval_boundary` (019feff0).
- [OPEN] Provision applicant preview smoke checks post-deploy (admin access, trustee 404, `APPLICANT_PREVIEW_OPENED` event) (01a01430).
- [OPEN] Applicant email draft still holds placeholders (`{{applicant_first_name}}`, `{{missing_item_N}}`, `{{deadline}}`, `{{secure_personalized_link}}`, `{{contact_email}}`) and no recipients (019fed08).
- [OPEN] Adrian Meier draft with 6 attachments (including `Neuropath_ISAB_Transfer_signed_20260521.pdf`) not sent; UBS e-banking session left open (01a014d5).
- [OPEN] `send_message_to_thread` TypeError blocked delivery to `/root`; CASL DOI case mismatch (01a014f5).
- [OPEN] Commit/push remaining worktree changes on `main` (blog: multiple threads, e.g. 01a03206, 01a0152a, 01a0153a).
- [OPEN] MSCA Part B1 host-institution confirmation, "Eliana Carr" verification, and approval of inserted host text (01a015cd).
- [OPEN] Icinga: confirm whether the 15 Aug `administrators_authorized_keys` overwrite was one-off; uncommitted `house.lan` monitoring changes (01a015fc).
- [OPEN] Azure: migrate `ISABOrderingProd` and Expenses/Reimbursement/Reconciliation/Appenzell to ISAB01, retire `fileclassifier`, complete O2 migration, review costs 2026-08-13 (019feca2).
- [OPEN] Finances2: production `/opt/finances2/current` has uncommitted `infra/*.sh`; local clone behind production main (019fefce).

## Session index

- 2026-08-09 `019fe7bd` — For tomorrow task, remind me that I need to tackle the payroll for the coworkers, and I al
- 2026-08-10 `019fe9ae` — You are implementing Task 1: Bootstrap the repository and coordination contract. Read this
- 2026-08-10 `019fe9b4` — You are reviewing one task's implementation: Task 1, Bootstrap the repository and coordina
- 2026-08-10 `019fe9b8` — You are re-reviewing Task 1 fix round 1. Verdict only the two prior findings and inspect t
- 2026-08-10 `019fe9b9` — You are implementing Task 2: Add typed configuration with fail-closed production checks. R
- 2026-08-10 `019fe9c0` — Review Task 2: typed fail-closed EHF configuration. This is a task-scoped spec and code-qu
- 2026-08-10 `019fe9c8` — Re-review Task 2 fix round 1. Verdict only the prior Critical/Important findings and inspe
- 2026-08-10 `019fe9cb` — Task 3 fix round 2. Work on current main; do not push/deploy. Strict TDD and minimal chang
- 2026-08-10 `019fe9e0` — You are the independent Task 3 reviewer for the EHF applications project. Work read-only: 
- 2026-08-10 `019fe9ef` — You are the independent re-reviewer for EHF Foundation Task 3 fix round 1. Read-only: do n
- 2026-08-10 `019fe9ff` — You are the independent re-reviewer for EHF Foundation Task 3 fix round 2. Read-only; do n
- 2026-08-10 `019fea02` — Resume immediately for controlled recovery, not further test runs. Audit the 10 leftover r
- 2026-08-10 `019fea06` — Implement the exact bounded Task 3 fix described here: C:\Users\aag\Documents\ChatGPT\EHF-
- 2026-08-10 `019fea17` — Independent final re-review for EHF Foundation Task 3 live-SQL fixes. Read-only: do not ed
- 2026-08-10 `019fea2b` — Independent security review of EHF Foundation Task 4. Read-only: no edits, commits, pushes
- 2026-08-10 `019fea6a` — Independent re-review for EHF Foundation Task 4 fix round 1. Read-only: do not edit, commi
- 2026-08-10 `019feab3` — Perform a final independent read-only security/spec review of Task 4 in C:\Users\aag\Docum
- 2026-08-10 `019feabd` — Complete fix round 5 for one verified omission at cb7cc06. In production _map_user dynamic
- 2026-08-10 `019feae6` — <subagent_notification> {"agent_path":"019feab3-3c19-7c01-ac1e-3e6c3b0cfa54","status":{"co
- 2026-08-10 `019feafa` — <subagent_notification> {"agent_path":"019feab3-3c19-7c01-ac1e-3e6c3b0cfa54","status":{"co
- 2026-08-10 `019feb0e` — <subagent_notification> {"agent_path":"019feab3-3c19-7c01-ac1e-3e6c3b0cfa54","status":{"co
- 2026-08-10 `019feb2d` — <subagent_notification> {"agent_path":"019feab3-3c19-7c01-ac1e-3e6c3b0cfa54","status":{"co
- 2026-08-10 `019feb37` — <subagent_notification> {"agent_path":"019feab3-3c19-7c01-ac1e-3e6c3b0cfa54","status":{"co
- 2026-08-10 `019feb46` — <subagent_notification> {"agent_path":"019feab3-3c19-7c01-ac1e-3e6c3b0cfa54","status":{"co
- 2026-08-10 `019feb4c` — Task 6 independent review found five Important issues. Implement a focused TDD correction 
- 2026-08-10 `019feb5f` — Perform an independent read-only review of Foundation Task 6 in C:\Users\aag\Documents\Cha
- 2026-08-10 `019feb77` — Independent final read-only review of corrected Foundation Task 6. Repo: C:\Users\aag\Docu
- 2026-08-10 `019feb7f` — Implement Foundation Task 7 in C:\Users\aag\Documents\ChatGPT\EHF-applications. Read the c
- 2026-08-10 `019feb89` — Work in C:\Users\aag\Documents\ChatGPT\EHF-applications on current main. User explicitly r
- 2026-08-10 `019feb8a` — Work in C:\Users\aag\Documents\ChatGPT\EHF-applications on current main. Implement ONLY do
- 2026-08-10 `019feb9a` — Work in C:\Users\aag\Documents\ChatGPT\EHF-applications on current main, no branch. User e
- 2026-08-10 `019feb9a` — Independent security/code review only in C:\Users\aag\Documents\ChatGPT\EHF-applications. 
- 2026-08-10 `019feba3` — Fix the independent review's deployment/runtime P1s in C:\Users\aag\Documents\ChatGPT\EHF-
- 2026-08-10 `019feba3` — Fix the independent review's database confidentiality P1s in C:\Users\aag\Documents\ChatGP
- 2026-08-10 `019febaf` — <subagent_notification> {"agent_path":"019feba3-c8e5-7ef3-bdaa-ef789f435aa1","status":{"co
- 2026-08-10 `019febc5` — <subagent_notification> {"agent_path":"019feba3-c8e5-7ef3-bdaa-ef789f435aa1","status":{"co
- 2026-08-10 `019febc8` — <subagent_notification> {"agent_path":"019feba3-c8e5-7ef3-bdaa-ef789f435aa1","status":{"co
- 2026-08-10 `019febce` — Review the uncommitted EHF Cloudflare edge changes in C:\Users\aag\Documents\GitHub\isab-c
- 2026-08-10 `019febd0` — Implement fixes in C:\Users\aag\Documents\GitHub\isab-cloudflare-edge for the review findi
- 2026-08-10 `019febd6` — Review only the uncommitted deployment retry fix in C:\Users\aag\Documents\ChatGPT\EHF-app
- 2026-08-10 `019febf7` — Independently review only the current uncommitted diff in C:\Users\aag\Documents\GitHub\is
- 2026-08-10 `019feca2` — [files attached:]
- 2026-08-10 `019fed08` — We will at some point in the near future request additional information from the applicant
- 2026-08-11 `019fefb8` — [https://ehf.isab.science/internal/#applications](https://ehf.isab.science/internal/#appli
- 2026-08-11 `019fefce` — Based on the salaries of the ICB co-workers, the current co-workers, and based on the fact
- 2026-08-11 `019feff0` — The next step is to create a page that each, so a personal page that each applicant will h
- 2026-08-11 `019feff0` — Also, please enhance the citation graphs, the scatter plots, the citation scatter plots by
- 2026-08-11 `019ff004` — (no user text)
- 2026-08-18 `01a012b7` — (no user text)
- 2026-08-18 `01a01319` — (no user text)
- 2026-08-18 `01a0133d` — Sony A7C II: I need a fisheye objective for this camera, which I can use for photography o
- 2026-08-18 `01a0136b` — (no user text)
- 2026-08-18 `01a013f4` — # **Access to ehf.isab.science was denied** **You don't have the user rights to view this 
- 2026-08-18 `01a01430` — (no user text)
- 2026-08-18 `01a014d5` — [files attached:]
- 2026-08-18 `01a014f5` — (no user text)
- 2026-08-18 `01a014f5` — (no user text)
- 2026-08-18 `01a014fd` — (no user text)
- 2026-08-18 `01a0150a` — (no user text)
- 2026-08-18 `01a01517` — (no user text)
- 2026-08-18 `01a0151d` — (no user text)
- 2026-08-18 `01a0151f` — (no user text)
- 2026-08-18 `01a01526` — (no user text)
- 2026-08-18 `01a0152a` — (no user text)
- 2026-08-18 `01a0153a` — (no user text)
- 2026-08-18 `01a015b1` — [files attached:]
- 2026-08-18 `01a015bd` — Several months ago I was asking for a quote to set up 20 Windows computers within ISAB, an
- 2026-08-18 `01a015cd` — [files attached:]
- 2026-08-18 `01a015fc` — [files attached:]
- 2026-08-21 `01a0228b` — [files attached:]
- 2026-08-21 `01a02298` — (no user text)
- 2026-08-23 `01a02d99` — done, but how can I avoid more captchas? Is there an API to access scholar?&#x20;
- 2026-08-23 `01a02d9a` — (no user text)
- 2026-08-23 `01a02d9a` — (no user text)
- 2026-08-23 `01a02e36` — (no user text)
- 2026-08-23 `01a02e36` — (no user text)
- 2026-08-23 `01a02e36` — (no user text)
- 2026-08-23 `01a02e3d` — (no user text)
- 2026-08-23 `01a02e41` — (no user text)
- 2026-08-23 `01a02e4a` — [files attached:]
- 2026-08-23 `01a02e4d` — (no user text)
- 2026-08-23 `01a02e4d` — (no user text)
- 2026-08-23 `01a02e60` — (no user text)
- 2026-08-23 `01a02e7a` — (no user text)
- 2026-08-23 `01a02e7a` — (no user text)
- 2026-08-23 `01a02e7a` — (no user text)
- 2026-08-23 `01a02e96` — (no user text)
- 2026-08-23 `01a02ecc` — [files attached:]
- 2026-08-23 `01a02d99` — done, but how can I avoid more captchas? Is there an API to access scholar?&#x20;
- 2026-08-24 `01a03192` — (no user text)
- 2026-08-24 `01a0319e` — (no user text)
- 2026-08-24 `01a03206` — [files attached:]
