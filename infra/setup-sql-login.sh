#!/usr/bin/env bash
{ set +x; } 2>/dev/null
set -euo pipefail

readonly expected_database="EHFApplications"
readonly expected_login="ehf_app"
readonly expected_user="ehf_app"
readonly credential_directory="/etc/ehf"
readonly password_file="${credential_directory}/sql-app-password"
readonly sqlcmd="/opt/mssql-tools18/bin/sqlcmd"

database="$expected_database"
login="$expected_login"
user="$expected_user"

fail() {
  printf '%s\n' "$1" >&2
  exit 2
}

while (($#)); do
  case "$1" in
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
    *)
      fail "Unexpected EHF SQL setup option."
      ;;
  esac
done

if [[ "$database" != "$expected_database" || "$login" != "$expected_login" || "$user" != "$expected_user" ]]; then
  fail "Unexpected EHF SQL database, login, or user name."
fi
if [[ "$EUID" -ne 0 ]]; then
  fail "Run the EHF SQL setup as root."
fi
if [[ ! -x "$sqlcmd" ]]; then
  fail "The required SQL command-line client is unavailable."
fi
if ! getent group ehf >/dev/null; then
  groupadd --system ehf
fi

admin_password_file="${EHF_SQL_ADMIN_PASSWORD_FILE:-}"
if [[ -z "$admin_password_file" || -L "$admin_password_file" || ! -f "$admin_password_file" || ! -s "$admin_password_file" ]]; then
  fail "The protected EHF SQL administrator credential file is unavailable."
fi
if [[ "$(stat -c '%U:%G:%a' "$admin_password_file")" != "root:root:600" ]]; then
  fail "The protected EHF SQL administrator credential file has an unexpected shape."
fi

admin_password="$(<"$admin_password_file")"
app_password=""
trap 'unset admin_password app_password EHF_SQL_APP_PASSWORD' EXIT

run_admin_sql() {
  local target_database="$1"
  local output
  if ! output="$(SQLCMDPASSWORD="$admin_password" "$sqlcmd" \
    -S 127.0.0.1:1433 -U sa -C -d "$target_database" -b -V 11 -r 1 2>&1)"; then
    unset output
    fail "EHF SQL administration failed without credential details."
  fi
  unset output
}

run_runtime_health() {
  local output
  if ! output="$(SQLCMDPASSWORD="$app_password" "$sqlcmd" \
    -S 127.0.0.1:1433 -U "$login" -C -d "$database" -b -V 11 -r 1 \
    -Q 'EXEC dbo.RuntimeHealth;' 2>&1)"; then
    unset output
    fail "The EHF runtime login verification failed without credential details."
  fi
  unset output
}

run_admin_sql master <<'SQL'
IF DB_ID(N'EHFApplications') IS NULL
    THROW 51600, 'The EHF database is missing.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM EHFApplications.dbo.SchemaMigration
    WHERE MigrationVersion = 5
      AND MigrationName = N'application_permissions'
)
    THROW 51601, 'The EHF permissions migration is not applied.', 1;
IF SUSER_ID(N'ehf_app') IS NOT NULL
AND
(
    NOT EXISTS
    (
        SELECT 1
        FROM sys.server_principals
        WHERE name = N'ehf_app'
          AND type_desc = N'SQL_LOGIN'
          AND is_disabled = 0
          AND default_database_name = N'EHFApplications'
    )
    OR EXISTS
    (
        SELECT 1
        FROM sys.server_role_members AS membership
        INNER JOIN sys.server_principals AS member_row
            ON member_row.principal_id = membership.member_principal_id
        WHERE member_row.name = N'ehf_app'
    )
)
    THROW 51602, 'The existing EHF SQL login has an unexpected shape.', 1;
SQL

install -d -m 0750 -o root -g ehf "$credential_directory"
if [[ -e "$password_file" ]]; then
  if [[ -L "$password_file" || ! -f "$password_file" || ! -s "$password_file" ]]; then
    fail "The existing EHF SQL password file has an unexpected shape."
  fi
  if [[ "$(stat -c '%U:%G:%a' "$password_file")" != "root:ehf:640" ]]; then
    fail "The existing EHF SQL password file has unexpected ownership or mode."
  fi
else
  umask 0077
  app_password="$(openssl rand -base64 48 | tr -d '\n')"
  [[ -n "$app_password" ]] || fail "EHF SQL password generation failed."
  printf '%s' "$app_password" >"$password_file"
  chown root:ehf "$password_file"
  chmod 0640 "$password_file"
fi
app_password="$(<"$password_file")"

export EHF_SQL_APP_PASSWORD="$app_password"
run_admin_sql master <<'SQL'
DECLARE @LoginName sysname = N'ehf_app';
DECLARE @Password nvarchar(256) = N'$(EHF_SQL_APP_PASSWORD)';
DECLARE @LoginSid varbinary(85);

IF NULLIF(@Password, N'') IS NULL
    THROW 51603, 'The EHF SQL password is unavailable.', 1;

IF SUSER_ID(@LoginName) IS NULL
BEGIN
    DECLARE @CreateLogin nvarchar(max) =
        N'CREATE LOGIN ' + QUOTENAME(@LoginName) +
        N' WITH PASSWORD = N' + QUOTENAME(@Password, N'''') +
        N', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF, '
        + N'DEFAULT_DATABASE = [EHFApplications];';
    EXEC (@CreateLogin);
END;

SELECT @LoginSid = sid
FROM sys.server_principals
WHERE name = @LoginName
  AND type_desc = N'SQL_LOGIN'
  AND is_disabled = 0
  AND default_database_name = N'EHFApplications';
IF @LoginSid IS NULL
    THROW 51604, 'The EHF SQL login has an unexpected shape.', 1;
IF EXISTS
(
    SELECT 1
    FROM sys.server_role_members AS membership
    INNER JOIN sys.server_principals AS member_row
        ON member_row.principal_id = membership.member_principal_id
    WHERE member_row.name = @LoginName
)
    THROW 51605, 'The EHF SQL login has a server role.', 1;

IF USER_ID(@LoginName) IS NULL
    EXEC(N'CREATE USER [ehf_app] FOR LOGIN [ehf_app];');
IF NOT EXISTS
(
    SELECT 1
    FROM sys.database_principals
    WHERE name = @LoginName
      AND sid = @LoginSid
)
    THROW 51606, 'The master EHF denial user has an unexpected shape.', 1;
DENY CONNECT TO [ehf_app];
DENY ALTER ANY LOGIN, ALTER ANY SERVER ROLE, VIEW ANY DATABASE,
    VIEW SERVER STATE, VIEW ANY DEFINITION, CONTROL SERVER
    TO [ehf_app];

USE [EHFApplications];
DECLARE @DatabaseUserSid varbinary(85);
DECLARE @AuthenticationType nvarchar(60);
SELECT
    @DatabaseUserSid = sid,
    @AuthenticationType = authentication_type_desc
FROM sys.database_principals
WHERE name = N'ehf_app'
  AND type_desc = N'SQL_USER';
IF @AuthenticationType IS NULL
    THROW 51607, 'The EHF database user is missing or unexpected.', 1;
IF @AuthenticationType = N'NONE'
    ALTER USER [ehf_app] WITH LOGIN = [ehf_app];
ELSE IF @DatabaseUserSid <> @LoginSid
    THROW 51608, 'The EHF database user maps to another login.', 1;

IF EXISTS
(
    SELECT 1
    FROM sys.database_role_members AS membership
    INNER JOIN sys.database_principals AS role_row
        ON role_row.principal_id = membership.role_principal_id
    INNER JOIN sys.database_principals AS member_row
        ON member_row.principal_id = membership.member_principal_id
    WHERE member_row.name = N'ehf_app'
      AND role_row.name NOT IN (N'public', N'EHFApplicationRuntime')
)
    THROW 51609, 'The EHF database user has an unexpected role.', 1;
IF NOT EXISTS
(
    SELECT 1
    FROM sys.database_role_members AS membership
    WHERE membership.role_principal_id = DATABASE_PRINCIPAL_ID(N'EHFApplicationRuntime')
      AND membership.member_principal_id = DATABASE_PRINCIPAL_ID(N'ehf_app')
)
    THROW 51610, 'The EHF database user is missing its expected runtime role.', 1;
SQL
unset EHF_SQL_APP_PASSWORD
run_runtime_health

printf '%s\n' 'EHF SQL runtime login is configured.'
