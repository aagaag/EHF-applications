#!/usr/bin/env python3
"""Fixed-purpose EHF SQL principal lifecycle helper.

There is deliberately no arbitrary SQL, target, connection-string, or secret
value interface.  Every accepted target has an exact production or randomized
test shape.  Dynamic SQL Server identifiers are built server-side only after
that validation and with ``QUOTENAME``.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
from typing import Iterable, Sequence

try:
    import pyodbc
except ImportError:  # pragma: no cover - deployment prerequisite path.
    class _MissingPyodbc:
        class Error(Exception):
            pass

        @staticmethod
        def connect(*_args, **_kwargs):
            raise PrincipalError("The pinned pyodbc runtime is unavailable")

    pyodbc = _MissingPyodbc()

try:  # Windows unit tests load this module without a POSIX group database.
    import grp
except ImportError:  # pragma: no cover
    grp = None


SERVER = "tcp:127.0.0.1,1433"
PRODUCTION_DATABASE = "EHFApplications"
PRODUCTION_LOGIN = "ehf_app"
PRODUCTION_USER = "ehf_app"
TEST_DATABASE = re.compile(r"^EHFApplications_Test_sqlperm_([a-f0-9]{24})$")
TEST_PEER_DATABASE = re.compile(r"^EHFApplications_Test_sqlperm_peer_([a-f0-9]{24})$")
TEST_LOGIN = re.compile(r"^ehf_app_test_([a-f0-9]{24})$")
RUN_TOKEN = re.compile(r"^[a-f0-9]{32}$")
SAFE_PASSWORD = re.compile(r"^[A-Za-z0-9._~-]{48}$")
MARKER_NAME = "EHF.Task4RunToken"
EXPECTED_SERVER_DENIES = frozenset(
    {
        "ALTER ANY LOGIN",
        "ALTER ANY SERVER ROLE",
        "CONTROL SERVER",
        "VIEW ANY DATABASE",
        "VIEW ANY DEFINITION",
        "VIEW SERVER STATE",
    }
)
MIGRATIONS = {
    "001_database_contract.sql": (1, "database_contract"),
    "002_application_core.sql": (2, "application_core"),
    "003_audit_and_preferences.sql": (3, "audit_and_preferences"),
    "004_audit_and_preference_hardening.sql": (4, "audit_and_preference_hardening"),
    "005_application_permissions.sql": (5, "application_permissions"),
}
COMMANDS = (
    "inspect-production",
    "authenticate-login",
    "create-production-login",
    "map-production-user",
    "create-test-database",
    "create-test-login",
    "map-test-user",
    "record-test-migration",
    "exercise-test-status",
    "cleanup-test-targets",
    "verify-test-cleanup",
    "verify-test-targets-preserved",
)


class PrincipalError(RuntimeError):
    pass


def _require_server(server: str) -> None:
    if server != SERVER:
        raise PrincipalError("Unexpected SQL Server target")


def _test_suffix(database: str) -> str | None:
    match = TEST_DATABASE.fullmatch(database) or TEST_PEER_DATABASE.fullmatch(database)
    return match.group(1) if match else None


def validate_target_names(database: str, login: str, user: str) -> None:
    if (database, login, user) == (PRODUCTION_DATABASE, PRODUCTION_LOGIN, PRODUCTION_USER):
        return
    suffix = _test_suffix(database)
    login_match = TEST_LOGIN.fullmatch(login)
    if suffix and login_match and login_match.group(1) == suffix and user == login:
        return
    raise PrincipalError("Unexpected principal target")


def validate_test_targets(database: str, peer_database: str, login: str) -> str:
    primary = TEST_DATABASE.fullmatch(database)
    peer = TEST_PEER_DATABASE.fullmatch(peer_database)
    login_match = TEST_LOGIN.fullmatch(login)
    if not primary or not peer or not login_match:
        raise PrincipalError("Unexpected principal target")
    suffix = primary.group(1)
    if peer.group(1) != suffix or login_match.group(1) != suffix:
        raise PrincipalError("Unexpected principal target")
    return suffix


def validate_run_token(token: str, suffix: str | None = None) -> None:
    if not RUN_TOKEN.fullmatch(token) or (suffix is not None and not token.startswith(suffix)):
        raise PrincipalError("Unexpected run token")


def validate_command_arguments(
    command: str,
    server: str,
    database: str | None,
    login: str | None,
    peer_database: str | None,
    user: str | None = None,
    run_token: str | None = None,
) -> None:
    """Reject every target before a credential is read or a connection is opened."""
    if command not in COMMANDS:
        raise PrincipalError("Unexpected helper command")
    _require_server(server)
    if command == "authenticate-login":
        if database is None or login is None:
            raise PrincipalError("Unexpected principal target")
        validate_target_names(database, login, login)
        return
    if database is None:
        raise PrincipalError("Unexpected principal target")
    if command in {"inspect-production", "create-production-login", "map-production-user"}:
        validate_target_names(database, login or "", user or PRODUCTION_USER)
        if database != PRODUCTION_DATABASE or login != PRODUCTION_LOGIN:
            raise PrincipalError("Unexpected principal target")
    elif command in {"create-test-database"}:
        if _test_suffix(database) is None:
            raise PrincipalError("Unexpected principal target")
    elif command in {"create-test-login", "map-test-user", "exercise-test-status"}:
        if login is None:
            raise PrincipalError("Unexpected principal target")
        validate_target_names(database, login, user or login)
        if database == PRODUCTION_DATABASE:
            raise PrincipalError("Unexpected principal target")
    elif command == "record-test-migration":
        if not TEST_DATABASE.fullmatch(database):
            raise PrincipalError("Unexpected principal target")
    elif command in {"cleanup-test-targets", "verify-test-cleanup"}:
        if login is None or peer_database is None:
            raise PrincipalError("Unexpected principal target")
        validate_test_targets(database, peer_database, login)
    elif command == "verify-test-targets-preserved":
        if login is None:
            raise PrincipalError("Unexpected principal target")
        validate_target_names(database, login, login)
        if database == PRODUCTION_DATABASE:
            raise PrincipalError("Unexpected principal target")
    if command in {"create-test-database", "cleanup-test-targets", "verify-test-cleanup", "verify-test-targets-preserved"}:
        if run_token is None:
            raise PrincipalError("Unexpected run token")
        validate_run_token(run_token, _test_suffix(database))


def _credential_mode(kind: str) -> tuple[int, int | None]:
    if kind in {"admin", "test"}:
        return 0o600, 0
    if kind == "application":
        try:
            if grp is None:
                raise KeyError
            return 0o640, grp.getgrnam("ehf").gr_gid
        except KeyError as error:
            raise PrincipalError("Protected application credential group is unavailable") from error
    raise PrincipalError("Unexpected credential purpose")


def _safe_credential_parents(path: Path) -> None:
    if not path.is_absolute():
        raise PrincipalError("Protected credential file has an unexpected shape")
    current = Path(path.anchor)
    for part in path.parts[1:-1]:
        current /= part
        metadata = os.lstat(current)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise PrincipalError("Protected credential file has an unexpected shape")


def read_credential(path: Path, kind: str) -> str:
    """Read one securely opened descriptor; never resolve and reopen the path."""
    expected_mode, expected_group = _credential_mode(kind)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not getattr(os, "O_NOFOLLOW", 0) or not getattr(os, "O_CLOEXEC", 0):
        raise PrincipalError("Protected credential file is unavailable")
    try:
        _safe_credential_parents(path)
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != 0
                or stat.S_IMODE(metadata.st_mode) != expected_mode
                or (expected_group is not None and metadata.st_gid != expected_group)
            ):
                raise PrincipalError("Protected credential file has an unexpected shape")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(map(len, chunks)) > 256:
                    raise PrincipalError("Protected credential file has an unexpected shape")
            value = b"".join(chunks).decode("utf-8")
        finally:
            os.close(descriptor)
    except PrincipalError:
        raise
    except (OSError, UnicodeError) as error:
        raise PrincipalError("Protected credential file is unavailable") from error
    if not value or "\n" in value or "\r" in value:
        raise PrincipalError("Protected credential file has an unexpected shape")
    return value


def _require_safe_password(value: str) -> None:
    if not (SAFE_PASSWORD.fullmatch(value) and re.search(r"[A-Z]", value) and re.search(r"[a-z]", value) and re.search(r"[0-9]", value) and re.search(r"[._~-]", value)):
        raise PrincipalError("Protected credential file has an unexpected shape")


def _odbc_component(value: str) -> str:
    if not value or "\x00" in value:
        raise PrincipalError("Unexpected SQL connection component")
    return "{" + value.replace("}", "}}") + "}"


def _connect(server: str, database: str | None, login: str, password: str):
    _require_server(server)
    if database is not None and database not in {"master", PRODUCTION_DATABASE} and _test_suffix(database) is None:
        raise PrincipalError("Unexpected principal target")
    if not login or "\x00" in login:
        raise PrincipalError("Unexpected principal target")
    parts = [
        "DRIVER={ODBC Driver 18 for SQL Server}",
        "SERVER=" + _odbc_component(server),
        "UID=" + _odbc_component(login),
        "PWD=" + _odbc_component(password),
        "Encrypt=yes",
        "TrustServerCertificate=yes",
    ]
    if database:
        parts.append("DATABASE=" + _odbc_component(database))
    return pyodbc.connect(";".join(parts), autocommit=False)


def connect_admin(server: str, credential_file: Path, database: str = "master"):
    return _connect(server, database, "sa", read_credential(credential_file, "admin"))


def _execute(connection, statement: str, parameters: Sequence[object] = ()) -> None:
    cursor = connection.cursor()
    cursor.execute(statement, *parameters)
    connection.commit()


def _rows(connection, statement: str, parameters: Sequence[object] = ()) -> list[object]:
    cursor = connection.cursor()
    cursor.execute(statement, *parameters)
    return list(cursor.fetchall())


def first_result_row(cursor):
    while cursor.description is None:
        if not cursor.nextset():
            raise PrincipalError("Expected SQL result set is unavailable")
    return cursor.fetchone()


def create_production_login(connection, database: str, login: str, credential_file: Path) -> None:
    validate_command_arguments("create-production-login", SERVER, database, login, None, PRODUCTION_USER)
    password = read_credential(credential_file, "application")
    _require_safe_password(password)
    connection.autocommit = True
    _execute(connection, """
DECLARE @LoginName sysname=?; DECLARE @Password nvarchar(128)=?; DECLARE @DatabaseName sysname=?;
IF SUSER_ID(@LoginName) IS NOT NULL THROW 51701, 'Expected login already exists.', 1;
IF DB_ID(@DatabaseName) IS NULL THROW 51702, 'Expected database is unavailable.', 1;
DECLARE @Check nvarchar(max)=N'USE '+QUOTENAME(@DatabaseName)+N';
DECLARE @Auth nvarchar(60); SELECT @Auth=authentication_type_desc FROM sys.database_principals WHERE name=N''ehf_app'' AND type_desc=N''SQL_USER'';
IF @Auth<>N''NONE'' THROW 51703,''Expected database user has an unexpected shape.'',1;
IF EXISTS (SELECT 1 FROM sys.database_permissions WHERE grantee_principal_id=DATABASE_PRINCIPAL_ID(N''ehf_app'')) THROW 51726,''Expected database user has direct permissions.'',1;
IF EXISTS (SELECT 1 FROM sys.database_role_members m INNER JOIN sys.database_principals r ON r.principal_id=m.role_principal_id WHERE m.member_principal_id=DATABASE_PRINCIPAL_ID(N''ehf_app'') AND r.name<>N''EHFApplicationRuntime'') THROW 51724,''Expected database user has an unexpected role.'',1;
IF NOT EXISTS (SELECT 1 FROM sys.database_role_members WHERE role_principal_id=DATABASE_PRINCIPAL_ID(N''EHFApplicationRuntime'') AND member_principal_id=DATABASE_PRINCIPAL_ID(N''ehf_app'')) THROW 51725,''Expected database user lacks its runtime role.'',1;';
EXEC(@Check);
DECLARE @Ddl nvarchar(max)=N'CREATE LOGIN '+QUOTENAME(@LoginName)+N' WITH PASSWORD=N'+QUOTENAME(@Password,N'''')+N', CHECK_POLICY=ON, CHECK_EXPIRATION=OFF, DEFAULT_DATABASE='+QUOTENAME(@DatabaseName)+N';';
EXEC(@Ddl);
DECLARE @Permission sysname;
DECLARE DenyCursor CURSOR LOCAL FAST_FORWARD FOR SELECT PermissionName FROM (VALUES
 (N'ALTER ANY LOGIN'),(N'ALTER ANY SERVER ROLE'),(N'CONTROL SERVER'),(N'VIEW ANY DATABASE'),(N'VIEW ANY DEFINITION'),(N'VIEW SERVER STATE')) AS expected(PermissionName);
OPEN DenyCursor; FETCH NEXT FROM DenyCursor INTO @Permission;
WHILE @@FETCH_STATUS=0 BEGIN
  SET @Ddl=N'DENY '+@Permission+N' TO '+QUOTENAME(@LoginName)+N';'; EXEC(@Ddl);
  FETCH NEXT FROM DenyCursor INTO @Permission;
END; CLOSE DenyCursor; DEALLOCATE DenyCursor;
""", (login, password, database))


def create_test_database(connection, database: str, run_token: str) -> None:
    validate_command_arguments("create-test-database", SERVER, database, None, None, run_token=run_token)
    connection.autocommit = True
    _execute(connection, """
DECLARE @DatabaseName sysname=?;
IF DB_ID(@DatabaseName) IS NOT NULL THROW 51710, 'Test database already exists.', 1;
DECLARE @Ddl nvarchar(max)=N'CREATE DATABASE '+QUOTENAME(@DatabaseName)+N';'; EXEC(@Ddl);
""", (database,))
    _execute(connection, """
DECLARE @DatabaseName sysname=?; DECLARE @RunToken nvarchar(64)=?;
DECLARE @Sql nvarchar(max)=N'USE '+QUOTENAME(@DatabaseName)+N'; EXEC sys.sp_addextendedproperty @name=N''EHF.Task4RunToken'', @value=@RunToken;';
EXEC sys.sp_executesql @Sql, N'@RunToken nvarchar(64)', @RunToken;
""", (database, run_token))


def create_test_login(connection, database: str, login: str, credential_file: Path) -> None:
    validate_command_arguments("create-test-login", SERVER, database, login, None, login)
    password = read_credential(credential_file, "test")
    _require_safe_password(password)
    connection.autocommit = True
    _execute(connection, """
DECLARE @LoginName sysname=?; DECLARE @Password nvarchar(128)=?; DECLARE @DatabaseName sysname=?;
IF SUSER_ID(@LoginName) IS NOT NULL THROW 51711, 'Test login already exists.', 1;
DECLARE @Ddl nvarchar(max)=N'CREATE LOGIN '+QUOTENAME(@LoginName)+N' WITH PASSWORD=N'+QUOTENAME(@Password,N'''')+N', CHECK_POLICY=ON, CHECK_EXPIRATION=OFF, DEFAULT_DATABASE='+QUOTENAME(@DatabaseName)+N';'; EXEC(@Ddl);
""", (login, password, database))


def _map_user(connection, database: str, login: str, user: str, production: bool) -> None:
    connection.autocommit = True
    _execute(connection, """
DECLARE @DatabaseName sysname=?; DECLARE @LoginName sysname=?; DECLARE @UserName sysname=?; DECLARE @AllowCreate bit=?;
DECLARE @Sql nvarchar(max)=N'USE '+QUOTENAME(@DatabaseName)+N';
DECLARE @ExistingSid varbinary(85), @Auth nvarchar(60);
SELECT @ExistingSid=sid,@Auth=authentication_type_desc FROM sys.database_principals WHERE name=@UserName AND type_desc=N''SQL_USER'';
IF @ExistingSid IS NULL
BEGIN
  IF @AllowCreate=0 THROW 51722,''Expected database user is unavailable.'',1;
  DECLARE @Create nvarchar(max)=N''CREATE USER ''+QUOTENAME(@UserName)+N'' FOR LOGIN ''+QUOTENAME(@LoginName)+N'';''; EXEC(@Create);
END
ELSE IF @Auth=N''NONE''
BEGIN
  DECLARE @Map nvarchar(max)=N''ALTER USER ''+QUOTENAME(@UserName)+N'' WITH LOGIN = ''+QUOTENAME(@LoginName)+N'';''; EXEC(@Map);
END
ELSE IF @ExistingSid<>SUSER_SID(@LoginName) THROW 51723,''Expected database user maps to another login.'',1;
IF @AllowCreate=1
BEGIN
  DECLARE @Revoke nvarchar(max)=N''REVOKE CONNECT FROM ''+QUOTENAME(@UserName)+N'';''; EXEC(@Revoke);
END;
IF NOT EXISTS (SELECT 1 FROM sys.database_role_members WHERE role_principal_id=DATABASE_PRINCIPAL_ID(N''EHFApplicationRuntime'') AND member_principal_id=DATABASE_PRINCIPAL_ID(@UserName))
BEGIN DECLARE @Role nvarchar(max)=N''ALTER ROLE [EHFApplicationRuntime] ADD MEMBER ''+QUOTENAME(@UserName)+N'';''; EXEC(@Role); END;
IF EXISTS (SELECT 1 FROM sys.database_role_members AS m INNER JOIN sys.database_principals AS r ON r.principal_id=m.role_principal_id WHERE m.member_principal_id=DATABASE_PRINCIPAL_ID(@UserName) AND r.name<>N''EHFApplicationRuntime'') THROW 51724,''Expected database user has an unexpected role.'',1;
IF EXISTS (SELECT 1 FROM sys.database_permissions WHERE grantee_principal_id=DATABASE_PRINCIPAL_ID(@UserName)) THROW 51726,''Expected database user has direct permissions.'',1;';
EXEC sys.sp_executesql @Sql,N'@LoginName sysname,@UserName sysname,@AllowCreate bit',@LoginName,@UserName,@AllowCreate;
""", (database, login, user, 0 if production else 1))


def map_production_user(connection, database: str, login: str, user: str) -> None:
    validate_command_arguments("map-production-user", SERVER, database, login, None, user)
    _map_user(connection, database, login, user, True)


def map_test_user(connection, database: str, login: str, user: str) -> None:
    validate_command_arguments("map-test-user", SERVER, database, login, None, user)
    _map_user(connection, database, login, user, False)


def require_no_cross_database_access(rows: Iterable[object], _database: str) -> None:
    if any(True for _ in rows):
        raise PrincipalError("Expected login has cross-database ownership or mapping")


def _cross_database_rows(connection, database: str, login: str) -> list[object]:
    return _rows(connection, """
DECLARE @ExpectedDatabase sysname=?; DECLARE @LoginName sysname=?;
CREATE TABLE #Finding (DatabaseName sysname NOT NULL, Finding varchar(48) NOT NULL);
INSERT #Finding SELECT d.name,'DATABASE_OWNER' FROM sys.databases d INNER JOIN sys.server_principals p ON p.sid=d.owner_sid WHERE p.name=@LoginName;
DECLARE @Sql nvarchar(max)=N'';
SELECT @Sql += N'USE '+QUOTENAME(name)+N'; IF DB_NAME()<>@ExpectedDatabase AND EXISTS (SELECT 1 FROM sys.database_principals WHERE sid=SUSER_SID(@LoginName)) INSERT #Finding VALUES (DB_NAME(),''DATABASE_PRINCIPAL'');'
FROM sys.databases WHERE state_desc=N'ONLINE' AND source_database_id IS NULL;
EXEC sys.sp_executesql @Sql,N'@ExpectedDatabase sysname,@LoginName sysname',@ExpectedDatabase,@LoginName;
SELECT DatabaseName,Finding FROM #Finding WHERE DatabaseName<>@ExpectedDatabase;
""", (database, login))


def _inspect_production_state(connection, database: str, login: str, user: str) -> str:
    rows = _rows(connection, """
DECLARE @LoginName sysname=?; DECLARE @DatabaseName sysname=?; DECLARE @UserName sysname=?;
IF SUSER_ID(@LoginName) IS NULL SELECT 'ABSENT' AS State;
ELSE IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name=@LoginName AND type_desc=N'SQL_LOGIN' AND is_disabled=0 AND default_database_name=@DatabaseName) SELECT 'INVALID' AS State;
ELSE IF EXISTS (SELECT 1 FROM sys.server_role_members m INNER JOIN sys.server_principals p ON p.principal_id=m.member_principal_id WHERE p.name=@LoginName) SELECT 'INVALID' AS State;
ELSE IF EXISTS (SELECT 1 FROM sys.server_permissions p WHERE p.grantee_principal_id=SUSER_ID(@LoginName) AND (p.state_desc<>N'DENY' OR p.permission_name NOT IN (N'ALTER ANY LOGIN',N'ALTER ANY SERVER ROLE',N'CONTROL SERVER',N'VIEW ANY DATABASE',N'VIEW ANY DEFINITION',N'VIEW SERVER STATE'))) SELECT 'INVALID' AS State;
ELSE IF (SELECT COUNT(*) FROM sys.server_permissions WHERE grantee_principal_id=SUSER_ID(@LoginName) AND state_desc=N'DENY' AND permission_name IN (N'ALTER ANY LOGIN',N'ALTER ANY SERVER ROLE',N'CONTROL SERVER',N'VIEW ANY DATABASE',N'VIEW ANY DEFINITION',N'VIEW SERVER STATE'))<>6 SELECT 'INVALID' AS State;
ELSE
BEGIN
 DECLARE @Sql nvarchar(max)=N'USE '+QUOTENAME(@DatabaseName)+N';
 DECLARE @Auth nvarchar(60),@Sid varbinary(85); SELECT @Auth=authentication_type_desc,@Sid=sid FROM sys.database_principals WHERE name=@UserName AND type_desc=N''SQL_USER'';
 IF @Auth IS NULL SELECT ''INVALID'' AS State;
 ELSE IF EXISTS (SELECT 1 FROM sys.schemas WHERE principal_id=DATABASE_PRINCIPAL_ID(@UserName)) SELECT ''INVALID'' AS State;
 ELSE IF EXISTS (SELECT 1 FROM sys.database_permissions WHERE grantee_principal_id=DATABASE_PRINCIPAL_ID(@UserName)) SELECT ''INVALID'' AS State;
 ELSE IF EXISTS (SELECT 1 FROM sys.database_role_members m INNER JOIN sys.database_principals r ON r.principal_id=m.role_principal_id WHERE m.member_principal_id=DATABASE_PRINCIPAL_ID(@UserName) AND r.name<>N''EHFApplicationRuntime'') SELECT ''INVALID'' AS State;
 ELSE IF NOT EXISTS (SELECT 1 FROM sys.database_role_members WHERE role_principal_id=DATABASE_PRINCIPAL_ID(N''EHFApplicationRuntime'') AND member_principal_id=DATABASE_PRINCIPAL_ID(@UserName)) SELECT ''INVALID'' AS State;
 ELSE IF @Auth=N''NONE'' SELECT ''UNMAPPED'' AS State;
 ELSE IF @Sid<>SUSER_SID(@LoginName) SELECT ''INVALID'' AS State;
 ELSE SELECT ''READY'' AS State;';
 EXEC sys.sp_executesql @Sql,N'@LoginName sysname,@UserName sysname',@LoginName,@UserName;
END;
""", (login, database, user))
    if len(rows) != 1:
        raise PrincipalError("Expected login inspection is ambiguous")
    return str(rows[0][0])


def inspect_production(connection, database: str, login: str, user: str) -> str:
    validate_command_arguments("inspect-production", SERVER, database, login, None, user)
    state = _inspect_production_state(connection, database, login, user)
    if state not in {"ABSENT", "UNMAPPED", "READY"}:
        raise PrincipalError("Expected login has an unexpected shape")
    require_no_cross_database_access(_cross_database_rows(connection, database, login), database)
    return state


def require_no_effective_cross_database_access(
    admin_connection, server: str, database: str, login: str, credential_file: Path
) -> None:
    """Prove that the authenticating runtime token cannot enter another user DB."""
    password = read_credential(credential_file, "application")
    _require_safe_password(password)
    rows = _rows(
        admin_connection,
        "SELECT name FROM sys.databases WHERE state_desc=N'ONLINE' AND database_id>4 AND name<>? AND source_database_id IS NULL;",
        (database,),
    )
    for row in rows:
        candidate = str(row[0])
        runtime = None
        try:
            runtime = _connect(server, candidate, login, password)
            actual = _rows(runtime, "SELECT DB_NAME();")
            if len(actual) == 1 and str(actual[0][0]) == candidate:
                raise PrincipalError("Expected login has effective cross-database access")
        except pyodbc.Error:
            continue
        finally:
            if runtime is not None:
                runtime.close()


def authenticate_login(server: str, database: str, login: str, credential_file: Path, kind: str) -> None:
    validate_command_arguments("authenticate-login", server, database, login, None)
    password = read_credential(credential_file, kind)
    _require_safe_password(password)
    connection = _connect(server, database, login, password)
    try:
        rows = _rows(connection, "SELECT SUSER_SNAME(), ORIGINAL_LOGIN(), DB_NAME();")
        if len(rows) != 1 or tuple(rows[0]) != (login, login, database):
            raise PrincipalError("Credential did not authenticate the expected login")
    finally:
        connection.close()


def record_test_migration(connection, database: str, migration_file: str) -> None:
    validate_command_arguments("record-test-migration", SERVER, database, "ehf_app_test_" + (_test_suffix(database) or ""), None)
    if migration_file not in MIGRATIONS:
        raise PrincipalError("Unexpected principal target")
    content = (Path(__file__).resolve().parents[1] / "database" / "migrations" / migration_file).read_bytes()
    version, name = MIGRATIONS[migration_file]
    _execute(connection, "INSERT dbo.SchemaMigration (MigrationVersion, MigrationName, ChecksumSha256) VALUES (?, ?, ?);", (version, name, hashlib.sha256(content).digest()))


def exercise_test_status(admin_connection, server: str, database: str, login: str, credential_file: Path) -> None:
    validate_command_arguments("exercise-test-status", server, database, login, None, login)
    cursor = admin_connection.cursor()
    cursor.execute("""
DECLARE @CallId uniqueidentifier=NEWID(),@ApplicantId uniqueidentifier=NEWID(),@ApplicationId uniqueidentifier=NEWID();
INSERT dbo.FellowshipCall (FellowshipCallId,CallCode,DisplayName,CallStatus,ApplicationDeadlineUtc) VALUES (@CallId,N'SQL-PERM-SYNTHETIC',N'Synthetic SQL permission fixture',N'OPEN',DATEADD(day,1,SYSUTCDATETIME()));
INSERT dbo.Applicant (ApplicantId,LegalGivenNames,LegalFamilyName) VALUES (@ApplicantId,N'Synthetic',N'Validator');
INSERT dbo.Application (ApplicationId,FellowshipCallId,ApplicantId,ApplicationStatus) VALUES (@ApplicationId,@CallId,@ApplicantId,'DRAFT');
SELECT @ApplicationId,RowVersion FROM dbo.Application WHERE ApplicationId=@ApplicationId;
""")
    fixture = first_result_row(cursor); admin_connection.commit()
    if not fixture or len(fixture) != 2:
        raise PrincipalError("Synthetic status fixture is unavailable")
    application_id, row_version = fixture
    password = read_credential(credential_file, "test"); _require_safe_password(password)
    runtime = _connect(server, database, login, password)
    try:
        runtime.cursor().execute("EXEC dbo.SetApplicationStatus ?, ?, ?, ?;", application_id, "IN_REVIEW", "isolated-runtime-validator", row_version); runtime.commit()
    finally:
        runtime.close()
    _execute(admin_connection, """
DECLARE @ApplicationId uniqueidentifier=?;
IF NOT EXISTS (SELECT 1 FROM dbo.Application a INNER JOIN dbo.AuditEvent e ON e.ApplicationId=a.ApplicationId WHERE a.ApplicationId=@ApplicationId AND a.ApplicationStatus='IN_REVIEW' AND e.EventType='APPLICATION_STATUS_CHANGED' AND e.ActorIdentity=N'isolated-runtime-validator') THROW 51740,'The status procedure did not persist its audit state.',1;
""", (application_id,))


def _database_marker(connection, database: str) -> str | None:
    rows = _rows(connection, """
DECLARE @DatabaseName sysname=?; DECLARE @MarkerName sysname=?; DECLARE @Value nvarchar(128)=NULL;
IF DB_ID(@DatabaseName) IS NOT NULL BEGIN
 DECLARE @Sql nvarchar(max)=N'USE '+QUOTENAME(@DatabaseName)+N'; SELECT @Out=CONVERT(nvarchar(128),value) FROM sys.extended_properties WHERE class=0 AND name=@MarkerName;';
 EXEC sys.sp_executesql @Sql,N'@MarkerName sysname,@Out nvarchar(128) OUTPUT',@MarkerName,@Value OUTPUT;
END; SELECT @Value;
""", (database, MARKER_NAME))
    return str(rows[0][0]) if rows and rows[0][0] is not None else None


def _database_exists(connection, database: str) -> bool:
    return bool(_rows(connection, "SELECT name FROM sys.databases WHERE name=?;", (database,)))


def _drop_owned_database(connection, database: str, token: str) -> str:
    if not _database_exists(connection, database):
        return "ABSENT"
    if _database_marker(connection, database) != token:
        return "PRESERVED"
    _execute(connection, """
DECLARE @DatabaseName sysname=?; DECLARE @Ddl nvarchar(max)=N'ALTER DATABASE '+QUOTENAME(@DatabaseName)+N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE '+QUOTENAME(@DatabaseName)+N';'; EXEC(@Ddl);
""", (database,))
    return "REMOVED"


def _test_login_exists(connection, login: str) -> bool:
    return bool(_rows(connection, "SELECT name FROM sys.server_principals WHERE name=? AND type_desc=N'SQL_LOGIN';", (login,)))


def _test_login_shape(connection, database: str, login: str) -> bool:
    rows = _rows(connection, """
DECLARE @LoginName sysname=?,@DatabaseName sysname=?;
SELECT CASE WHEN EXISTS (SELECT 1 FROM sys.server_principals WHERE name=@LoginName AND type_desc=N'SQL_LOGIN' AND is_disabled=0 AND default_database_name=@DatabaseName)
 AND NOT EXISTS (SELECT 1 FROM sys.server_role_members m INNER JOIN sys.server_principals p ON p.principal_id=m.member_principal_id WHERE p.name=@LoginName)
 AND NOT EXISTS (SELECT 1 FROM sys.server_permissions WHERE grantee_principal_id=SUSER_ID(@LoginName) AND NOT (permission_name=N'CONNECT SQL' AND state_desc=N'GRANT')) THEN 1 ELSE 0 END;
""", (login, database))
    return len(rows) == 1 and int(rows[0][0]) == 1


def cleanup_test_targets(connection, database: str, peer_database: str, login: str, run_token: str, server: str = SERVER) -> None:
    validate_command_arguments("cleanup-test-targets", server, database, login, peer_database, run_token=run_token)
    connection.autocommit = True
    marker_fallback = (
        _database_marker(connection, database) == run_token
        and _database_marker(connection, peer_database) == run_token
    )
    # Authenticate and drop the login first: its default database is the primary
    # disposable database and removing that database first can prevent login.
    login_state = "ABSENT"
    if _test_login_exists(connection, login):
        if not _test_login_shape(connection, database, login):
            login_state = "PRESERVED"
        else:
            login_state = "REMOVED" if marker_fallback else "PRESERVED"
            if login_state == "REMOVED":
                _execute(connection, "DECLARE @LoginName sysname=?; DECLARE @Ddl nvarchar(max)=N'DROP LOGIN '+QUOTENAME(@LoginName)+N';'; EXEC(@Ddl);", (login,))
    peer = _drop_owned_database(connection, peer_database, run_token)
    primary = _drop_owned_database(connection, database, run_token)
    if "PRESERVED" in {peer, primary, login_state}:
        raise PrincipalError("Test principal cleanup ownership evidence is insufficient")


def verify_test_cleanup(connection, database: str, peer_database: str, login: str, run_token: str) -> None:
    validate_command_arguments("verify-test-cleanup", SERVER, database, login, peer_database, run_token=run_token)
    if _database_marker(connection, database) == run_token or _database_marker(connection, peer_database) == run_token or _test_login_exists(connection, login):
        raise PrincipalError("Test principal cleanup verification failed")


def verify_test_targets_preserved(connection, database: str, login: str, run_token: str, credential_file: Path, server: str = SERVER) -> None:
    validate_command_arguments("verify-test-targets-preserved", server, database, login, None, run_token=run_token)
    if _database_marker(connection, database) != run_token or not _test_login_exists(connection, login) or not _test_login_shape(connection, database, login):
        raise PrincipalError("Test principal preservation verification failed")


def admin_connection_database(command: str, database: str) -> str:
    return database if command in {"record-test-migration", "exercise-test-status"} else "master"


def _admin_connection(arguments):
    return connect_admin(arguments.server, Path(arguments.admin_credential_file), admin_connection_database(arguments.command, arguments.database))


def dispatch(arguments) -> None:
    command = arguments.command
    validate_command_arguments(command, arguments.server, getattr(arguments, "database", None), getattr(arguments, "login", None), getattr(arguments, "peer_database", None), getattr(arguments, "user", None), getattr(arguments, "run_token", None))
    if command == "authenticate-login":
        authenticate_login(arguments.server, arguments.database, arguments.login, Path(arguments.credential_file), arguments.credential_kind); return
    connection = _admin_connection(arguments)
    try:
        if command == "inspect-production":
            state = inspect_production(connection, arguments.database, arguments.login, arguments.user)
            if getattr(arguments, "credential_file", None):
                require_no_effective_cross_database_access(connection, arguments.server, arguments.database, arguments.login, Path(arguments.credential_file))
            print(state.lower())
        elif command == "create-production-login": create_production_login(connection, arguments.database, arguments.login, Path(arguments.credential_file))
        elif command == "map-production-user": map_production_user(connection, arguments.database, arguments.login, arguments.user)
        elif command == "create-test-database": create_test_database(connection, arguments.database, arguments.run_token)
        elif command == "create-test-login": create_test_login(connection, arguments.database, arguments.login, Path(arguments.credential_file))
        elif command == "map-test-user": map_test_user(connection, arguments.database, arguments.login, arguments.user)
        elif command == "record-test-migration": record_test_migration(connection, arguments.database, arguments.migration_file)
        elif command == "exercise-test-status": exercise_test_status(connection, arguments.server, arguments.database, arguments.login, Path(arguments.credential_file))
        elif command == "cleanup-test-targets": cleanup_test_targets(connection, arguments.database, arguments.peer_database, arguments.login, arguments.run_token, arguments.server)
        elif command == "verify-test-cleanup": verify_test_cleanup(connection, arguments.database, arguments.peer_database, arguments.login, arguments.run_token)
        elif command == "verify-test-targets-preserved": verify_test_targets_preserved(connection, arguments.database, arguments.login, arguments.run_token, Path(arguments.credential_file), arguments.server)
    finally:
        connection.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(add_help=False); subparsers = result.add_subparsers(dest="command", required=True)
    for command in COMMANDS:
        item = subparsers.add_parser(command, add_help=False); item.add_argument("--server", required=True)
        if command != "authenticate-login": item.add_argument("--admin-credential-file", required=True)
        if command != "create-test-database": item.add_argument("--database", required=True)
        else: item.add_argument("--database", required=True)
        if command in {"inspect-production", "map-production-user", "map-test-user"}: item.add_argument("--user", required=True)
        if command in {"inspect-production", "authenticate-login", "create-production-login", "map-production-user", "create-test-login", "map-test-user", "exercise-test-status", "cleanup-test-targets", "verify-test-cleanup", "verify-test-targets-preserved"}: item.add_argument("--login", required=True)
        if command in {"authenticate-login", "create-production-login", "create-test-login", "exercise-test-status", "verify-test-targets-preserved"}: item.add_argument("--credential-file", required=True)
        elif command == "inspect-production": item.add_argument("--credential-file")
        if command == "authenticate-login": item.add_argument("--credential-kind", choices=("application", "test"), required=True)
        if command in {"cleanup-test-targets", "verify-test-cleanup"}: item.add_argument("--peer-database", required=True)
        if command in {"create-test-database", "cleanup-test-targets", "verify-test-cleanup", "verify-test-targets-preserved"}: item.add_argument("--run-token", required=True)
        if command == "record-test-migration": item.add_argument("--migration-file", required=True, choices=tuple(MIGRATIONS))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    try:
        dispatch(parser().parse_args(argv)); return 0
    except Exception:
        print("SQL_PRINCIPAL_ERROR: OPERATION_FAILED", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
