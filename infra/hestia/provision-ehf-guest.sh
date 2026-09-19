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
SQLCMDPASSWORD="$(cat "$admin_credential")" "$sqlcmd" -S tcp:127.0.0.1,1433 -U sa -C -X -I -h -1 -W \
  -Q "SET NOCOUNT ON; SELECT 'sql=' + CONVERT(varchar(60), SERVERPROPERTY('ProductVersion')) + ' ' + CONVERT(varchar(20), SERVERPROPERTY('Edition'));"
printf 'provision-ehf-guest: SQL Server 2025 ready; administrator credential at %s\n' "$admin_credential"
