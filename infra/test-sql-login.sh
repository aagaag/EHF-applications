#!/usr/bin/env bash
{ set +x; } 2>/dev/null
set -euo pipefail

readonly sqlcmd="/opt/mssql-tools18/bin/sqlcmd"
readonly project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly migration_directory="${project_root}/database/migrations"
readonly validation_directory="${project_root}/database/tests"
readonly helper="${project_root}/infra/sql-principal.py"
readonly helper_python="${EHF_SQL_PRINCIPAL_PYTHON:-/opt/ehf/venv/bin/python}"
readonly server="tcp:127.0.0.1,1433"

run_id="$(openssl rand -hex 12)"
database="EHFApplications_Test_sqlperm_${run_id}"
peer_database="EHFApplications_Test_sqlperm_peer_${run_id}"
login="ehf_app_test_${run_id}"
user="${login}"
created_database=0
created_peer_database=0
created_login=0
admin_password=""
test_password=""
test_password_file=""

fail() {
  printf '%s\n' "$1" >&2
  exit 2
}

while (($#)); do
  case "$1" in
    --database)
      (($# >= 2)) || fail "Unexpected incomplete isolated SQL database option."
      database="$2"
      peer_database="${database/EHFApplications_Test_sqlperm_/EHFApplications_Test_sqlperm_peer_}"
      shift 2
      ;;
    --login)
      (($# >= 2)) || fail "Unexpected incomplete isolated SQL login option."
      login="$2"
      user="$2"
      shift 2
      ;;
    --user)
      (($# >= 2)) || fail "Unexpected incomplete isolated SQL user option."
      user="$2"
      shift 2
      ;;
    *) fail "Unexpected isolated SQL verification option." ;;
  esac
done

if [[ ! "$database" =~ ^EHFApplications_Test_sqlperm_[a-f0-9]{24}$ ]] || [[ ! "$peer_database" =~ ^EHFApplications_Test_sqlperm_peer_[a-f0-9]{24}$ ]] || [[ ! "$login" =~ ^ehf_app_test_[a-f0-9]{24}$ ]] || [[ "$user" != "$login" ]] || [[ "${database##*_}" != "${login##*_}" ]] || [[ "${database##*_}" != "${peer_database##*_}" ]]; then
  fail "Unexpected isolated EHF SQL database, login, or user name."
fi
[[ "$EUID" -eq 0 ]] || fail "Run the isolated EHF SQL verification as root."
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
admin_password="$(<"$admin_password_file")"
test_password="Aa1._~$(openssl rand -hex 21)"
[[ "$test_password" =~ ^[A-Za-z0-9._~-]{48}$ ]] || fail "Isolated SQL password generation failed."
umask 0077
test_password_file="$(mktemp)"
printf '%s' "$test_password" >"$test_password_file"
chown root:root "$test_password_file"
chmod 0600 "$test_password_file"
trap 'unset admin_password test_password SQLCMDINI; rm -f "$test_password_file"' EXIT
unset SQLCMDINI

run_helper() { "$helper_python" "$helper" "$@"; }

run_admin_sql() {
  local target_database="$1"
  shift
  SQLCMDPASSWORD="$admin_password" "$sqlcmd" -S "$server" -U sa -C -X -I -d "$target_database" -b -V 11 -r 1 "$@"
}

run_runtime_sql() {
  local target_database="$1"
  shift
  SQLCMDPASSWORD="$test_password" "$sqlcmd" -S "$server" -U "$login" -C -X -I -d "$target_database" -b -V 11 -r 1 "$@"
}

cleanup() {
  local status=$?
  local cleanup_failed=0
  set +e
  if ((created_database || created_peer_database || created_login)); then
    run_helper cleanup-test-targets --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --peer-database "$peer_database" --login "$login" >/dev/null 2>&1 || cleanup_failed=1
    run_helper verify-test-cleanup --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --peer-database "$peer_database" --login "$login" >/dev/null 2>&1 || cleanup_failed=1
  fi
  if ((cleanup_failed)); then
    unset admin_password test_password SQLCMDINI
    rm -f "$test_password_file"
    printf '%s\n' 'Cleanup failed; isolated EHF SQL verification is unsuccessful.' >&2
    exit 3
  fi
  unset admin_password test_password SQLCMDINI
  rm -f "$test_password_file"
  exit "$status"
}
trap cleanup EXIT

run_helper create-test-database --server "$server" --admin-credential-file "$admin_password_file" --database "$database" >/dev/null || fail "The isolated primary database creation failed."
created_database=1
run_helper create-test-database --server "$server" --admin-credential-file "$admin_password_file" --database "$peer_database" >/dev/null || fail "The isolated peer database creation failed."
created_peer_database=1

migration_files=(001_database_contract.sql 002_application_core.sql 003_audit_and_preferences.sql 004_audit_and_preference_hardening.sql 005_application_permissions.sql)
for migration_file in "${migration_files[@]}"; do
  migration_path="${migration_directory}/${migration_file}"
  [[ -f "$migration_path" ]] || fail "The isolated EHF migration set is incomplete."
  run_admin_sql "$database" -i "$migration_path" >/dev/null 2>&1 || fail "The isolated EHF migration ${migration_file} failed without credential details."
  run_helper record-test-migration --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --migration-file "$migration_file" >/dev/null || fail "The isolated EHF migration record failed."
done

for validation_file in 001_validate_database_contract.sql 002_validate_application_core.sql 003_validate_audit_and_preferences.sql 004_validate_audit_and_preference_hardening.sql 005_validate_application_permissions.sql; do
  validation_path="${validation_directory}/${validation_file}"
  [[ -f "$validation_path" ]] || fail "The isolated EHF validator set is incomplete."
  run_admin_sql "$database" -i "$validation_path" >/dev/null 2>&1 || fail "The isolated EHF SQL validator ${validation_file} failed without credential details."
done

run_helper create-test-login --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --credential-file "$test_password_file" >/dev/null || fail "The isolated test login creation failed."
created_login=1
run_helper map-test-user --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --user "$user" >/dev/null || fail "The isolated test user mapping failed."
run_helper authenticate-login --server "$server" --database "$database" --login "$login" --credential-file "$test_password_file" --credential-kind test >/dev/null || fail "The isolated test login authentication failed."

run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated runtime health probe failed."
DECLARE @Health TABLE (IsReady bit NOT NULL);
INSERT @Health EXEC dbo.RuntimeHealth;
IF NOT EXISTS (SELECT 1 FROM @Health WHERE IsReady = 1) THROW 51640, 'Runtime health failed.', 1;
SQL

run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated runtime preference transaction probe failed."
BEGIN TRANSACTION;
DECLARE @PreferenceResult TABLE (UserPreferenceId uniqueidentifier NOT NULL, IdentityKey nvarchar(255) NOT NULL, Email nvarchar(320) NOT NULL, DisplayName nvarchar(320) NOT NULL, Skin varchar(24) NOT NULL, InvertColors bit NOT NULL, CompactDensity bit NOT NULL, ReduceMotion bit NOT NULL, UpdatedAtUtc datetime2(7) NOT NULL, RowVersion binary(8) NOT NULL);
INSERT @PreferenceResult EXEC dbo.SetUserPreference @IdentityKey=N'isolated-runtime-validator', @Email=N'validator@example.invalid', @DisplayName=N'Isolated runtime validator', @Skin='blue', @InvertColors=0, @CompactDensity=1, @ReduceMotion=0, @ActorIdentity=N'isolated-runtime-validator';
IF @@TRANCOUNT <> 1 THROW 51641, 'Preference transaction changed.', 1;
ROLLBACK TRANSACTION;
SQL

run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated protected-table denial probe failed."
BEGIN TRY SELECT TOP (1) UserPreferenceId FROM dbo.UserPreference; THROW 51645, 'Protected read succeeded.', 1; END TRY BEGIN CATCH IF ERROR_NUMBER() = 51645 THROW; IF ERROR_NUMBER() <> 229 THROW; END CATCH;
SQL

run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated runtime server-permission baseline failed."
BEGIN TRY DELETE FROM dbo.UserPreference WHERE 1=0; THROW 51646, 'Protected delete succeeded.', 1; END TRY BEGIN CATCH IF ERROR_NUMBER() = 51646 THROW; IF ERROR_NUMBER() <> 229 THROW; END CATCH;
IF COALESCE(HAS_PERMS_BY_NAME(NULL, NULL, N'ALTER ANY LOGIN'), 0) <> 0 THROW 51656, 'ALTER ANY LOGIN granted.', 1;
IF COALESCE(HAS_PERMS_BY_NAME(NULL, NULL, N'ALTER ANY SERVER ROLE'), 0) <> 0 THROW 51657, 'ALTER ANY SERVER ROLE granted.', 1;
SQL

run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated server-role denial probe failed."
BEGIN TRY
    DECLARE @RoleCommand nvarchar(max) = N'ALTER SERVER ROLE [sysadmin] ADD MEMBER ' + QUOTENAME(SUSER_SNAME()) + N';';
    EXEC(@RoleCommand);
    THROW 51652, 'Server role change succeeded.', 1;
END TRY BEGIN CATCH IF ERROR_NUMBER() = 51652 THROW; IF ERROR_NUMBER() <> 15151 THROW; END CATCH;
SQL

run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated login-alteration denial probe failed."
BEGIN TRY
    DECLARE @LoginCommand nvarchar(max) = N'ALTER LOGIN ' + QUOTENAME(SUSER_SNAME()) + N' DISABLE;';
    EXEC(@LoginCommand);
    THROW 51653, 'Login alteration succeeded.', 1;
END TRY BEGIN CATCH IF ERROR_NUMBER() = 51653 THROW; IF ERROR_NUMBER() <> 15151 THROW; END CATCH;
SQL

run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated self-password recovery probe failed."
BEGIN TRY
    DECLARE @SelfPasswordCommand nvarchar(max) = N'ALTER LOGIN ' + QUOTENAME(SUSER_SNAME()) + N' WITH PASSWORD = ''AbcdEFGHijklMNOPqrstUVWXyz0123456789._~-AbcdEFGH'' OLD_PASSWORD = ''wrong-old-password'';';
    EXEC(@SelfPasswordCommand);
    THROW 51658, 'Self password change succeeded.', 1;
END TRY BEGIN CATCH IF ERROR_NUMBER() = 51658 THROW; END CATCH;
SQL

run_helper exercise-test-status --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --credential-file "$test_password_file" >/dev/null || fail "The real runtime status/audit probe failed."

if run_runtime_sql "$peer_database" <<'SQL' >/dev/null 2>&1
SELECT TOP (1) name FROM sys.tables;
SQL
then
  fail "The runtime login read the isolated peer database."
fi

run_admin_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The rollback audit probe failed."
IF EXISTS (SELECT 1 FROM dbo.UserPreference AS preference_row INNER JOIN dbo.AuditEvent AS audit_row ON audit_row.EntityId=preference_row.UserPreferenceId WHERE preference_row.IdentityKey=N'isolated-runtime-validator' AND audit_row.EventType='USER_PREFERENCE_SET') THROW 51655, 'Preference audit did not roll back.', 1;
SQL

printf '%s\n' 'PASS isolated EHF SQL permission boundary.'
