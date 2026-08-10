#!/usr/bin/env bash
{ set +x; } 2>/dev/null
set -euo pipefail

readonly sqlcmd="/opt/mssql-tools18/bin/sqlcmd"
readonly project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly migration_directory="${project_root}/database/migrations"
readonly validation_directory="${project_root}/database/tests"
readonly helper="${project_root}/infra/sql-principal.py"
readonly helper_python="${EHF_SQL_PRINCIPAL_PYTHON:-/opt/ehf/current/venv/bin/python}"
readonly server="tcp:127.0.0.1,1433"

run_id="$(openssl rand -hex 12)"
run_token=""
database="EHFApplications_Test_sqlperm_${run_id}"
peer_database="EHFApplications_Test_sqlperm_peer_${run_id}"
login="ehf_app_test_${run_id}"
user="$login"
adverse_id="$(openssl rand -hex 12)"
adverse_token=""
adverse_database="EHFApplications_Test_sqlperm_${adverse_id}"
adverse_peer_database="EHFApplications_Test_sqlperm_peer_${adverse_id}"
adverse_login="ehf_app_test_${adverse_id}"
run_token="${run_id}$(openssl rand -hex 4)"
adverse_token="${adverse_id}$(openssl rand -hex 4)"
secret_directory=""
test_password_file=""
adverse_password_file=""
admin_password=""
test_password=""
adverse_password=""
cleanup_complete=0
cleanup_attempted=0

fail() { printf '%s\n' "$1" >&2; exit 2; }

while (($#)); do
  case "$1" in
    --database) (($# >= 2)) || fail "Unexpected incomplete isolated SQL database option."; database="$2"; peer_database="${database/EHFApplications_Test_sqlperm_/EHFApplications_Test_sqlperm_peer_}"; shift 2 ;;
    --login) (($# >= 2)) || fail "Unexpected incomplete isolated SQL login option."; login="$2"; user="$2"; shift 2 ;;
    --user) (($# >= 2)) || fail "Unexpected incomplete isolated SQL user option."; user="$2"; shift 2 ;;
    *) fail "Unexpected isolated SQL verification option." ;;
  esac
done

[[ "$database" =~ ^EHFApplications_Test_sqlperm_[a-f0-9]{24}$ && "$peer_database" =~ ^EHFApplications_Test_sqlperm_peer_[a-f0-9]{24}$ && "$login" =~ ^ehf_app_test_[a-f0-9]{24}$ && "$user" == "$login" && "${database##*_}" == "${peer_database##*_}" && "${database##*_}" == "${login##*_}" ]] || fail "Unexpected isolated EHF SQL database, login, or user name."
[[ "$EUID" -eq 0 ]] || fail "Run the isolated EHF SQL verification as root."
[[ "${EHF_SQL_TEST_MODE:-}" == 1 ]] || fail "The isolated verifier requires explicit test mode."
[[ -x "$sqlcmd" && -x "$helper_python" && -f "$helper" ]] || fail "The required pinned EHF SQL helper runtime is unavailable."
"$helper_python" -c 'import pyodbc' >/dev/null 2>&1 || fail "The required pinned EHF SQL helper runtime is unavailable."
admin_password_file="${EHF_SQL_ADMIN_PASSWORD_FILE:-}"
[[ -n "$admin_password_file" && -f "$admin_password_file" && ! -L "$admin_password_file" ]] || fail "The protected EHF SQL administrator credential file is unavailable."

unset SQLCMDINI
cleanup_owned_targets() {
  local failed=0
  cleanup_attempted=1
  set +e
  [[ -n "$secret_directory" ]] || failed=1
  run_helper cleanup-test-targets --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --peer-database "$peer_database" --login "$login" --run-token "$run_token" --credential-file "$test_password_file" >/dev/null || { printf '%s\n' 'Cleanup stage: current targets.' >&2; failed=1; }
  run_helper verify-test-cleanup --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --peer-database "$peer_database" --login "$login" --run-token "$run_token" >/dev/null 2>&1 || failed=1
  # The seeded peer/login must survive the current-run cleanup before its own cleanup.
  run_helper verify-test-targets-preserved --server "$server" --admin-credential-file "$admin_password_file" --database "$adverse_database" --login "$adverse_login" --run-token "$adverse_token" --credential-file "$adverse_password_file" >/dev/null 2>&1 || failed=1
  run_helper cleanup-test-targets --server "$server" --admin-credential-file "$admin_password_file" --database "$adverse_database" --peer-database "$adverse_peer_database" --login "$adverse_login" --run-token "$adverse_token" --credential-file "$adverse_password_file" >/dev/null 2>&1 || failed=1
  run_helper verify-test-cleanup --server "$server" --admin-credential-file "$admin_password_file" --database "$adverse_database" --peer-database "$adverse_peer_database" --login "$adverse_login" --run-token "$adverse_token" >/dev/null 2>&1 || failed=1
  set -e
  ((failed == 0)) || { printf '%s\n' 'Cleanup failed; isolated EHF SQL verification is unsuccessful.' >&2; return 1; }
  cleanup_complete=1
}
cleanup_trap() {
  local status=$?
  if ((cleanup_complete == 0 && cleanup_attempted == 0)); then
    cleanup_owned_targets || status=3
  fi
  unset admin_password test_password adverse_password SQLCMDINI
  [[ -z "$secret_directory" ]] || rm -rf -- "$secret_directory"
  exit "$status"
}
trap cleanup_trap EXIT
run_helper() { "$helper_python" "$helper" "$@"; }
admin_password="$(<"$admin_password_file")"
secret_directory="$(mktemp -d /run/ehf-sqlperm.XXXXXXXX)"
chmod 0700 "$secret_directory"
test_password_file="$secret_directory/test-password"; adverse_password_file="$secret_directory/adverse-password"
test_password="Aa1._~$(openssl rand -hex 21)"; adverse_password="Aa1._~$(openssl rand -hex 21)"
printf '%s' "$test_password" >"$test_password_file"; printf '%s' "$adverse_password" >"$adverse_password_file"
chmod 0600 "$test_password_file" "$adverse_password_file"

run_admin_sql() { local target_database="$1"; shift; SQLCMDPASSWORD="$admin_password" "$sqlcmd" -S "$server" -U sa -C -X -I -d "$target_database" -b -V 11 -r 1 "$@"; }
run_runtime_sql() { local target_database="$1"; shift; SQLCMDPASSWORD="$test_password" "$sqlcmd" -S "$server" -U "$login" -C -X -I -d "$target_database" -b -V 11 -r 1 "$@"; }

# Seed an adversarial, test-shaped peer/login with its own evidence. It must be preserved.
run_helper create-test-database --server "$server" --admin-credential-file "$admin_password_file" --database "$adverse_database" --run-token "$adverse_token" >/dev/null || fail "The adverse primary database creation failed."
run_helper create-test-database --server "$server" --admin-credential-file "$admin_password_file" --database "$adverse_peer_database" --run-token "$adverse_token" >/dev/null || fail "The adverse peer database creation failed."
run_helper create-test-login --server "$server" --admin-credential-file "$admin_password_file" --database "$adverse_database" --login "$adverse_login" --credential-file "$adverse_password_file" >/dev/null || fail "The adverse test login creation failed."

run_helper create-test-database --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --run-token "$run_token" >/dev/null || fail "The isolated primary database creation failed."
run_helper create-test-database --server "$server" --admin-credential-file "$admin_password_file" --database "$peer_database" --run-token "$run_token" >/dev/null || fail "The isolated peer database creation failed."
for migration_file in 001_database_contract.sql 002_application_core.sql 003_audit_and_preferences.sql 004_audit_and_preference_hardening.sql 005_application_permissions.sql; do
  [[ -f "$migration_directory/$migration_file" ]] || fail "The isolated EHF migration set is incomplete."
  run_admin_sql "$database" -i "$migration_directory/$migration_file" >/dev/null 2>&1 || fail "The isolated EHF migration failed without credential details."
  run_helper record-test-migration --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --migration-file "$migration_file" >/dev/null || fail "The isolated EHF migration record failed."
done
for validation_file in 001_validate_database_contract.sql 002_validate_application_core.sql 003_validate_audit_and_preferences.sql 004_validate_audit_and_preference_hardening.sql 005_validate_application_permissions.sql; do
  run_admin_sql "$database" -i "$validation_directory/$validation_file" >/dev/null 2>&1 || fail "The isolated EHF SQL validator failed without credential details."
done
run_helper create-test-login --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --credential-file "$test_password_file" >/dev/null || fail "The isolated test login creation failed."
run_helper map-test-user --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --user "$user" >/dev/null || fail "The isolated test user mapping failed."
run_helper authenticate-login --server "$server" --database "$database" --login "$login" --credential-file "$test_password_file" --credential-kind test >/dev/null || fail "The isolated test login authentication failed."

run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated runtime health probe failed."
DECLARE @Health TABLE (IsReady bit NOT NULL); INSERT @Health EXEC dbo.RuntimeHealth; IF NOT EXISTS (SELECT 1 FROM @Health WHERE IsReady=1) THROW 51640,'Runtime health failed.',1;
SQL
run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated runtime preference transaction probe failed."
BEGIN TRANSACTION; EXEC dbo.SetUserPreference @IdentityKey=N'isolated-runtime-validator',@Email=N'validator@example.invalid',@DisplayName=N'Isolated runtime validator',@Skin='blue',@InvertColors=0,@CompactDensity=1,@ReduceMotion=0,@ActorIdentity=N'isolated-runtime-validator'; IF @@TRANCOUNT<>1 THROW 51641,'Preference transaction changed.',1; ROLLBACK;
SQL
run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated DML denial probe failed."
BEGIN TRY SELECT TOP(1) ApplicationId FROM dbo.Application; THROW 51645,'Protected SELECT succeeded.',1; END TRY BEGIN CATCH IF ERROR_NUMBER()=51645 THROW; IF ERROR_NUMBER()<>229 THROW; END CATCH;
BEGIN TRY INSERT dbo.Application (ApplicationId,FellowshipCallId,ApplicantId,ApplicationStatus) VALUES (NEWID(),NEWID(),NEWID(),'DRAFT'); THROW 51646,'Protected INSERT succeeded.',1; END TRY BEGIN CATCH IF ERROR_NUMBER()=51646 THROW; IF ERROR_NUMBER()<>229 THROW; END CATCH;
BEGIN TRY UPDATE dbo.Application SET ApplicationStatus='DRAFT' WHERE 1=0; THROW 51647,'Protected UPDATE succeeded.',1; END TRY BEGIN CATCH IF ERROR_NUMBER()=51647 THROW; IF ERROR_NUMBER()<>229 THROW; END CATCH;
BEGIN TRY DELETE dbo.Application WHERE 1=0; THROW 51648,'Protected DELETE succeeded.',1; END TRY BEGIN CATCH IF ERROR_NUMBER()=51648 THROW; IF ERROR_NUMBER()<>229 THROW; END CATCH;
SQL
run_runtime_sql "$database" <<'SQL' >/dev/null || fail "The isolated server permission denial probe failed."
IF COALESCE(HAS_PERMS_BY_NAME(NULL,NULL,N'ALTER ANY LOGIN'),0)<>0 THROW 51656,'ALTER ANY LOGIN granted.',1;
IF COALESCE(HAS_PERMS_BY_NAME(NULL,NULL,N'ALTER ANY SERVER ROLE'),0)<>0 THROW 51657,'ALTER ANY SERVER ROLE granted.',1;
BEGIN TRY EXECUTE AS LOGIN='sa'; THROW 51649,'Impersonation succeeded.',1; END TRY BEGIN CATCH IF ERROR_NUMBER()=51649 THROW; IF ERROR_NUMBER() NOT IN (15406,15517) THROW; END CATCH;
BEGIN TRY CREATE LOGIN [ehf_probe_policy_compliant] WITH PASSWORD='Aa1._~AbcdEFGHijklMNOPqrstUVWXyz0123456789._~-AbcdEFGH'; THROW 51650,'CREATE LOGIN succeeded.',1; END TRY BEGIN CATCH IF ERROR_NUMBER()=51650 THROW; IF ERROR_NUMBER()<>15247 THROW; END CATCH;
BEGIN TRY DECLARE @loginSql nvarchar(max)=N'ALTER LOGIN '+QUOTENAME(SUSER_SNAME())+N' DISABLE;'; EXEC(@loginSql); THROW 51651,'ALTER LOGIN succeeded.',1; END TRY BEGIN CATCH IF ERROR_NUMBER()=51651 THROW; IF ERROR_NUMBER()<>15151 THROW; END CATCH;
BEGIN TRY DECLARE @roleSql nvarchar(max)=N'ALTER SERVER ROLE [sysadmin] ADD MEMBER '+QUOTENAME(SUSER_SNAME())+N';'; EXEC(@roleSql); THROW 51652,'ALTER SERVER ROLE succeeded.',1; END TRY BEGIN CATCH IF ERROR_NUMBER()=51652 THROW; IF ERROR_NUMBER()<>15151 THROW; END CATCH;
SQL
run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated schema denial probe failed."
BEGIN TRY CREATE TABLE dbo.EhfDeniedProbe (Id int); THROW 51653,'Schema alteration succeeded.',1; END TRY BEGIN CATCH IF ERROR_NUMBER()=51653 THROW; IF ERROR_NUMBER()<>262 THROW; END CATCH;
SQL
run_helper exercise-test-status --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --credential-file "$test_password_file" >/dev/null || fail "The real runtime status/audit probe failed."
if run_runtime_sql "$peer_database" <<'SQL' >/dev/null 2>&1
SELECT TOP (1) name FROM sys.tables;
SQL
then fail "The runtime login read the isolated peer database."; fi
run_admin_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The rollback audit probe failed."
IF EXISTS (SELECT 1 FROM dbo.UserPreference p INNER JOIN dbo.AuditEvent a ON a.EntityId=p.UserPreferenceId WHERE p.IdentityKey=N'isolated-runtime-validator' AND a.EventType='USER_PREFERENCE_SET') THROW 51655,'Preference audit did not roll back.',1;
SQL

cleanup_owned_targets || exit 3
trap - EXIT
unset admin_password test_password adverse_password SQLCMDINI
rm -rf -- "$secret_directory"; secret_directory=""
printf '%s\n' 'PASS isolated EHF SQL permission boundary.'
