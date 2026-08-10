#!/usr/bin/env bash
{ set +x; } 2>/dev/null
set -euo pipefail

readonly expected_database="EHFApplications"
readonly expected_login="ehf_app"
readonly expected_user="ehf_app"
readonly credential_directory="/etc/ehf"
readonly password_file="${credential_directory}/sql-app-password"
readonly sqlcmd="/opt/mssql-tools18/bin/sqlcmd"
readonly project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly helper="${project_root}/infra/sql-principal.py"
readonly helper_python="${EHF_SQL_PRINCIPAL_PYTHON:-/opt/ehf/current/venv/bin/python}"
readonly server="tcp:127.0.0.1,1433"

database="$expected_database"
login="$expected_login"
user="$expected_user"

fail() { printf '%s\n' "$1" >&2; exit 2; }

while (($#)); do
  case "$1" in
    --database) (($# >= 2)) || fail "Unexpected incomplete EHF SQL database option."; database="$2"; shift 2 ;;
    --login) (($# >= 2)) || fail "Unexpected incomplete EHF SQL login option."; login="$2"; shift 2 ;;
    --user) (($# >= 2)) || fail "Unexpected incomplete EHF SQL user option."; user="$2"; shift 2 ;;
    *) fail "Unexpected EHF SQL setup option." ;;
  esac
done

[[ "$database" == "$expected_database" && "$login" == "$expected_login" && "$user" == "$expected_user" ]] || fail "Unexpected EHF SQL database, login, or user name."
[[ "$EUID" -eq 0 ]] || fail "Run the EHF SQL setup as root."
[[ -x "$sqlcmd" ]] || fail "The required SQL command-line client is unavailable."

secure_regular() {
  local candidate="$1" resolved owner mode parent
  resolved="$(readlink -f -- "$candidate")" || return 1
  [[ -f "$resolved" && ! -L "$resolved" ]] || return 1
  owner="$(stat -c '%u' -- "$resolved")"; mode="$(stat -c '%a' -- "$resolved")"
  [[ "$owner" == 0 && $((8#$mode & 8#022)) -eq 0 ]] || return 1
  parent="$(dirname -- "$resolved")"
  while [[ "$parent" != / ]]; do
    owner="$(stat -c '%u' -- "$parent")"; mode="$(stat -c '%a' -- "$parent")"
    [[ "$owner" == 0 && $((8#$mode & 8#022)) -eq 0 ]] || return 1
    parent="$(dirname -- "$parent")"
  done
}

validate_runtime() {
  if [[ "${EHF_SQL_TEST_MODE:-}" == 1 ]]; then
    [[ -x "$helper_python" && -f "$helper" ]] || return 1
    "$helper_python" -c 'import pyodbc' >/dev/null 2>&1
    return
  fi
  local release helper_resolved python_resolved
  release="$(readlink -f -- /opt/ehf/current)" || return 1
  [[ "$release" =~ ^/opt/ehf/r/[0-9a-f]{40}$ ]] || return 1
  [[ "$helper" == /opt/ehf/current/infra/sql-principal.py && "$helper_python" == /opt/ehf/current/venv/bin/python ]] || return 1
  helper_resolved="$(readlink -f -- "$helper")"; python_resolved="$(readlink -f -- "$helper_python")"
  [[ "$helper_resolved" == "$release/infra/sql-principal.py" && "$python_resolved" == "$release/venv/bin/python" ]] || return 1
  secure_regular "$helper" && secure_regular "$helper_python" && "$helper_python" -c 'import pyodbc' >/dev/null 2>&1
}

validate_runtime || fail "The required pinned EHF SQL helper runtime is unavailable."
admin_password_file="${EHF_SQL_ADMIN_PASSWORD_FILE:-}"
[[ -n "$admin_password_file" && -f "$admin_password_file" && ! -L "$admin_password_file" ]] || fail "The protected EHF SQL administrator credential file is unavailable."

trap 'unset app_password SQLCMDINI' EXIT
unset SQLCMDINI
run_helper() { "$helper_python" "$helper" "$@"; }

inspect_state="$(run_helper inspect-production --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --user "$user")" || fail "EHF SQL principal inspection failed."
case "$inspect_state" in
  ready|unmapped)
    run_helper authenticate-login --server "$server" --database "$database" --login "$login" --credential-file "$password_file" --credential-kind application >/dev/null || fail "The existing EHF SQL login did not authenticate from its protected password file."
    if [[ "$inspect_state" == unmapped ]]; then
      run_helper map-production-user --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --user "$user" >/dev/null || fail "The authenticated EHF SQL login could not be mapped safely."
    fi
    ;;
  absent)
    getent group ehf >/dev/null || groupadd --system ehf
    install -d -o root -g ehf -m 0750 "$credential_directory"
    if [[ -e "$password_file" ]]; then
      [[ -f "$password_file" && ! -L "$password_file" ]] || fail "The new EHF SQL password file has an unexpected shape."
      [[ "$(stat -c '%U:%G:%a' "$password_file")" == "root:ehf:640" ]] || fail "The new EHF SQL password file has unexpected ownership or mode."
    else
      umask 0077
      printf 'Aa1._~%s' "$(openssl rand -hex 21)" >"$password_file"
      chown root:ehf "$password_file"; chmod 0640 "$password_file"
    fi
    run_helper create-production-login --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --credential-file "$password_file" >/dev/null || fail "EHF SQL login creation failed."
    run_helper map-production-user --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --user "$user" >/dev/null || fail "EHF SQL user mapping failed."
    run_helper authenticate-login --server "$server" --database "$database" --login "$login" --credential-file "$password_file" --credential-kind application >/dev/null || fail "The new EHF SQL login did not authenticate from its protected password file."
    ;;
  *) fail "The EHF SQL principal inspection result is unexpected." ;;
esac

[[ "$(run_helper inspect-production --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --user "$user" --credential-file "$password_file")" == ready ]] || fail "The EHF SQL login has an unexpected principal state."
app_password="$(<"$password_file")"
if ! SQLCMDPASSWORD="$app_password" "$sqlcmd" -S "$server" -U "$login" -C -X -I -d "$database" -b -V 11 -r 1 -Q 'EXEC dbo.RuntimeHealth;' >/dev/null 2>&1; then
  fail "The EHF runtime login verification failed without credential details."
fi
printf '%s\n' 'EHF SQL runtime login is configured.'
