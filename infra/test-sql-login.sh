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
[[ -n "$admin_password_file" ]] || fail "The protected EHF SQL administrator credential file is unavailable."

unset SQLCMDINI
cleanup_owned_targets() {
  local failed=0
  cleanup_attempted=1
  set +e
  [[ -n "$secret_directory" ]] || failed=1
  run_helper cleanup-test-targets --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --peer-database "$peer_database" --login "$login" --run-token "$run_token" >/dev/null || { printf '%s\n' 'Cleanup stage: current targets.' >&2; failed=1; }
  run_helper verify-test-cleanup --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --peer-database "$peer_database" --login "$login" --run-token "$run_token" >/dev/null 2>&1 || { printf '%s\n' 'Cleanup stage: current named verify.' >&2; failed=1; }
  # The seeded peer/login must survive the current-run cleanup before its own cleanup.
  run_helper verify-test-targets-preserved --server "$server" --admin-credential-file "$admin_password_file" --database "$adverse_database" --login "$adverse_login" --run-token "$adverse_token" >/dev/null 2>&1 || { printf '%s\n' 'Cleanup stage: adverse preservation.' >&2; failed=1; }
  run_helper cleanup-test-targets --server "$server" --admin-credential-file "$admin_password_file" --database "$adverse_database" --peer-database "$adverse_peer_database" --login "$adverse_login" --run-token "$adverse_token" >/dev/null 2>&1 || { printf '%s\n' 'Cleanup stage: adverse targets.' >&2; failed=1; }
  run_helper verify-test-cleanup --server "$server" --admin-credential-file "$admin_password_file" --database "$adverse_database" --peer-database "$adverse_peer_database" --login "$adverse_login" --run-token "$adverse_token" >/dev/null 2>&1 || { printf '%s\n' 'Cleanup stage: adverse named verify.' >&2; failed=1; }
  run_helper verify-no-test-leftovers --server "$server" --admin-credential-file "$admin_password_file" >/dev/null 2>&1 || { printf '%s\n' 'Cleanup stage: global zero verify.' >&2; failed=1; }
  set -e
  ((failed == 0)) || { printf '%s\n' 'Cleanup failed; isolated EHF SQL verification is unsuccessful.' >&2; return 1; }
  cleanup_complete=1
}
cleanup_trap() {
  local status=$?
  if ((cleanup_complete == 0 && cleanup_attempted == 0)); then
    cleanup_owned_targets || status=3
  fi
  unset test_password adverse_password SQLCMDINI
  [[ -z "$secret_directory" ]] || rm -rf -- "$secret_directory"
  exit "$status"
}
trap cleanup_trap EXIT
run_helper() { "$helper_python" "$helper" "$@"; }
secret_directory="$(mktemp -d /run/ehf-sqlperm.XXXXXXXX)"
chmod 0700 "$secret_directory"
test_password_file="$secret_directory/test-password"; adverse_password_file="$secret_directory/adverse-password"
test_password="Aa1._~$(openssl rand -hex 21)"; adverse_password="Aa1._~$(openssl rand -hex 21)"
printf '%s' "$test_password" >"$test_password_file"; printf '%s' "$adverse_password" >"$adverse_password_file"
chmod 0600 "$test_password_file" "$adverse_password_file"

run_admin_sql() { local target_database="$1"; local artifact="$2"; run_helper run-admin-sqlcmd --server "$server" --admin-credential-file "$admin_password_file" --database "$target_database" --sql-file "$artifact"; }
run_runtime_sql() { local target_database="$1"; shift; SQLCMDPASSWORD="$test_password" "$sqlcmd" -S "$server" -U "$login" -C -X -I -d "$target_database" -b -V 11 -r 1 "$@"; }

# Seed an adversarial, test-shaped peer/login with its own evidence. It must be preserved.
run_helper create-test-database --server "$server" --admin-credential-file "$admin_password_file" --database "$adverse_database" --run-token "$adverse_token" >/dev/null || fail "The adverse primary database creation failed."
run_helper create-test-database --server "$server" --admin-credential-file "$admin_password_file" --database "$adverse_peer_database" --run-token "$adverse_token" >/dev/null || fail "The adverse peer database creation failed."
run_helper create-test-login --server "$server" --admin-credential-file "$admin_password_file" --database "$adverse_database" --login "$adverse_login" --credential-file "$adverse_password_file" >/dev/null || fail "The adverse test login creation failed."

run_helper create-test-database --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --run-token "$run_token" >/dev/null || fail "The isolated primary database creation failed."
run_helper create-test-database --server "$server" --admin-credential-file "$admin_password_file" --database "$peer_database" --run-token "$run_token" >/dev/null || fail "The isolated peer database creation failed."
for migration_file in 001_database_contract.sql 002_application_core.sql 003_audit_and_preferences.sql 004_audit_and_preference_hardening.sql 005_application_permissions.sql 006_user_preference_read.sql 007_document_store.sql 008_import_provenance.sql 009_document_permissions.sql 010_report_export_audit.sql 011_applicant_access.sql 012_applicant_drafts.sql 013_applicant_confirmations.sql 014_applicant_projection.sql 015_applicant_document_slots.sql; do
  [[ -f "$migration_directory/$migration_file" ]] || fail "The isolated EHF migration set is incomplete."
  run_admin_sql "$database" "$migration_file" >/dev/null 2>&1 || fail "The isolated EHF migration failed without credential details."
  run_helper record-test-migration --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --migration-file "$migration_file" >/dev/null || fail "The isolated EHF migration record failed."
done
for validation_file in 001_validate_database_contract.sql 002_validate_application_core.sql 003_validate_audit_and_preferences.sql 004_validate_audit_and_preference_hardening.sql 005_validate_application_permissions.sql 006_validate_user_preference_read.sql 007_validate_document_store.sql 008_validate_import_provenance.sql 009_validate_document_permissions.sql 010_validate_report_export_audit.sql 011_validate_applicant_access.sql 012_validate_applicant_drafts.sql 013_validate_applicant_confirmations.sql 014_validate_applicant_projection.sql 015_validate_applicant_document_slots.sql; do
  run_admin_sql "$database" "$validation_file" >/dev/null 2>&1 || fail "The isolated EHF SQL validator failed without credential details."
done
run_helper create-test-login --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --credential-file "$test_password_file" >/dev/null || fail "The isolated test login creation failed."
run_helper map-test-user --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --user "$user" >/dev/null || fail "The isolated test user mapping failed."
run_helper authenticate-login --server "$server" --database "$database" --login "$login" --credential-file "$test_password_file" --credential-kind test >/dev/null || fail "The isolated test login authentication failed."

run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated runtime health probe failed."
DECLARE @Health TABLE (IsReady bit NOT NULL); INSERT @Health EXEC dbo.RuntimeHealth; IF NOT EXISTS (SELECT 1 FROM @Health WHERE IsReady=1) THROW 51640,'Runtime health failed.',1;
SQL
run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated runtime preference transaction probe failed."
BEGIN TRANSACTION;
EXEC dbo.SetUserPreference @IdentityKey=N'isolated-runtime-validator',@Email=N'validator@example.invalid',@DisplayName=N'Isolated runtime validator',@Skin='blue',@InvertColors=0,@CompactDensity=1,@ReduceMotion=0,@ActorIdentity=N'isolated-runtime-validator';
IF @@TRANCOUNT<>1 THROW 51641,'Preference transaction changed.',1;
DECLARE @Preference TABLE (UserPreferenceId uniqueidentifier,IdentityKey nvarchar(255),Email nvarchar(320),DisplayName nvarchar(320),Skin varchar(24),InvertColors bit,CompactDensity bit,ReduceMotion bit);
INSERT @Preference EXEC dbo.GetUserPreference @IdentityKey=N'isolated-runtime-validator';
IF NOT EXISTS (SELECT 1 FROM @Preference WHERE Skin='blue' AND CompactDensity=1) THROW 51642,'Preference read failed.',1;
ROLLBACK;
SQL
run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated runtime report-export audit probe failed."
BEGIN TRANSACTION;
EXEC dbo.RecordReportExportAudit @ActorIdentity=N'isolated-runtime-validator',@ActorGroup=N'EHF-Trustees',@RowCount=2,@Outcome=N'COMPLETED',@FailureStage=NULL;
IF @@TRANCOUNT<>1 THROW 51657,'Report export audit changed the caller transaction.',1;
ROLLBACK;
SQL
run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated DML denial probe failed."
DECLARE @DmlTargets TABLE (TableName sysname NOT NULL, ColumnName sysname NOT NULL);
INSERT @DmlTargets VALUES
 (N'SchemaMigration',N'MigrationVersion'),(N'FellowshipCall',N'CallCode'),(N'Applicant',N'LegalGivenNames'),
 (N'ApplicantContact',N'ApplicantId'),(N'Application',N'ApplicationStatus'),(N'EmploymentAffiliation',N'ApplicationId'),
 (N'Qualification',N'ApplicationId'),(N'EligibilityDeclaration',N'ApplicationId'),(N'Bibliometrics',N'ApplicationId'),
 (N'ContributionStatement',N'ApplicationId'),(N'FieldProvenance',N'EntityType'),(N'ApplicationSectionVersion',N'ApplicationId'),
 (N'AuditEvent',N'EventType'),(N'UserPreference',N'IdentityKey'),
 (N'DocumentSlot',N'SlotCode'),(N'Document',N'DocumentType'),(N'StoredObject',N'ObjectKey'),
 (N'DocumentVersion',N'VersionNumber'),(N'Recommendation',N'ArrivalChannel'),
 (N'ImportRun',N'ImporterVersion'),(N'ImportRow',N'SourceRowNumber'),(N'SourceOccurrence',N'SourceLocatorSha256'),
 (N'CallSourceOccurrence',N'SourceLocatorSha256'),(N'ImportException',N'ExceptionCode'),
 (N'ClassificationDecision',N'Classification'),
 (N'ApplicantInvitation',N'InvitationTokenSha256'),(N'ApplicantPreAuthContext',N'ApplicantInvitationId'),
 (N'ApplicantVerificationChallenge',N'ApplicantInvitationId'),(N'ApplicantSession',N'ApplicationId'),
 (N'ApplicantRateLimitBucket',N'ScopeType'),(N'ApplicantSectionDraft',N'SectionCode'),
 (N'ApplicantFieldCorrection',N'FieldCode'),(N'ApplicantSectionConfirmation',N'SectionCode'),
 (N'ApplicantFinalConfirmation',N'ApplicationId'),(N'ApplicantReopenScope',N'ScopeType'),
 (N'ApplicantDocumentSubmission',N'SubmissionStatus');
DECLARE @TableName sysname,@ColumnName sysname,@Sql nvarchar(max),@Denied bit;
DECLARE dml_cursor CURSOR LOCAL FAST_FORWARD FOR SELECT TableName,ColumnName FROM @DmlTargets;
OPEN dml_cursor; FETCH NEXT FROM dml_cursor INTO @TableName,@ColumnName;
WHILE @@FETCH_STATUS=0
BEGIN
  SET @Denied=0; SET @Sql=N'SELECT TOP (1) 1 FROM dbo.'+QUOTENAME(@TableName)+N';';
  BEGIN TRY EXEC sys.sp_executesql @Sql; END TRY BEGIN CATCH IF ERROR_NUMBER()<>229 THROW; SET @Denied=1; END CATCH;
  IF @Denied=0 THROW 51645,'DML permission denial was not returned for SELECT.',1;
  SET @Denied=0; SET @Sql=N'INSERT dbo.'+QUOTENAME(@TableName)+N' DEFAULT VALUES;';
  BEGIN TRY EXEC sys.sp_executesql @Sql; END TRY BEGIN CATCH IF ERROR_NUMBER()<>229 THROW; SET @Denied=1; END CATCH;
  IF @Denied=0 THROW 51646,'DML permission denial was not returned for INSERT.',1;
  SET @Denied=0; SET @Sql=N'UPDATE dbo.'+QUOTENAME(@TableName)+N' SET '+QUOTENAME(@ColumnName)+N'='+QUOTENAME(@ColumnName)+N' WHERE 1=0;';
  BEGIN TRY EXEC sys.sp_executesql @Sql; END TRY BEGIN CATCH IF ERROR_NUMBER()<>229 THROW; SET @Denied=1; END CATCH;
  IF @Denied=0 THROW 51647,'DML permission denial was not returned for UPDATE.',1;
  SET @Denied=0; SET @Sql=N'DELETE dbo.'+QUOTENAME(@TableName)+N' WHERE 1=0;';
  BEGIN TRY EXEC sys.sp_executesql @Sql; END TRY BEGIN CATCH IF ERROR_NUMBER()<>229 THROW; SET @Denied=1; END CATCH;
  IF @Denied=0 THROW 51648,'DML permission denial was not returned for DELETE.',1;
  FETCH NEXT FROM dml_cursor INTO @TableName,@ColumnName;
END;
CLOSE dml_cursor; DEALLOCATE dml_cursor;
SQL
run_runtime_sql "$database" <<'SQL' >/dev/null 2>&1 || fail "The isolated server and metadata denial probe failed."
DECLARE @DeniedPermissions TABLE (PermissionName sysname NOT NULL, ScopeName sysname NULL);
-- Do not add an explicit DENY CONTROL SERVER: SQL Server then rejects this
-- SQL login with error 18456. Its effective absence is still verified below.
INSERT @DeniedPermissions VALUES
 (N'ALTER ANY LOGIN',NULL),(N'ALTER ANY SERVER ROLE',NULL),(N'CONTROL SERVER',NULL),
 (N'VIEW ANY DATABASE',NULL),(N'VIEW ANY DEFINITION',NULL),(N'VIEW SERVER STATE',NULL),
 (N'VIEW DEFINITION',N'DATABASE'),(N'CREATE TABLE',N'DATABASE'),(N'CREATE PROCEDURE',N'DATABASE'),
 (N'CREATE VIEW',N'DATABASE'),(N'ALTER ANY SCHEMA',N'DATABASE'),(N'ALTER ANY USER',N'DATABASE'),
 (N'ALTER ANY ROLE',N'DATABASE'),(N'ALTER',N'SCHEMA'),(N'IMPERSONATE',N'USER');
DECLARE @PermissionName sysname,@ScopeName sysname,@HasPermission int;
DECLARE permission_cursor CURSOR LOCAL FAST_FORWARD FOR SELECT PermissionName,ScopeName FROM @DeniedPermissions;
OPEN permission_cursor; FETCH NEXT FROM permission_cursor INTO @PermissionName,@ScopeName;
WHILE @@FETCH_STATUS=0
BEGIN
  SET @HasPermission=CASE @ScopeName
    WHEN N'DATABASE' THEN HAS_PERMS_BY_NAME(DB_NAME(),N'DATABASE',@PermissionName)
    WHEN N'SCHEMA' THEN HAS_PERMS_BY_NAME(N'dbo',N'SCHEMA',@PermissionName)
    WHEN N'USER' THEN HAS_PERMS_BY_NAME(N'EHFPreferenceProcedureExecutor',N'USER',@PermissionName)
    ELSE HAS_PERMS_BY_NAME(NULL,NULL,@PermissionName) END;
IF COALESCE(@HasPermission,0)<>0 THROW 51656,'A required server or metadata denial is missing.',1;
  FETCH NEXT FROM permission_cursor INTO @PermissionName,@ScopeName;
END;
CLOSE permission_cursor; DEALLOCATE permission_cursor;
IF COALESCE(HAS_PERMS_BY_NAME(N'EHFReportExportAuditExecutor',N'USER',N'IMPERSONATE'),0)<>0
  THROW 51658,'Report audit executor impersonation is available.',1;
IF COALESCE(HAS_PERMS_BY_NAME(N'EHFFinalConfirmationProcedureExecutor',N'USER',N'IMPERSONATE'),0)<>0
  THROW 51659,'Final-confirmation executor impersonation is available.',1;
DECLARE @Denied bit=0;
BEGIN TRY EXECUTE AS LOGIN='sa'; END TRY BEGIN CATCH IF ERROR_NUMBER() NOT IN (15406,15517) THROW; SET @Denied=1; END CATCH;
IF @Denied=0 THROW 51649,'Impersonation succeeded.',1;
SET @Denied=0;
BEGIN TRY CREATE LOGIN [ehf_probe_policy_compliant] WITH PASSWORD='Aa1._~AbcdEFGHijklMNOPqrstUVWXyz0123456789._~-AbcdEFGH'; END TRY BEGIN CATCH IF ERROR_NUMBER()<>15247 THROW; SET @Denied=1; END CATCH;
IF @Denied=0 THROW 51650,'CREATE LOGIN succeeded.',1;
SET @Denied=0;
BEGIN TRY DECLARE @loginSql nvarchar(max)=N'ALTER LOGIN '+QUOTENAME(SUSER_SNAME())+N' DISABLE;'; EXEC(@loginSql); END TRY BEGIN CATCH IF ERROR_NUMBER()<>15151 THROW; SET @Denied=1; END CATCH;
IF @Denied=0 THROW 51651,'ALTER LOGIN succeeded.',1;
SET @Denied=0;
BEGIN TRY DECLARE @roleSql nvarchar(max)=N'ALTER SERVER ROLE [sysadmin] ADD MEMBER '+QUOTENAME(SUSER_SNAME())+N';'; EXEC(@roleSql); END TRY BEGIN CATCH IF ERROR_NUMBER()<>15151 THROW; SET @Denied=1; END CATCH;
IF @Denied=0 THROW 51652,'ALTER SERVER ROLE succeeded.',1;
SET @Denied=0;
BEGIN TRY CREATE TABLE dbo.EhfDeniedProbe (Id int); END TRY BEGIN CATCH IF ERROR_NUMBER()<>262 THROW; SET @Denied=1; END CATCH;
IF @Denied=0 THROW 51653,'Schema alteration succeeded.',1;
SQL
run_helper exercise-test-status --server "$server" --admin-credential-file "$admin_password_file" --database "$database" --login "$login" --credential-file "$test_password_file" >/dev/null || fail "The real runtime status/audit probe failed."
run_helper verify-peer-database-denial --server "$server" --database "$peer_database" --login "$login" --credential-file "$test_password_file" >/dev/null 2>&1 || fail "The exact isolated peer database denial was unavailable."
run_helper verify-test-preference-rollback --server "$server" --admin-credential-file "$admin_password_file" --database "$database" >/dev/null || fail "The rollback audit probe failed."

cleanup_owned_targets || exit 3
trap - EXIT
unset test_password adverse_password SQLCMDINI
rm -rf -- "$secret_directory"; secret_directory=""
printf '%s\n' 'PASS isolated EHF SQL permission boundary.'
