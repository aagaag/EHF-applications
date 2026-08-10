#!/usr/bin/env bash
{ set +x; } 2>/dev/null
set -euo pipefail

readonly expected_database="EHFApplications"
readonly expected_login="ehf_app"
readonly expected_user="ehf_app"
readonly credential_directory="/etc/ehf"
readonly password_file="${credential_directory}/sql-app-password"
readonly sqlcmd="/opt/mssql-tools18/bin/sqlcmd"
readonly helper="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/sql-principal.py"
readonly helper_python="${EHF_SQL_PRINCIPAL_PYTHON:-/opt/ehf/venv/bin/python}"
readonly server="tcp:127.0.0.1,1433"

database="$expected_database"
login="$expected_login"
user="$expected_user"

password_is_safe() {
  [[ "$1" =~ ^[A-Za-z0-9._~-]{48}$ ]] \
    && [[ "$1" =~ [A-Z] ]] \
    && [[ "$1" =~ [a-z] ]] \
    && [[ "$1" =~ [0-9] ]] \
    && [[ "$1" =~ [._~-] ]]
}

fail() {
  printf '%s\n' "$1" >&2
  exit 2
}

while (($#)); do
  case "$1" in
    --validate-password)
      (($# == 2)) || fail "Unexpected EHF SQL password validation option."
      password_is_safe "$2" && exit 0
      fail "Unexpected EHF SQL password format."
      ;;
    --database)
      (($# >= 2)) || fail "Unexpected incomplete EHF SQL database option."
      database="$2"
      shift 2
      ;;
    --login)
      (($# >= 2)) || fail "Unexpected incomplete EHF SQL login option."
      login="$2"
      shift 2
      ;;
    --user)
      (($# >= 2)) || fail "Unexpected incomplete EHF SQL user option."
      user="$2"
      shift 2
      ;;
    *) fail "Unexpected EHF SQL setup option." ;;
  esac
done

if [[ "$database" != "$expected_database" || "$login" != "$expected_login" || "$user" != "$expected_user" ]]; then
  fail "Unexpected EHF SQL database, login, or user name."
fi
[[ "$EUID" -eq 0 ]] || fail "Run the EHF SQL setup as root."
[[ -x "$sqlcmd" ]] || fail "The required SQL command-line client is unavailable."
[[ -x "$helper_python" && -f "$helper" ]] || fail "The required pinned EHF SQL helper runtime is unavailable."
"$helper_python" -c 'import pyodbc' >/dev/null 2>&1 || fail "The required pinned EHF SQL helper runtime is unavailable."

admin_password_file="${EHF_SQL_ADMIN_PASSWORD_FILE:-}"
if [[ -z "$admin_password_file" || -L "$admin_password_file" || ! -f "$admin_password_file" || ! -s "$admin_password_file" ]]; then
  fail "The protected EHF SQL administrator credential file is unavailable."
fi
if [[ "$(stat -c '%U:%G:%a' "$admin_password_file")" != "root:root:600" ]]; then
  fail "The protected EHF SQL administrator credential file has an unexpected shape."
fi

trap 'unset app_password SQLCMDINI' EXIT
unset SQLCMDINI

run_helper() {
  "$helper_python" "$helper" "$@"
}

inspect_state="$(run_helper inspect-production --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --user "$user")" || fail "EHF SQL principal inspection failed."
case "$inspect_state" in
  ready|unmapped)
    run_helper authenticate-login --server "$server" --database "$database" --login "$login" --credential-file "$password_file" --credential-kind application >/dev/null || fail "The existing EHF SQL login did not authenticate from its protected password file."
    [[ "$inspect_state" == "ready" ]] || fail "The existing EHF SQL login has an unexpected principal state."
    ;;
  absent)
    getent group ehf >/dev/null || groupadd --system ehf
    install -d -o root -g ehf -m 0750 "$credential_directory"
    if [[ -e "$password_file" ]]; then
      [[ ! -L "$password_file" && -f "$password_file" && -s "$password_file" ]] || fail "The new EHF SQL password file has an unexpected shape."
      [[ "$(stat -c '%U:%G:%a' "$password_file")" == "root:ehf:640" ]] || fail "The new EHF SQL password file has unexpected ownership or mode."
    else
      umask 0077
      app_password="Aa1._~$(openssl rand -hex 21)"
      password_is_safe "$app_password" || fail "EHF SQL password generation failed."
      printf '%s' "$app_password" >"$password_file"
      chown root:ehf "$password_file"
      chmod 0640 "$password_file"
    fi
    run_helper create-production-login --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --credential-file "$password_file" >/dev/null || fail "EHF SQL login creation failed."
    run_helper map-production-user --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --user "$user" >/dev/null || fail "EHF SQL user mapping failed."
    run_helper authenticate-login --server "$server" --database "$database" --login "$login" --credential-file "$password_file" --credential-kind application >/dev/null || fail "The new EHF SQL login did not authenticate from its protected password file."
    [[ "$(run_helper inspect-production --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --user "$user")" == "ready" ]] || fail "The new EHF SQL login has an unexpected principal state."
    ;;
  *) fail "The EHF SQL principal inspection result is unexpected." ;;
esac

app_password="$(<"$password_file")"
password_is_safe "$app_password" || fail "The EHF SQL password file has an unexpected format."
if ! SQLCMDPASSWORD="$app_password" "$sqlcmd" -S "$server" -U "$login" -C -X -I -d "$database" -b -V 11 -r 1 -Q 'EXEC dbo.RuntimeHealth;' >/dev/null 2>&1; then
  fail "The EHF runtime login verification failed without credential details."
fi

printf '%s\n' 'EHF SQL runtime login is configured.'
