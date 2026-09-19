#!/usr/bin/env bash
# Restore the EHF state onto the dedicated VM from a migration bundle.
#
#   restore-ehf-state.sh <bundle-dir> configuration   # service account + protected config
#   restore-ehf-state.sh <bundle-dir> database        # SQL database from the .bak file
#   restore-ehf-state.sh <bundle-dir> documents       # encrypted document store
#
# The bundle contains EHFApplications.bak, ehf-secrets.tgz and ehf-documents.tgz.
# The bundle's sql-admin-password is deliberately NOT used: each host holds its own
# administrator credential, and only the data-encryption keyring must travel with the data.
set -Eeuo pipefail

readonly bundle=${1:?usage: restore-ehf-state.sh <bundle-dir> <configuration|database|documents>}
readonly action=${2:?usage: restore-ehf-state.sh <bundle-dir> <configuration|database|documents>}
readonly config_root=/etc/ehf
readonly service_user=ehf
readonly sqlcmd=/opt/mssql-tools18/bin/sqlcmd
readonly admin_credential=$config_root/sql-admin-password
readonly runtime_backup_dir=/var/opt/mssql/backup-migration

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || fail 'run as root inside the EHF VM'
[[ $(hostname -s) == ehf ]] || fail 'this script restores onto the EHF VM only'
[[ -d $bundle ]] || fail "bundle directory not found: $bundle"
sqlsa() { SQLCMDPASSWORD="$(cat "$admin_credential")" "$sqlcmd" -S tcp:127.0.0.1,1433 -U sa -C -X -I -b -V 11 -r 1 "$@"; }

case "$action" in
configuration)
  install -d -m 0750 -o root -g root "$config_root"
  [[ -s $admin_credential ]] || fail 'the host administrator credential is missing'
  if ! getent group "$service_user" >/dev/null; then
    /usr/sbin/useradd --system --user-group --home-dir /nonexistent \
      --shell /usr/sbin/nologin "$service_user"
  fi
  service_gid=$(getent group "$service_user" | cut -d: -f3)
  scratch=$(mktemp -d)
  trap 'rm -rf -- "$scratch"' EXIT
  tar -xzf "$bundle/ehf-secrets.tgz" -C "$scratch"
  for name in document-keyring session-pepper otp-pepper turnstile-secret ehf.env; do
    [[ -f $scratch/$name ]] || fail "the migration bundle is missing $name"
    install -m 0640 -o root -g "$service_user" "$scratch/$name" "$config_root/$name"
  done
  printf 'configuration restored: %s (root:%s 0640)\n' "$config_root" "$service_user"
  ;;
database)
  [[ -f $bundle/EHFApplications.bak ]] || fail 'the migration bundle has no database backup'
  install -d -m 0700 -o mssql -g mssql "$runtime_backup_dir"
  install -m 0640 -o mssql -g mssql "$bundle/EHFApplications.bak" \
    "$runtime_backup_dir/EHFApplications.bak"
  sqlsa -Q "RESTORE DATABASE [EHFApplications] FROM DISK = N'$runtime_backup_dir/EHFApplications.bak' \
WITH REPLACE, RECOVERY, \
MOVE N'EHFApplications' TO N'/var/opt/mssql/data/EHFApplications.mdf', \
MOVE N'EHFApplications_log' TO N'/var/opt/mssql/data/EHFApplications_log.ldf', \
STATS = 25;" >/dev/null
  sqlsa -d EHFApplications -h -1 -W -Q "SET NOCOUNT ON;
SELECT 'migration=' + CONVERT(varchar(10), MAX(MigrationVersion)) FROM dbo.SchemaMigration;
SELECT 'applications=' + CONVERT(varchar(10), COUNT(*)) FROM dbo.Application;
SELECT 'documentVersions=' + CONVERT(varchar(10), COUNT(*)) FROM dbo.DocumentVersion;"
  ;;
documents)
  [[ -f $bundle/ehf-documents.tgz ]] || fail 'the migration bundle has no document archive'
  getent passwd "$service_user" >/dev/null || fail 'the EHF service account does not exist yet'
  install -d -m 0750 -o "$service_user" -g "$service_user" /var/lib/ehf/documents /var/lib/ehf/quarantine
  tar -xzf "$bundle/ehf-documents.tgz" -C /var/lib/ehf
  chown -R "$service_user:$service_user" /var/lib/ehf/documents /var/lib/ehf/quarantine
  chmod 0750 /var/lib/ehf/documents /var/lib/ehf/quarantine
  printf 'documents restored: %s files\n' "$(find /var/lib/ehf/documents -type f | wc -l)"
  ;;
*)
  fail "unknown action: $action"
  ;;
esac
