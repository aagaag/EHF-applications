# EHF VM on Hestia

The EHF portal runs in a dedicated, self-contained virtual machine named **EHF** on the
Hestia KVM/libvirt host. Everything the application needs — the SQL Server instance, the
release directory, the document store and the database files — lives inside that one VM,
so the whole workload can be moved to another KVM host by copying two disk images.

## Layout

| Item | Value |
|---|---|
| libvirt domain | `EHF` (autostart) |
| Guest hostname | `ehf` |
| Management address | `192.168.254.2` on libvirt network `ehf-net` (`virbr-ehf`, NAT) |
| Operator access | `ssh ehf-hestia` (user `aag`, ProxyJump through the KVM host) |
| OS disk | `/var/lib/libvirt/images/EHF/ehf-os.qcow2` (40 GiB) |
| Data disk | `/var/lib/libvirt/images/EHF/ehf-data.qcow2` (20 GiB, ext4 label `ehf-data`) |
| Cloud-init seed | `/var/lib/libvirt/images/EHF/ehf-seed.iso` |
| SQL Server | 2025 (Developer), loopback `127.0.0.1:1433`, data directory `/var/opt/mssql/data` |
| Application release | `/opt/ehf/current` → `/opt/ehf/r/<40-hex commit>` |
| Unit and site | `/etc/systemd/system/ehf.service`, `/etc/nginx/sites-available/ehf` |
| Host ingress path | `/etc/systemd/system/hestia-ehf-network.service` (chain `ISAB_EHF_FWD`: `192.168.251.2` → `192.168.254.2:80`) |
| Protected configuration | `/etc/ehf/ehf.env` plus `document-keyring`, `session-pepper`, `otp-pepper`, `turnstile-secret`, `sql-admin-password`, `sql-app-password` |
| Document store | `/var/lib/ehf/documents`, `/var/lib/ehf/quarantine` (encrypted objects) |

Ingress is unchanged in shape: the Cloudflare tunnel terminates on `isab-proxy01`, whose
EHF server block proxies to the VM's port 80. The VM itself never listens on the public
internet and holds no credentials for the edge. Because libvirt rejects new connections
between its own networks, the host carries one small filter chain for that single flow,
installed and reapplied by `infra/hestia/hestia-ehf-network.sh` through
`hestia-ehf-network.service`.

## Address and network rationale

`ehf-net` is a Hestia-local management network, exactly the pattern the ISAB retirement
policy allows for a replacement service ("the Hestia location … using the ISAB
`10.100.0.0/22` network **or another documented Hestia-local management network**"). The
guest reaches the ISAB LAN through the host's `10.100.0.10` address, so the portal depends
on no retired network, host or storage endpoint.

## Provisioning from scratch

On the KVM host (root), with the assets in `infra/hestia/`:

```bash
sudo bash infra/hestia/provision-ehf-vm.sh
```

Inside the new VM (root):

```bash
sudo bash provision-ehf-guest.sh              # SQL Server 2025, client tooling and ClamAV
sudo bash restore-ehf-state.sh <bundle> configuration
sudo python3 /usr/local/sbin/ehf-deploy \
  --archive /root/ehf-release-r.tar \
  --commit <40-hex> \
  --sql-admin-credential /etc/ehf/sql-admin-password --apply
sudo systemctl stop ehf.service
sudo bash restore-ehf-state.sh <bundle> database     # restores the data and re-maps the app login
sudo /opt/ehf/current/venv/bin/python /opt/ehf/current/infra/bootstrap-ehf-database.py \
  --admin-credential-file /etc/ehf/sql-admin-password
sudo systemctl start ehf.service
sudo bash restore-ehf-state.sh <bundle> documents
```

The order matters. The deployment helper creates the service account, the writable paths,
the application login, the database objects, the unit and the Nginx site, then activates the
immutable release and waits for `http://127.0.0.1:8087/health/ready`. It must run against a
database it created itself: a database restored *before* the helper exists carries the source
instance's application SID, and the validators (which impersonate the application user) then
fail with SQL error 15517. `restore-ehf-state.sh database` therefore runs after the first
deploy, re-maps the login with `ALTER USER [ehf_app] WITH LOGIN = [ehf_app]`, and the
bootstrap re-runs all twenty-three validators against the restored data.

Two credential-shape rules the helper enforces: the protected credential files must contain
the password only — no trailing newline — and the SQL administrator credential must be
`root:root 0600` (the application credential is `root:ehf 0640`).

## Moving the VM to another host

1. On the destination host, install the assets from this directory and run
   `provision-ehf-vm.sh` once — it defines the `ehf-net` network and the `EHF` domain.
2. Stop the VM on the old host and copy `ehf-os.qcow2` and `ehf-data.qcow2` (both are
   plain qcow2 files; QEMU image conversion or `virt-v2v` is not needed.
3. Replace the two image files on the destination host, start the domain, and confirm
   `systemctl is-active ehf mssql-server nginx` plus `curl -H 'Host: ehf.isab.science'
   http://127.0.0.1:8087/health/ready` inside the guest.
4. Repoint the proxy01 EHF upstream at the new management address.

`EHF_MEMORY_MB`, `EHF_VCPUS`, `EHF_OS_DISK_SIZE`, `EHF_DATA_DISK_SIZE` and
`EHF_BASE_IMAGE` override the defaults in `provision-ehf-vm.sh`; the domain uses
`host-model` CPU so it is not pinned to one host's CPU generation.

## Backup and restore

The state that matters is the database, the documents and the keyring:

```bash
SQLCMDPASSWORD="$(sudo cat /etc/ehf/sql-admin-password)" \
  /opt/mssql-tools18/bin/sqlcmd -S tcp:127.0.0.1,1433 -U sa -C -X -I -b \
  -Q "BACKUP DATABASE [EHFApplications] TO DISK = N'/var/opt/mssql/backup-migration/EHFApplications.bak' WITH INIT, COMPRESSION, CHECKSUM;"
tar -C /var/lib/ehf -czf ehf-documents.tgz documents quarantine
tar -C /etc/ehf -czf ehf-secrets.tgz document-keyring session-pepper otp-pepper turnstile-secret ehf.env
```

Restoring onto a freshly provisioned VM uses `restore-ehf-state.sh` (see above). The
document keyring must travel with the documents: without it the stored objects cannot be
decrypted. The SQL administrator credential is per host and is never copied between hosts.
