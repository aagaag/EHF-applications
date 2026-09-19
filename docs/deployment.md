# EHF deployment and rollback

## Production architecture and startup order

The EHF production workload runs in the dedicated KVM virtual machine `EHF` on
the Hestia compute platform. The VM hosts the loopback-only Uvicorn service on
`127.0.0.1:8087` with its active release at `/opt/ehf/current`, its own SQL
Server 2025 instance on loopback `127.0.0.1:1433`, and the encrypted document
store under `/var/lib/ehf`. Nginx inside the VM is the local proxy for
`ehf.isab.science` only; ingress arrives from the Cloudflare tunnel through
`isab-proxy01`.

The VM is self-contained and host-independent: the `EHFApplications` database
files live on the VM's dedicated data disk (`ehf-data.qcow2`, ext4, mounted at
`/var/opt/mssql/data`), not on host-local storage, an external array, or any
retired network. The whole workload therefore moves between KVM hosts as two
qcow2 images (see [hestia-vm.md](hestia-vm.md)); no address plan, iSCSI LUN,
host path or appliance outside the VM participates in its operation.

Startup must preserve this exact fail-closed dependency chain:

1. Start the KVM host and libvirt.
2. Bring up the `ehf-net` VM network and the `EHF` domain (autostart).
3. The guest mounts its data disk at `/var/opt/mssql/data`; SQL Server starts
   only if that mount is present.
4. Start `ehf.service` only after SQL Server accepts connections, so its Uvicorn
   process at `/opt/ehf/current` cannot begin before its database engine.

Every dependency fails closed: an unavailable predecessor prevents the network,
VM, mount, SQL Server, or `ehf.service` from starting. A service restart or host
boot must never let SQL Server initialize `EHFApplications` on anything other
than the VM's own data disk. This process does not publish Cloudflare DNS,
create a Tunnel route, change Cloudflare Access, enable invitations, enable
production mail, import applicant records, or send any message.

## First-install prerequisites

An `EHF` VM administrator must prepare the non-secret environment file and the
four protected application credentials before `-Apply`. Do not put credential
contents in this repository, in a command line, or in a deployment log.

On a fresh VM, first apply the provisioning assets as described in
[hestia-vm.md](hestia-vm.md): `infra/hestia/provision-ehf-vm.sh` on the KVM host
creates the network and the domain, `infra/hestia/provision-ehf-guest.sh`
installs SQL Server 2025 with the host's administrator credential at
`/etc/ehf/sql-admin-password`, and `infra/hestia/restore-ehf-state.sh
<migration-bundle> configuration` places the protected configuration.

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
   isolated SQL verifier passes. A migration moves `document-keyring` with the
   documents (without it the stored objects cannot be decrypted) but never the
   SQL administrator credential, which is per host.

4. Confirm that `/opt/mssql-tools18/bin/sqlcmd`, ODBC Driver 18, SQL Server,
   Python 3.12, Nginx, `curl`, `tar`, and `systemd` are available. The script
   validates the application SQL principal and uses the release virtual
   environment at `/opt/ehf/current/venv/bin/python`.

The administrator must not create a public DNS record, alter a Cloudflare
Tunnel, or enable invitations/mail as part of these prerequisites.

## Local release gate and dry run

From the repository root, use the pinned repository Python runtime:

```powershell
$Python = 'C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python -m pytest infra\test-install-ehf.py tests\test_deployment_contract.py -q
& $Python -m pytest -q
powershell -NoProfile -File scripts\deploy-ehf.ps1 -WhatIf
```

`-WhatIf` names the exact local commit and planned actions without connecting
to the `EHF` VM or mutating any server. It is not an authorization to deploy.

## Apply

Before applying, push the reviewed commit and make the local checkout exactly
equal to `origin/main`. The deploy script refuses a dirty checkout, another
branch, or a mismatch between `HEAD` and `origin/main`.

```powershell
git push origin main
git fetch origin
$AdminCredentialPath = '/etc/ehf/sql-admin-password'
powershell -NoProfile -File scripts\deploy-ehf.ps1 -Apply -SqlAdminCredentialPath $AdminCredentialPath
powershell -NoProfile -File scripts\verify-ehf.ps1
```

The deploy script targets the `ehf-hestia` SSH alias (user `aag`, ProxyJump
through the KVM host) and the path variable contains a path, not a password. Do
not echo it or replace it with a credential value. The script builds
`git archive` bytes for the exact commit, stages only fixed `/tmp/ehf-<pid>`
paths, then creates only the exact `EHFApplications` database when it is
absent. The release helper applies its checksum-bound migrations and the
twenty-three fixed validators before isolated SQL principal verification and
application-login setup. It refuses other database names and unexpected
migration state. Only after all installer and repository tests pass does it
change `/opt/ehf/current`, then it checks loopback readiness. A failed
post-activation check restores the prior immutable release link and the prior
service state automatically.

## Explicit rollback

First identify the previous immutable commit from a trusted deployment record
or from the validated release directory on the `EHF` VM. It must be exactly 40
lowercase hexadecimal characters and match that release's `.commit` marker.

```powershell
$PreviousCommit = '<validated 40-hex previous commit>'
powershell -NoProfile -File scripts\deploy-ehf.ps1 -Rollback $PreviousCommit
powershell -NoProfile -File scripts\verify-ehf.ps1 -ExpectedCommit $PreviousCommit
```

Rollback never extracts an archive, modifies applicant data, enables mail, or
publishes a hostname. It atomically repoints `/opt/ehf/current` to the named
validated immutable release and restarts the service before checking readiness.
