#!/usr/bin/env bash
# Provision the dedicated EHF guest baseline: SQL Server 2025 plus client tooling.
#
# Idempotent and host-independent: it only depends on the Microsoft package
# repositories and on /var/opt/mssql/data being the mounted data volume.
set -Eeuo pipefail

readonly mssql_data=/var/opt/mssql/data
readonly config_root=/etc/ehf
readonly admin_credential=$config_root/sql-admin-password
readonly sqlcmd=/opt/mssql-tools18/bin/sqlcmd

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || fail 'run as root inside the EHF VM'
[[ $(hostname -s) == ehf ]] || fail 'this script provisions the EHF VM only'
[[ $(findmnt -no FSTYPE --target "$mssql_data") == ext4 ]] || fail "$mssql_data is not the dedicated data volume"

install -d -m 0755 /usr/share/keyrings
if [[ ! -s /usr/share/keyrings/microsoft-prod.gpg ]]; then
  curl -fsSL https://packages.microsoft.com/keys/microsoft.asc |
    gpg --batch --yes --dearmor -o /usr/share/keyrings/microsoft-prod.gpg
fi
curl -fsSL -o /etc/apt/sources.list.d/mssql-server-2025.list \
  https://packages.microsoft.com/config/ubuntu/24.04/mssql-server-2025.list
curl -fsSL -o /etc/apt/sources.list.d/mssql-prod.list \
  https://packages.microsoft.com/config/ubuntu/24.04/prod.list

export DEBIAN_FRONTEND=noninteractive
apt-get update
ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
  mssql-server mssql-tools18 msodbcsql18 unixodbc-dev
[[ -x $sqlcmd ]] || fail 'sqlcmd was not installed where the deployment expects it'

install -d -m 0750 -o root -g root "$config_root"
if [[ ! -s $admin_credential ]]; then
  ( umask 077; python3 - <<'PY'
import secrets
import string
import sys

alphabet = string.ascii_letters + string.digits
sys.stdout.write("Aa1._" + "".join(secrets.choice(alphabet) for _ in range(40)))
PY
  ) > "$admin_credential"
  chmod 0600 "$admin_credential"
fi
# The credential reader rejects any trailing newline, so verify the shape explicitly.
[[ -f $admin_credential ]] || fail 'the administrator credential file is unavailable'
[[ $(wc -c < "$admin_credential") -eq 45 ]] || fail 'the administrator credential file has an unexpected length'
[[ $(tail -c 1 "$admin_credential" | od -An -c | tr -d ' \n') != '\n' ]] ||
  fail 'the administrator credential file must not end with a newline'

if ! grep -qi 'accepteula' /var/opt/mssql/mssql.conf 2>/dev/null; then
  MSSQL_SA_PASSWORD="$(cat "$admin_credential")" MSSQL_PID=Developer ACCEPT_EULA=Y \
    /opt/mssql/bin/mssql-conf -n setup
fi

# SQL Server must never accept connections from another host: the portal talks to it
# over the loopback interface only, and verify-ehf.ps1 asserts exactly that.
if [[ $(/opt/mssql/bin/mssql-conf get network.ipaddress 2>/dev/null || true) != 127.0.0.1 ]]; then
  /opt/mssql/bin/mssql-conf set network.ipaddress 127.0.0.1
  # Re-binding while the previous listener still holds the port makes the engine fail
  # its start, so release the port and clear systemd's start-limit counter first.
  systemctl stop mssql-server >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    ss -ltn '( sport = :1433 )' | grep -q ':1433' || break
    sleep 1
  done
  systemctl reset-failed mssql-server >/dev/null 2>&1 || true
fi

# Fail closed at boot: SQL Server must never initialize before its data volume is mounted.
install -d -m 0755 /etc/systemd/system/mssql-server.service.d
cat > /etc/systemd/system/mssql-server.service.d/10-ehf-data-volume.conf <<'UNIT'
[Unit]
RequiresMountsFor=/var/opt/mssql/data
After=var-opt-mssql-data.mount
UNIT
chmod 0644 /etc/systemd/system/mssql-server.service.d/10-ehf-data-volume.conf
systemctl daemon-reload

install -d -m 0770 -o mssql -g mssql "$mssql_data"
systemctl enable --now mssql-server >/dev/null 2>&1 || true
started=no
for _ in $(seq 1 60); do
  if SQLCMDPASSWORD="$(cat "$admin_credential")" "$sqlcmd" -S tcp:127.0.0.1,1433 -U sa -C -X -I \
      -Q 'SELECT 1' >/dev/null 2>&1; then
    started=yes
    break
  fi
  sleep 2
done
[[ $started == yes ]] || fail 'SQL Server did not accept connections after installation'
if ! ss -ltn '( sport = :1433 )' | grep -qF '127.0.0.1:1433'; then
  fail 'SQL Server is not listening on the loopback interface'
fi
if ss -ltn '( sport = :1433 )' | grep -qF '0.0.0.0:1433'; then
  fail 'SQL Server must not listen on every interface'
fi
SQLCMDPASSWORD="$(cat "$admin_credential")" "$sqlcmd" -S tcp:127.0.0.1,1433 -U sa -C -X -I -h -1 -W \
  -Q "SET NOCOUNT ON; SELECT 'sql=' + CONVERT(varchar(60), SERVERPROPERTY('ProductVersion')) + ' ' + CONVERT(varchar(20), SERVERPROPERTY('Edition'));"

# Applicant documents are scanned with clamdscan against the daemon socket that
# infra/ehf-clamav.conf names, so the guest has to provide that daemon and socket.
readonly scanner_socket=/run/clamav/clamd.ctl
apt-get install -y --no-install-recommends clamav-daemon clamav-freshclam clamdscan
[[ -x /usr/bin/clamdscan ]] || fail 'clamdscan was not installed where the application expects it'

set_clamd_option() {
  local key=$1 value=$2 file=/etc/clamav/clamd.conf
  if grep -qE "^[#[:space:]]*${key}[[:space:]]" "$file"; then
    sed -i -E "s|^[#[:space:]]*${key}[[:space:]].*|${key} ${value}|" "$file"
  else
    printf '%s %s\n' "$key" "$value" >> "$file"
  fi
}
set_clamd_option LocalSocket "$scanner_socket"
# The portal runs as the unprivileged ehf account, which is not in the clamav group.
set_clamd_option LocalSocketMode 0666

systemctl enable clamav-daemon clamav-freshclam >/dev/null 2>&1 || true
systemctl restart clamav-freshclam >/dev/null 2>&1 || true
systemctl restart clamav-daemon
socket_ready=no
for _ in $(seq 1 60); do
  if [[ -S $scanner_socket ]]; then
    socket_ready=yes
    break
  fi
  sleep 2
done
[[ $socket_ready == yes ]] || fail "the ClamAV daemon did not create $scanner_socket"

# Prove that a clean file scans before the portal is allowed to rely on the daemon.
probe=$(mktemp)
printf 'ehf scanner probe\n' > "$probe"
/usr/bin/clamdscan --version >/dev/null || fail 'clamdscan is not executable'
/usr/bin/clamdscan --fdpass --no-summary "$probe" >/dev/null ||
  fail 'clamdscan could not scan a clean probe file through the daemon socket'
rm -f "$probe"

printf 'provision-ehf-guest: SQL Server 2025 ready; administrator credential at %s\n' "$admin_credential"
printf 'provision-ehf-guest: ClamAV daemon ready on %s for clamdscan\n' "$scanner_socket"
