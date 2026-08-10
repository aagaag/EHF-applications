#!/usr/bin/env bash
{ set +x; } 2>/dev/null
set -euo pipefail

readonly sqlcmd="/opt/mssql-tools18/bin/sqlcmd"
readonly project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly migration_directory="${project_root}/database/migrations"
readonly validation_directory="${project_root}/database/tests"

run_id="$(openssl rand -hex 12)"
database="EHFApplications_Test_sqlperm_${run_id}"
login="ehf_app_test_${run_id}"
user="ehf_app_test_${run_id}"
created_database=0
created_login=0
admin_password=""
test_password=""

fail() {
  printf '%s\n' "$1" >&2
  exit 2
}

while (($#)); do
  case "$1" in
    --database)
      (($# >= 2)) || fail "Unexpected incomplete isolated SQL database option."
      database="$2"
      shift 2
      ;;
    --login)
      (($# >= 2)) || fail "Unexpected incomplete isolated SQL login option."
      login="$2"
      shift 2
      ;;
    --user)
      (($# >= 2)) || fail "Unexpected incomplete isolated SQL user option."
      user="$2"
      shift 2
      ;;
    *)
      fail "Unexpected isolated SQL verification option."
      ;;
  esac
done

if [[ ! "$database" =~ ^EHFApplications_Test_sqlperm_[a-f0-9]{24}$ ]] \
  || [[ ! "$login" =~ ^ehf_app_test_[a-f0-9]{24}$ ]] \
  || [[ ! "$user" =~ ^ehf_app_test_[a-f0-9]{24}$ ]] \
  || [[ "${database##*_}" != "${login##*_}" ]] \
  || [[ "${login##*_}" != "${user##*_}" ]]; then
  fail "Unexpected isolated EHF SQL database, login, or user name."
fi
if [[ "$EUID" -ne 0 ]]; then
  fail "Run the isolated EHF SQL verification as root."
fi
if [[ ! -x "$sqlcmd" ]]; then
  fail "The required SQL command-line client is unavailable."
fi
admin_password_file="${EHF_SQL_ADMIN_PASSWORD_FILE:-}"
if [[ -z "$admin_password_file" || -L "$admin_password_file" || ! -f "$admin_password_file" || ! -s "$admin_password_file" ]]; then
  fail "The protected EHF SQL administrator credential file is unavailable."
fi
if [[ "$(stat -c '%U:%G:%a' "$admin_password_file")" != "root:root:600" ]]; then
  fail "The protected EHF SQL administrator credential file has an unexpected shape."
fi
admin_password="$(<"$admin_password_file")"
test_password="$(openssl rand -base64 48 | tr -d '\n')"
[[ -n "$test_password" ]] || fail "Isolated SQL password generation failed."
export EHF_SQL_TEST_DATABASE="$database"
export EHF_SQL_TEST_LOGIN="$login"
export EHF_SQL_TEST_USER="$user"
export EHF_SQL_TEST_PASSWORD="$test_password"
trap 'unset admin_password test_password EHF_SQL_TEST_DATABASE EHF_SQL_TEST_LOGIN EHF_SQL_TEST_USER EHF_SQL_TEST_PASSWORD' EXIT

run_admin_sql() {
  local target_database="$1"
  local output
  if ! output="$(SQLCMDPASSWORD="$admin_password" "$sqlcmd" \
    -S 127.0.0.1:1433 -U sa -C -d "$target_database" -b -V 11 -r 1 2>&1)"; then
    unset output
    return 1
  fi
  unset output
}

run_runtime_sql() {
  local output
  if ! output="$(SQLCMDPASSWORD="$test_password" "$sqlcmd" \
    -S 127.0.0.1:1433 -U "$login" -C -d "$database" -b -V 11 -r 1 2>&1)"; then
    unset output
    return 1
  fi
  unset output
}

cleanup() {
  local status=$?
  set +e
  if ((created_database)); then
    run_admin_sql master <<'SQL'
DECLARE @DatabaseName sysname = N'$(EHF_SQL_TEST_DATABASE)';
IF @DatabaseName NOT LIKE N'EHFApplications_Test_sqlperm_[0-9a-f]%'
    THROW 51650, 'Cleanup refused an unexpected database.', 1;
IF DB_ID(@DatabaseName) IS NOT NULL
BEGIN
    DECLARE @DropDatabase nvarchar(max) =
        N'ALTER DATABASE ' + QUOTENAME(@DatabaseName) +
        N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE ' +
        QUOTENAME(@DatabaseName) + N';';
    EXEC (@DropDatabase);
END;
SQL
  fi
  if ((created_login)); then
    run_admin_sql master <<'SQL'
DECLARE @LoginName sysname = N'$(EHF_SQL_TEST_LOGIN)';
IF @LoginName NOT LIKE N'ehf_app_test_[0-9a-f]%'
    THROW 51651, 'Cleanup refused an unexpected login.', 1;
IF USER_ID(@LoginName) IS NOT NULL
    EXEC(N'DROP USER ' + QUOTENAME(@LoginName) + N';');
IF SUSER_ID(@LoginName) IS NOT NULL
    EXEC(N'DROP LOGIN ' + QUOTENAME(@LoginName) + N';');
SQL
  fi
  exit "$status"
}
trap cleanup EXIT

run_admin_sql master <<'SQL'
DECLARE @DatabaseName sysname = N'$(EHF_SQL_TEST_DATABASE)';
IF DB_ID(@DatabaseName) IS NOT NULL
    THROW 51620, 'The isolated test database already exists.', 1;
DECLARE @CreateDatabase nvarchar(max) = N'CREATE DATABASE ' + QUOTENAME(@DatabaseName) + N';';
EXEC (@CreateDatabase);
SQL
created_database=1

migration_files=(
  "001_database_contract.sql"
  "002_application_core.sql"
  "003_audit_and_preferences.sql"
  "004_audit_and_preference_hardening.sql"
  "005_application_permissions.sql"
)
for migration_file in "${migration_files[@]}"; do
  migration_path="${migration_directory}/${migration_file}"
  [[ -f "$migration_path" ]] || fail "The isolated EHF migration set is incomplete."
  if ! SQLCMDPASSWORD="$admin_password" "$sqlcmd" \
    -S 127.0.0.1:1433 -U sa -C -d "$database" -b -V 11 -r 1 \
    -i "$migration_path" >/dev/null 2>&1; then
    fail "An isolated EHF migration failed without credential details."
  fi
  migration_version="${migration_file%%_*}"
  migration_name="${migration_file#*_}"
  migration_name="${migration_name%.sql}"
  migration_checksum="$(sha256sum "$migration_path" | awk '{print $1}')"
  export EHF_SQL_MIGRATION_VERSION="$migration_version"
  export EHF_SQL_MIGRATION_NAME="$migration_name"
  export EHF_SQL_MIGRATION_CHECKSUM="$migration_checksum"
  run_admin_sql "$database" <<'SQL'
INSERT dbo.SchemaMigration (MigrationVersion, MigrationName, ChecksumSha256)
VALUES
(
    CONVERT(int, N'$(EHF_SQL_MIGRATION_VERSION)'),
    N'$(EHF_SQL_MIGRATION_NAME)',
    CONVERT(binary(32), N'0x$(EHF_SQL_MIGRATION_CHECKSUM)', 1)
);
SQL
  unset EHF_SQL_MIGRATION_VERSION EHF_SQL_MIGRATION_NAME EHF_SQL_MIGRATION_CHECKSUM
done

for validation_file in \
  "001_validate_database_contract.sql" \
  "002_validate_application_core.sql" \
  "003_validate_audit_and_preferences.sql" \
  "004_validate_audit_and_preference_hardening.sql" \
  "005_validate_application_permissions.sql"; do
  validation_path="${validation_directory}/${validation_file}"
  [[ -f "$validation_path" ]] || fail "The isolated EHF validator set is incomplete."
  if ! SQLCMDPASSWORD="$admin_password" "$sqlcmd" \
    -S 127.0.0.1:1433 -U sa -C -d "$database" -b -V 11 -r 1 \
    -i "$validation_path" >/dev/null 2>&1; then
    fail "An isolated EHF SQL validator failed without credential details."
  fi
done

run_admin_sql master <<'SQL'
DECLARE @LoginName sysname = N'$(EHF_SQL_TEST_LOGIN)';
DECLARE @Password nvarchar(256) = N'$(EHF_SQL_TEST_PASSWORD)';
IF SUSER_ID(@LoginName) IS NOT NULL
    THROW 51630, 'The isolated test login already exists.', 1;
DECLARE @CreateLogin nvarchar(max) =
    N'CREATE LOGIN ' + QUOTENAME(@LoginName) +
    N' WITH PASSWORD = N' + QUOTENAME(@Password, N'''') +
    N', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF, '
    + N'DEFAULT_DATABASE = ' + QUOTENAME(N'$(EHF_SQL_TEST_DATABASE)') + N';';
EXEC (@CreateLogin);
DECLARE @LoginSid varbinary(85) = SUSER_SID(@LoginName);
EXEC(N'CREATE USER ' + QUOTENAME(@LoginName) + N' FOR LOGIN ' + QUOTENAME(@LoginName) + N';');
DENY CONNECT TO [$(EHF_SQL_TEST_LOGIN)];
DENY ALTER ANY LOGIN, ALTER ANY SERVER ROLE, VIEW ANY DATABASE,
    VIEW SERVER STATE, VIEW ANY DEFINITION, CONTROL SERVER
    TO [$(EHF_SQL_TEST_LOGIN)];
IF @LoginSid IS NULL
    THROW 51631, 'The isolated test login was not created.', 1;
SQL
created_login=1

run_admin_sql "$database" <<'SQL'
DECLARE @LoginName sysname = N'$(EHF_SQL_TEST_LOGIN)';
DECLARE @UserName sysname = N'$(EHF_SQL_TEST_USER)';
IF DATABASE_PRINCIPAL_ID(@UserName) IS NOT NULL
    THROW 51632, 'The isolated test user already exists.', 1;
EXEC(N'CREATE USER ' + QUOTENAME(@UserName) + N' FOR LOGIN ' + QUOTENAME(@LoginName) + N';');
EXEC(N'ALTER ROLE [EHFApplicationRuntime] ADD MEMBER ' + QUOTENAME(@UserName) + N';');
IF EXISTS
(
    SELECT 1
    FROM sys.database_role_members AS membership
    INNER JOIN sys.database_principals AS role_row
        ON role_row.principal_id = membership.role_principal_id
    INNER JOIN sys.database_principals AS member_row
        ON member_row.principal_id = membership.member_principal_id
    WHERE member_row.name = @UserName
      AND role_row.name NOT IN (N'public', N'EHFApplicationRuntime')
)
    THROW 51633, 'The isolated test user has an unexpected role.', 1;
SQL

run_runtime_sql <<'SQL'
DECLARE @Health TABLE (IsReady bit NOT NULL);
INSERT @Health EXEC dbo.RuntimeHealth;
IF NOT EXISTS (SELECT 1 FROM @Health WHERE IsReady = 1)
    THROW 51640, 'The runtime health procedure failed.', 1;

BEGIN TRANSACTION;
DECLARE @PreferenceResult TABLE
(
    UserPreferenceId uniqueidentifier NOT NULL,
    IdentityKey nvarchar(255) NOT NULL,
    Email nvarchar(320) NOT NULL,
    DisplayName nvarchar(320) NOT NULL,
    Skin varchar(24) NOT NULL,
    InvertColors bit NOT NULL,
    CompactDensity bit NOT NULL,
    ReduceMotion bit NOT NULL,
    UpdatedAtUtc datetime2(7) NOT NULL,
    RowVersion binary(8) NOT NULL
);
INSERT @PreferenceResult
EXEC dbo.SetUserPreference
    @IdentityKey = N'isolated-runtime-validator',
    @Email = N'validator@example.invalid',
    @DisplayName = N'Isolated runtime validator',
    @Skin = 'blue',
    @InvertColors = 0,
    @CompactDensity = 1,
    @ReduceMotion = 0,
    @ActorIdentity = N'isolated-runtime-validator';
IF @@TRANCOUNT <> 1
    THROW 51641, 'The preference procedure did not preserve the outer transaction.', 1;
ROLLBACK TRANSACTION;

DECLARE @ProtectedTables TABLE (TableName sysname NOT NULL PRIMARY KEY);
INSERT @ProtectedTables (TableName)
VALUES
    (N'SchemaMigration'), (N'FellowshipCall'), (N'Applicant'),
    (N'ApplicantContact'), (N'Application'), (N'EmploymentAffiliation'),
    (N'Qualification'), (N'EligibilityDeclaration'), (N'Bibliometrics'),
    (N'ContributionStatement'), (N'FieldProvenance'),
    (N'ApplicationSectionVersion'), (N'AuditEvent'), (N'UserPreference');
IF EXISTS
(
    SELECT 1
    FROM @ProtectedTables AS protected_table
    CROSS APPLY
    (
        VALUES (N'SELECT'), (N'INSERT'), (N'UPDATE'), (N'DELETE')
    ) AS operation (PermissionName)
    WHERE HAS_PERMS_BY_NAME
    (
        N'dbo.' + protected_table.TableName,
        N'OBJECT', operation.PermissionName
    ) <> 0
)
    THROW 51642, 'The runtime login has direct table permission.', 1;
IF HAS_PERMS_BY_NAME(DB_NAME(), N'DATABASE', N'VIEW DEFINITION') <> 0
    THROW 51643, 'The runtime login can read database definitions.', 1;
IF HAS_PERMS_BY_NAME(N'dbo', N'SCHEMA', N'ALTER') <> 0
    THROW 51644, 'The runtime login can alter the dbo schema.', 1;
IF COALESCE(HAS_PERMS_BY_NAME(NULL, NULL, N'ALTER ANY LOGIN'), 0) <> 0
    THROW 51656, 'The runtime login can manage server logins.', 1;
IF COALESCE(HAS_PERMS_BY_NAME(NULL, NULL, N'ALTER ANY SERVER ROLE'), 0) <> 0
    THROW 51657, 'The runtime login can manage server roles.', 1;

BEGIN TRY
    SELECT TOP (1) UserPreferenceId FROM dbo.UserPreference;
    THROW 51645, 'The runtime login read a protected table.', 1;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() = 51645 THROW;
    IF ERROR_NUMBER() <> 229 THROW;
END CATCH;
BEGIN TRY
    DELETE FROM dbo.UserPreference WHERE 1 = 0;
    THROW 51646, 'The runtime login deleted a protected table.', 1;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() = 51646 THROW;
    IF ERROR_NUMBER() <> 229 THROW;
END CATCH;
BEGIN TRY
    UPDATE dbo.UserPreference SET Skin = Skin WHERE 1 = 0;
    THROW 51647, 'The runtime login updated a protected table.', 1;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() = 51647 THROW;
    IF ERROR_NUMBER() <> 229 THROW;
END CATCH;
BEGIN TRY
    INSERT dbo.UserPreference
        (IdentityKey, Email, DisplayName, Skin,
         InvertColors, CompactDensity, ReduceMotion)
    VALUES
        (N'isolated-direct-validator', N'validator@example.invalid',
         N'Isolated direct validator', 'default', 0, 0, 0);
    THROW 51648, 'The runtime login inserted into a protected table.', 1;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() = 51648 THROW;
    IF ERROR_NUMBER() <> 229 THROW;
END CATCH;
BEGIN TRY
    EXEC(N'CREATE TABLE dbo.IsolatedPermissionDenied (Id int NOT NULL);');
    THROW 51649, 'The runtime login altered the schema.', 1;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() = 51649 THROW;
END CATCH;
BEGIN TRY
    EXEC(N'ALTER SERVER ROLE [sysadmin] ADD MEMBER [ehf_isolated_role_member_denied];');
    THROW 51652, 'The runtime login altered a server role.', 1;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() = 51652 THROW;
END CATCH;
BEGIN TRY
    EXEC(N'CREATE LOGIN [ehf_isolated_permission_denied] WITH PASSWORD = ''x'';');
    THROW 51653, 'The runtime login created a server login.', 1;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() = 51653 THROW;
END CATCH;
BEGIN TRY
    EXECUTE AS USER = N'EHFPreferenceProcedureExecutor';
    THROW 51654, 'The runtime login impersonated the preference executor.', 1;
END TRY
BEGIN CATCH
    IF ERROR_NUMBER() = 51654 THROW;
END CATCH;
SQL

if run_runtime_sql <<'SQL'
SELECT TOP (1) name FROM master.sys.databases;
SQL
then
  fail "The runtime login read another database."
fi

run_admin_sql "$database" <<'SQL'
IF EXISTS
(
    SELECT 1
    FROM dbo.UserPreference AS preference_row
    INNER JOIN dbo.AuditEvent AS audit_row
        ON audit_row.EntityId = preference_row.UserPreferenceId
    WHERE preference_row.IdentityKey = N'isolated-runtime-validator'
      AND audit_row.EventType = 'USER_PREFERENCE_SET'
)
    THROW 51655, 'The preference audit did not roll back with the caller transaction.', 1;
SQL

printf '%s\n' 'PASS isolated EHF SQL permission boundary.'
