# EHF deployment and rollback

## Production architecture and startup order

The EHF production workload runs on the Hestia compute platform in the
`isab-db01` VM. The VM hosts both the loopback-only Uvicorn service on
`127.0.0.1:8087`, with its active release at `/opt/ehf/current`, and the SQL
Server engine used by the application. Nginx on that VM is the local proxy for
`ehf.isab.science` only.

Only SQL Server data for the exact `EHFApplications` database belongs on the
QNAP TS-873A `ISAB_DBS` iSCSI storage. The iSCSI-backed XFS filesystem is
mounted at `/var/opt/mssql/data`, where SQL Server keeps that database's files.
This placement does not put `/var/lib/ehf/documents` or
`/var/lib/ehf/quarantine` on QNAP; those application paths are outside this
QNAP SQL-storage claim.

Startup must preserve this exact fail-closed dependency chain:

1. Start Hestia/libvirt.
2. Bring up the persistent `isab-db01-mgmt` VM network.
3. Start the `isab-db01` VM only after that network is available.
4. In `isab-db01`, bring the `ISAB_DBS` iSCSI storage online and mount its XFS
   filesystem at `/var/opt/mssql/data`.
5. Start SQL Server only after that mount is available.
6. Start `ehf.service` only after SQL Server is available, so its Uvicorn
   process at `/opt/ehf/current` cannot begin before its database engine.

Every dependency must fail closed: an unavailable predecessor prevents the
dependent network, VM, mount, SQL Server, or `ehf.service` from starting. The
Hestia/libvirt and VM configuration, and the guest systemd configuration, must
enforce this order. A service restart or host boot must never allow SQL Server
to initialize `EHFApplications` on fallback local storage. This process does
not publish Cloudflare DNS, create a Tunnel route, change
Cloudflare Access, enable invitations, enable production mail, import
applicant records, or send any message.

## First-install prerequisites

An `isab-db01` administrator must prepare the non-secret environment file and the
four protected application credentials before `-Apply`. Do not put credential
contents in this repository, in a command line, or in a deployment log.

1. Create the locked service account and configuration directory by running
   the deployment once it has the approved SQL administrator credential path.
   The installer creates `ehf` with `/usr/sbin/nologin`, locks it, and creates
   `/var/lib/ehf/documents` and `/var/lib/ehf/quarantine` as its only writable
   application paths.
2. Create `/etc/ehf/ehf.env` from
   [`infra/ehf.env.example`](../infra/ehf.env.example), replacing every
   non-secret placeholder with the approved EHF production value. Keep these
   two exact lines:

   ```text
   EHF_INVITATIONS_ENABLED=false
   EHF_PRODUCTION_MAIL_ENABLED=false
   ```

   The Entra applicant portal uses the exact internal and applicant Access
   audience tags as a comma-separated `EHF_CLOUDFLARE_ACCESS_AUDIENCE` value.
   Enabling `EHF_APPLICANT_PORTAL_ENABLED=true` also requires the canonical
   `EHF_APPLICANT_GROUP_ID` and the non-secret `EHF_TURNSTILE_SITE_KEY` whose
   widget permits `ehf.isab.science`.

3. Place these root-owned `0640` files in `/etc/ehf`, group `ehf`:

   - `document-keyring`
   - `session-pepper`
   - `otp-pepper`
   - `turnstile-secret`

   The protected SQL administrator credential remains in its approved
   root-only location and is supplied to `-Apply` as a path only. The installer
   creates `/etc/ehf/sql-app-password` itself as `root:ehf`, `0640`, after the
   isolated SQL verifier passes.

4. Confirm that `/opt/mssql-tools18/bin/sqlcmd`, ODBC Driver 18, SQL Server,
   Python 3.12, Nginx, `curl`, `tar`, and `systemd` are available. The script
   validates the application SQL principal and uses the release virtual
   environment at `/opt/ehf/current/venv/bin/python`.

The administrator must not create a public DNS record, alter a Cloudflare
Tunnel, or enable invitations/mail as part of these prerequisites.

The unavoidable `isab01` text in legacy deployment and verification script or
test filenames is tooling terminology only; it does not identify another host.
Those tools operate on `isab-db01`.

## Local release gate and dry run

From the repository root, use the pinned repository Python runtime:

```powershell
$Python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python -m pytest infra\test-install-isab01.py tests\test_deployment_contract.py -q
& $Python -m pytest -q
powershell -NoProfile -File scripts\deploy-isab01.ps1 -WhatIf
```

`-WhatIf` names the exact local commit and planned actions without connecting
to `isab-db01` or mutating any server. It is not an authorization to deploy.

## Apply

Before applying, push the reviewed commit and make the local checkout exactly
equal to `origin/main`. The deploy script refuses a dirty checkout, another
branch, or a mismatch between `HEAD` and `origin/main`.

```powershell
git push origin main
$AdminCredentialPath = '<approved root-only path on isab-db01>'
powershell -NoProfile -File scripts\deploy-isab01.ps1 -Apply -SqlAdminCredentialPath $AdminCredentialPath
powershell -NoProfile -File scripts\verify-isab01.ps1
```

The path variable contains a path, not a password. Do not echo it or replace it
with a credential value. The script builds `git archive` bytes for the exact
commit, stages only fixed `/tmp/ehf-<pid>` paths, then creates only the exact
`EHFApplications` database when it is absent. The release helper applies its
checksum-bound migrations and the twenty-three fixed validators before isolated SQL
principal verification and application-login setup. It refuses other database
names and unexpected migration state. Only after all installer and repository
tests pass does it change `/opt/ehf/current`, then it checks loopback readiness.
A failed post-activation check restores the prior immutable release link and
the prior service state automatically.

## Explicit rollback

First identify the previous immutable commit from a trusted deployment record
or from the validated release directory on `isab-db01`. It must be exactly 40
lowercase hexadecimal characters and match that release's `.commit` marker.

```powershell
$PreviousCommit = '<validated 40-hex previous commit>'
powershell -NoProfile -File scripts\deploy-isab01.ps1 -Rollback $PreviousCommit
powershell -NoProfile -File scripts\verify-isab01.ps1 -ExpectedCommit $PreviousCommit
```

Rollback never extracts an archive, modifies applicant data, enables mail, or
publishes a hostname. It atomically repoints `/opt/ehf/current` to the named
validated immutable release and restarts the service before checking readiness.
