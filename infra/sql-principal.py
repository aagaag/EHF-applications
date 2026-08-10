#!/usr/bin/env python3
"""Fixed-purpose SQL Server principal lifecycle helper for EHF Applications.

This helper intentionally exposes no SQL text, query-file, or connection-string
arguments. It reads credentials only from verified root-owned regular files and
uses ODBC parameters for every value. SQL Server DDL identifiers are constructed
only inside fixed T-SQL blocks with QUOTENAME.
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
except ImportError:  # pragma: no cover - exercised by deployment prerequisite checks.
    class _MissingPyodbc:
        class Error(Exception):
            pass

        @staticmethod
        def connect(*_args, **_kwargs):
            raise PrincipalError("The pinned pyodbc runtime is unavailable")

    pyodbc = _MissingPyodbc()

try:  # The helper runs on Linux; this keeps its fake-driver unit tests portable.
    import grp
except ImportError:  # pragma: no cover - Windows has no POSIX group database.
    grp = None


SERVER = "tcp:127.0.0.1,1433"
PRODUCTION_DATABASE = "EHFApplications"
PRODUCTION_LOGIN = "ehf_app"
PRODUCTION_USER = "ehf_app"
TEST_SUFFIX = re.compile(r"^[a-f0-9]{24}$")
TEST_DATABASE = re.compile(r"^EHFApplications_Test_sqlperm_([a-f0-9]{24})$")
TEST_PEER_DATABASE = re.compile(r"^EHFApplications_Test_sqlperm_peer_([a-f0-9]{24})$")
TEST_LOGIN = re.compile(r"^ehf_app_test_([a-f0-9]{24})$")
SAFE_PASSWORD = re.compile(r"^[A-Za-z0-9._~-]{48}$")
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
)


class PrincipalError(RuntimeError):
    pass


def _require_server(server: str) -> None:
    if server != SERVER:
        raise PrincipalError("Unexpected SQL Server target")


def _test_suffix(database: str) -> str | None:
    primary = TEST_DATABASE.fullmatch(database)
    peer = TEST_PEER_DATABASE.fullmatch(database)
    return (primary or peer).group(1) if primary or peer else None


def validate_target_names(database: str, login: str, user: str) -> None:
    if (database, login, user) == (
        PRODUCTION_DATABASE,
        PRODUCTION_LOGIN,
        PRODUCTION_USER,
    ):
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


def _credential_mode(kind: str) -> tuple[int, int | None]:
    if kind == "admin":
        return 0o600, 0
    if kind == "application":
        try:
            if grp is None:
                raise KeyError
            return 0o640, grp.getgrnam("ehf").gr_gid
        except KeyError as error:
            raise PrincipalError("Protected application credential group is unavailable") from error
    if kind == "test":
        return 0o600, 0
    raise PrincipalError("Unexpected credential purpose")


def read_credential(path: Path, kind: str) -> str:
    try:
        metadata = path.lstat()
        expected_mode, expected_group = _credential_mode(kind)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != expected_mode
            or (expected_group is not None and metadata.st_gid != expected_group)
        ):
            raise PrincipalError("Protected credential file has an unexpected shape")
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise PrincipalError("Protected credential file is unavailable") from error
    if not value or "\n" in value or "\r" in value:
        raise PrincipalError("Protected credential file has an unexpected shape")
    return value


def _require_safe_password(value: str) -> None:
    if (
        not SAFE_PASSWORD.fullmatch(value)
        or not re.search(r"[A-Z]", value)
        or not re.search(r"[a-z]", value)
        or not re.search(r"[0-9]", value)
        or not re.search(r"[._~-]", value)
    ):
        raise PrincipalError("Protected credential file has an unexpected shape")


def _connect(server: str, database: str | None, login: str, password: str):
    _require_server(server)
    parts = [
        "DRIVER={ODBC Driver 18 for SQL Server}",
        f"SERVER={server}",
        f"UID={login}",
        f"PWD={password}",
        "Encrypt=yes",
        "TrustServerCertificate=yes",
    ]
    if database:
        parts.append(f"DATABASE={database}")
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
    validate_target_names(database, login, PRODUCTION_USER)
    password = read_credential(credential_file, "application")
    _require_safe_password(password)
    connection.autocommit = True
    _execute(
        connection,
        """
DECLARE @LoginName sysname = ?;
DECLARE @Password nvarchar(128) = ?;
DECLARE @DefaultDatabase sysname = ?;
IF @LoginName <> N'ehf_app' OR @DefaultDatabase <> N'EHFApplications'
    THROW 51700, 'Unexpected principal target.', 1;
IF SUSER_ID(@LoginName) IS NOT NULL
    THROW 51701, 'Expected login already exists.', 1;
IF DB_ID(@DefaultDatabase) IS NULL
    THROW 51702, 'Expected database is unavailable.', 1;
DECLARE @CheckSql nvarchar(max) = N'USE ' + QUOTENAME(@DefaultDatabase) + N';
DECLARE @AuthenticationType nvarchar(60);
SELECT @AuthenticationType = authentication_type_desc
FROM sys.database_principals WHERE name = @LoginName AND type_desc = N''SQL_USER'';
IF @AuthenticationType <> N''NONE''
    THROW 51703, ''Expected database user has an unexpected shape.'', 1;
IF EXISTS
(
    SELECT 1 FROM sys.database_role_members AS membership
    INNER JOIN sys.database_principals AS role_row
      ON role_row.principal_id = membership.role_principal_id
    INNER JOIN sys.database_principals AS member_row
      ON member_row.principal_id = membership.member_principal_id
    WHERE member_row.name = @LoginName
      AND role_row.name NOT IN (N''public'', N''EHFApplicationRuntime'')
)
    THROW 51704, ''Expected database user has an unexpected role.'', 1;
IF NOT EXISTS
(
    SELECT 1 FROM sys.database_role_members
    WHERE role_principal_id = DATABASE_PRINCIPAL_ID(N''EHFApplicationRuntime'')
      AND member_principal_id = DATABASE_PRINCIPAL_ID(@LoginName)
)
    THROW 51705, ''Expected database user lacks its runtime role.'', 1;';
EXEC sys.sp_executesql @CheckSql, N'@LoginName sysname', @LoginName;
DECLARE @Ddl nvarchar(max) = N'CREATE LOGIN ' + QUOTENAME(@LoginName)
    + N' WITH PASSWORD = N' + QUOTENAME(@Password, N'''')
    + N', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF, DEFAULT_DATABASE = '
    + QUOTENAME(@DefaultDatabase) + N';';
EXEC(@Ddl);
""",
        (login, password, database),
    )


def create_test_database(connection, database: str) -> None:
    if not TEST_DATABASE.fullmatch(database) and not TEST_PEER_DATABASE.fullmatch(database):
        raise PrincipalError("Unexpected principal target")
    connection.autocommit = True
    _execute(
        connection,
        """
DECLARE @DatabaseName sysname = ?;
IF DB_ID(@DatabaseName) IS NOT NULL
    THROW 51710, 'Test database already exists.', 1;
DECLARE @Ddl nvarchar(max) = N'CREATE DATABASE ' + QUOTENAME(@DatabaseName) + N';';
EXEC(@Ddl);
""",
        (database,),
    )


def create_test_login(connection, database: str, login: str, credential_file: Path) -> None:
    validate_target_names(database, login, login)
    if database == PRODUCTION_DATABASE:
        raise PrincipalError("Unexpected principal target")
    password = read_credential(credential_file, "test")
    _require_safe_password(password)
    connection.autocommit = True
    _execute(
        connection,
        """
DECLARE @LoginName sysname = ?;
DECLARE @Password nvarchar(128) = ?;
DECLARE @DefaultDatabase sysname = ?;
IF SUSER_ID(@LoginName) IS NOT NULL
    THROW 51711, 'Test login already exists.', 1;
DECLARE @Ddl nvarchar(max) = N'CREATE LOGIN ' + QUOTENAME(@LoginName)
    + N' WITH PASSWORD = N' + QUOTENAME(@Password, N'''')
    + N', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF, DEFAULT_DATABASE = '
    + QUOTENAME(@DefaultDatabase) + N';';
EXEC(@Ddl);
""",
        (login, password, database),
    )


def map_production_user(connection, database: str, login: str, user: str) -> None:
    validate_target_names(database, login, user)
    connection.autocommit = True
    _execute(
        connection,
        """
DECLARE @DatabaseName sysname = ?;
DECLARE @LoginName sysname = ?;
DECLARE @UserName sysname = ?;
DECLARE @LoginSid varbinary(85) = SUSER_SID(@LoginName);
IF @LoginSid IS NULL
    THROW 51720, 'Expected login is unavailable.', 1;
IF DB_ID(@DatabaseName) IS NULL
    THROW 51721, 'Expected database is unavailable.', 1;
DECLARE @Sql nvarchar(max) = N'USE ' + QUOTENAME(@DatabaseName) + N';
DECLARE @AuthenticationType nvarchar(60);
DECLARE @ExistingSid varbinary(85);
SELECT @AuthenticationType = authentication_type_desc, @ExistingSid = sid
FROM sys.database_principals WHERE name = @UserName AND type_desc = N''SQL_USER'';
IF @AuthenticationType IS NULL THROW 51722, ''Expected database user is unavailable.'', 1;
IF @AuthenticationType = N''NONE''
BEGIN
    DECLARE @MapSql nvarchar(max) = N''ALTER USER '' + QUOTENAME(@UserName) + N'' WITH LOGIN = '' + QUOTENAME(@LoginName) + N'';'';
    EXEC(@MapSql);
END
ELSE IF @ExistingSid <> @LoginSid
    THROW 51723, ''Expected database user maps to another login.'', 1;
IF EXISTS
(
    SELECT 1 FROM sys.database_role_members AS membership
    INNER JOIN sys.database_principals AS role_row
      ON role_row.principal_id = membership.role_principal_id
    INNER JOIN sys.database_principals AS member_row
      ON member_row.principal_id = membership.member_principal_id
    WHERE member_row.name = @UserName
      AND role_row.name NOT IN (N''public'', N''EHFApplicationRuntime'')
)
    THROW 51724, ''Expected database user has an unexpected role.'', 1;
IF NOT EXISTS
(
    SELECT 1 FROM sys.database_role_members
    WHERE role_principal_id = DATABASE_PRINCIPAL_ID(N''EHFApplicationRuntime'')
      AND member_principal_id = DATABASE_PRINCIPAL_ID(@UserName)
)
    THROW 51725, ''Expected database user lacks its runtime role.'', 1;';
EXEC sys.sp_executesql @Sql,
    N'@LoginName sysname, @UserName sysname, @LoginSid varbinary(85)',
    @LoginName, @UserName, @LoginSid;
""",
        (database, login, user),
    )


def map_test_user(connection, database: str, login: str, user: str) -> None:
    validate_target_names(database, login, user)
    if database == PRODUCTION_DATABASE:
        raise PrincipalError("Unexpected principal target")
    connection.autocommit = True
    _execute(
        connection,
        """
DECLARE @DatabaseName sysname = ?;
DECLARE @LoginName sysname = ?;
DECLARE @UserName sysname = ?;
DECLARE @LoginSid varbinary(85) = SUSER_SID(@LoginName);
IF @LoginSid IS NULL THROW 51730, 'Test login is unavailable.', 1;
DECLARE @Sql nvarchar(max) = N'USE ' + QUOTENAME(@DatabaseName) + N';
IF DATABASE_PRINCIPAL_ID(@UserName) IS NOT NULL
    THROW 51731, ''Test user already exists.'', 1;
DECLARE @CreateUserSql nvarchar(max) = N''CREATE USER '' + QUOTENAME(@UserName) + N'' FOR LOGIN '' + QUOTENAME(@LoginName) + N'';'';
EXEC(@CreateUserSql);
DECLARE @RoleSql nvarchar(max) = N''ALTER ROLE [EHFApplicationRuntime] ADD MEMBER '' + QUOTENAME(@UserName) + N'';'';
EXEC(@RoleSql);
IF NOT EXISTS
(
    SELECT 1 FROM sys.database_role_members
    WHERE role_principal_id = DATABASE_PRINCIPAL_ID(N''EHFApplicationRuntime'')
      AND member_principal_id = DATABASE_PRINCIPAL_ID(@UserName)
)
    THROW 51732, ''Test user lacks its runtime role.'', 1;';
EXEC sys.sp_executesql @Sql, N'@LoginName sysname, @UserName sysname', @LoginName, @UserName;
""",
        (database, login, user),
    )


def require_no_cross_database_access(rows: Iterable[object], database: str) -> None:
    if any(True for _ in rows):
        raise PrincipalError("Expected login has cross-database ownership or mapping")


def _cross_database_rows(connection, database: str, login: str) -> list[object]:
    return _rows(
        connection,
        """
DECLARE @ExpectedDatabase sysname = ?;
DECLARE @LoginName sysname = ?;
CREATE TABLE #Finding (DatabaseName sysname NOT NULL, Finding varchar(32) NOT NULL);
INSERT #Finding (DatabaseName, Finding)
SELECT database_row.name, 'DATABASE_OWNER'
FROM sys.databases AS database_row
INNER JOIN sys.server_principals AS owner_row ON owner_row.sid = database_row.owner_sid
WHERE owner_row.name = @LoginName AND database_row.name <> @ExpectedDatabase;
DECLARE @Sql nvarchar(max) = N'';
SELECT @Sql += N'USE ' + QUOTENAME(name) + N';
IF DB_NAME() <> @ExpectedDatabase AND EXISTS
(
    SELECT 1 FROM sys.database_principals
    WHERE sid = SUSER_SID(@LoginName) AND type_desc = N''SQL_USER''
)
    INSERT #Finding VALUES (DB_NAME(), ''DATABASE_USER'');'
FROM sys.databases
WHERE state_desc = N'ONLINE' AND source_database_id IS NULL;
EXEC sys.sp_executesql @Sql, N'@ExpectedDatabase sysname, @LoginName sysname',
    @ExpectedDatabase, @LoginName;
SELECT DatabaseName, Finding FROM #Finding;
""",
        (database, login),
    )


def inspect_production(connection, database: str, login: str, user: str) -> str:
    validate_target_names(database, login, user)
    rows = _rows(
        connection,
        """
DECLARE @LoginName sysname = ?;
DECLARE @DatabaseName sysname = ?;
DECLARE @UserName sysname = ?;
IF SUSER_ID(@LoginName) IS NULL SELECT 'ABSENT' AS State;
ELSE IF NOT EXISTS
(
    SELECT 1 FROM sys.server_principals
    WHERE name = @LoginName AND type_desc = N'SQL_LOGIN' AND is_disabled = 0
      AND default_database_name = @DatabaseName
)
    SELECT 'INVALID' AS State;
ELSE IF EXISTS
(
    SELECT 1 FROM sys.server_role_members AS membership
    INNER JOIN sys.server_principals AS member_row
      ON member_row.principal_id = membership.member_principal_id
    WHERE member_row.name = @LoginName
)
    SELECT 'INVALID' AS State;
ELSE
BEGIN
    DECLARE @Sql nvarchar(max) = N'USE ' + QUOTENAME(@DatabaseName) + N';
    DECLARE @AuthenticationType nvarchar(60);
    DECLARE @UserSid varbinary(85);
    SELECT @AuthenticationType = authentication_type_desc, @UserSid = sid
    FROM sys.database_principals WHERE name = @UserName AND type_desc = N''SQL_USER'';
    IF @AuthenticationType IS NULL SELECT ''INVALID'' AS State;
    ELSE IF @AuthenticationType = N''NONE'' SELECT ''UNMAPPED'' AS State;
    ELSE IF @UserSid <> SUSER_SID(@LoginName) SELECT ''INVALID'' AS State;
    ELSE IF EXISTS
    (
        SELECT 1 FROM sys.database_role_members AS membership
        INNER JOIN sys.database_principals AS role_row
          ON role_row.principal_id = membership.role_principal_id
        INNER JOIN sys.database_principals AS member_row
          ON member_row.principal_id = membership.member_principal_id
        WHERE member_row.name = @UserName
          AND role_row.name NOT IN (N''public'', N''EHFApplicationRuntime'')
    ) SELECT ''INVALID'' AS State;
    ELSE IF NOT EXISTS
    (
        SELECT 1 FROM sys.database_role_members
        WHERE role_principal_id = DATABASE_PRINCIPAL_ID(N''EHFApplicationRuntime'')
          AND member_principal_id = DATABASE_PRINCIPAL_ID(@UserName)
    ) SELECT ''INVALID'' AS State;
    ELSE SELECT ''READY'' AS State;';
    EXEC sys.sp_executesql @Sql, N'@LoginName sysname, @UserName sysname', @LoginName, @UserName;
END;
""",
        (login, database, user),
    )
    if len(rows) != 1:
        raise PrincipalError("Expected login inspection is ambiguous")
    state = str(rows[0][0])
    if state not in {"ABSENT", "UNMAPPED", "READY"}:
        raise PrincipalError("Expected login has an unexpected shape")
    require_no_cross_database_access(_cross_database_rows(connection, database, login), database)
    return state


def authenticate_login(server: str, database: str, login: str, credential_file: Path, kind: str) -> None:
    validate_target_names(database, login, login)
    password = read_credential(credential_file, kind)
    _require_safe_password(password)
    connection = _connect(server, None, login, password)
    try:
        rows = _rows(connection, "SELECT SUSER_SNAME(), ORIGINAL_LOGIN(), DB_NAME();")
        if len(rows) != 1 or tuple(rows[0]) != (login, login, database):
            raise PrincipalError("Credential did not authenticate the expected login")
    finally:
        connection.close()


def record_test_migration(connection, database: str, migration_file: str) -> None:
    if not TEST_DATABASE.fullmatch(database) or migration_file not in MIGRATIONS:
        raise PrincipalError("Unexpected principal target")
    migration_path = Path(__file__).resolve().parents[1] / "database" / "migrations" / migration_file
    content = migration_path.read_bytes()
    version, name = MIGRATIONS[migration_file]
    _execute(
        connection,
        "INSERT dbo.SchemaMigration (MigrationVersion, MigrationName, ChecksumSha256) VALUES (?, ?, ?);",
        (version, name, hashlib.sha256(content).digest()),
    )


def exercise_test_status(
    admin_connection, server: str, database: str, login: str, credential_file: Path
) -> None:
    validate_target_names(database, login, login)
    if not TEST_DATABASE.fullmatch(database):
        raise PrincipalError("Unexpected principal target")
    cursor = admin_connection.cursor()
    cursor.execute(
        """
DECLARE @CallId uniqueidentifier = NEWID();
DECLARE @ApplicantId uniqueidentifier = NEWID();
DECLARE @ApplicationId uniqueidentifier = NEWID();
INSERT dbo.FellowshipCall
    (FellowshipCallId, CallCode, DisplayName, CallStatus, ApplicationDeadlineUtc)
VALUES (@CallId, N'SQL-PERM-SYNTHETIC', N'Synthetic SQL permission fixture', N'OPEN', DATEADD(day, 1, SYSUTCDATETIME()));
INSERT dbo.Applicant (ApplicantId, LegalGivenNames, LegalFamilyName)
VALUES (@ApplicantId, N'Synthetic', N'Validator');
INSERT dbo.Application (ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus)
VALUES (@ApplicationId, @CallId, @ApplicantId, 'DRAFT');
SELECT @ApplicationId, RowVersion FROM dbo.Application WHERE ApplicationId = @ApplicationId;
"""
    )
    fixture = first_result_row(cursor)
    admin_connection.commit()
    if not fixture or len(fixture) != 2:
        raise PrincipalError("Synthetic status fixture is unavailable")
    application_id, row_version = fixture
    password = read_credential(credential_file, "test")
    _require_safe_password(password)
    runtime_connection = _connect(server, database, login, password)
    try:
        runtime_cursor = runtime_connection.cursor()
        runtime_cursor.execute(
            "EXEC dbo.SetApplicationStatus ?, ?, ?, ?;",
            application_id,
            "IN_REVIEW",
            "isolated-runtime-validator",
            row_version,
        )
        runtime_connection.commit()
    finally:
        runtime_connection.close()
    _execute(
        admin_connection,
        """
DECLARE @ApplicationId uniqueidentifier = ?;
IF NOT EXISTS
(
    SELECT 1 FROM dbo.Application AS application_row
    INNER JOIN dbo.AuditEvent AS audit_row
      ON audit_row.ApplicationId = application_row.ApplicationId
    WHERE application_row.ApplicationId = @ApplicationId
      AND application_row.ApplicationStatus = 'IN_REVIEW'
      AND audit_row.EventType = 'APPLICATION_STATUS_CHANGED'
      AND audit_row.ActorIdentity = N'isolated-runtime-validator'
)
    THROW 51740, 'The status procedure did not persist its audit state.', 1;
""",
        (application_id,),
    )


def cleanup_test_targets(connection, database: str, peer_database: str, login: str) -> None:
    validate_test_targets(database, peer_database, login)
    connection.autocommit = True
    _execute(
        connection,
        """
DECLARE @DatabaseName sysname = ?;
IF DB_ID(@DatabaseName) IS NOT NULL
BEGIN
    DECLARE @Ddl nvarchar(max) = N'ALTER DATABASE ' + QUOTENAME(@DatabaseName)
        + N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE ' + QUOTENAME(@DatabaseName) + N';';
    EXEC(@Ddl);
END;
""",
        (peer_database,),
    )
    _execute(
        connection,
        """
DECLARE @DatabaseName sysname = ?;
IF DB_ID(@DatabaseName) IS NOT NULL
BEGIN
    DECLARE @Ddl nvarchar(max) = N'ALTER DATABASE ' + QUOTENAME(@DatabaseName)
        + N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE ' + QUOTENAME(@DatabaseName) + N';';
    EXEC(@Ddl);
END;
""",
        (database,),
    )
    _execute(
        connection,
        """
DECLARE @LoginName sysname = ?;
IF SUSER_ID(@LoginName) IS NOT NULL
BEGIN
    DECLARE @Ddl nvarchar(max) = N'DROP LOGIN ' + QUOTENAME(@LoginName) + N';';
    EXEC(@Ddl);
END;
""",
        (login,),
    )


def verify_test_cleanup(connection, database: str, peer_database: str, login: str) -> None:
    validate_test_targets(database, peer_database, login)
    rows = _rows(
        connection,
        "SELECT name FROM sys.databases WHERE name IN (?, ?) UNION ALL SELECT name FROM sys.server_principals WHERE name = ?;",
        (database, peer_database, login),
    )
    if rows:
        raise PrincipalError("Test principal cleanup verification failed")


def admin_connection_database(command: str, database: str) -> str:
    if command in {"record-test-migration", "exercise-test-status"}:
        return database
    return "master"


def _admin_connection(arguments):
    return connect_admin(
        arguments.server,
        Path(arguments.admin_credential_file),
        admin_connection_database(arguments.command, arguments.database),
    )


def dispatch(arguments) -> None:
    command = arguments.command
    if command == "authenticate-login":
        authenticate_login(arguments.server, arguments.database, arguments.login, Path(arguments.credential_file), arguments.credential_kind)
        return
    connection = _admin_connection(arguments)
    try:
        if command == "inspect-production":
            state = inspect_production(connection, arguments.database, arguments.login, arguments.user)
            print(state.lower())
        elif command == "create-production-login":
            create_production_login(connection, arguments.database, arguments.login, Path(arguments.credential_file))
        elif command == "map-production-user":
            map_production_user(connection, arguments.database, arguments.login, arguments.user)
        elif command == "create-test-database":
            create_test_database(connection, arguments.database)
        elif command == "create-test-login":
            create_test_login(connection, arguments.database, arguments.login, Path(arguments.credential_file))
        elif command == "map-test-user":
            map_test_user(connection, arguments.database, arguments.login, arguments.user)
        elif command == "record-test-migration":
            record_test_migration(connection, arguments.database, arguments.migration_file)
        elif command == "exercise-test-status":
            exercise_test_status(
                connection,
                arguments.server,
                arguments.database,
                arguments.login,
                Path(arguments.credential_file),
            )
        elif command == "cleanup-test-targets":
            cleanup_test_targets(connection, arguments.database, arguments.peer_database, arguments.login)
        elif command == "verify-test-cleanup":
            verify_test_cleanup(connection, arguments.database, arguments.peer_database, arguments.login)
        else:
            raise PrincipalError("Unexpected helper command")
    finally:
        connection.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(add_help=False)
    subparsers = result.add_subparsers(dest="command", required=True)
    for command in COMMANDS:
        item = subparsers.add_parser(command, add_help=False)
        item.add_argument("--server", required=True)
        if command != "authenticate-login":
            item.add_argument("--admin-credential-file", required=True)
        if command in {"inspect-production", "map-production-user", "map-test-user"}:
            item.add_argument("--user", required=True)
        if command in {
            "inspect-production", "authenticate-login", "create-production-login",
            "map-production-user", "create-test-database", "create-test-login",
            "map-test-user", "record-test-migration", "exercise-test-status",
            "cleanup-test-targets", "verify-test-cleanup",
        }:
            item.add_argument("--database", required=True)
        if command in {"authenticate-login", "create-production-login", "create-test-login", "exercise-test-status", "map-production-user", "map-test-user", "cleanup-test-targets", "verify-test-cleanup", "inspect-production"}:
            item.add_argument("--login", required=True)
        if command in {"authenticate-login", "create-production-login", "create-test-login", "exercise-test-status"}:
            item.add_argument("--credential-file", required=True)
        if command == "authenticate-login":
            item.add_argument("--credential-kind", choices=("application", "test"), required=True)
        if command in {"cleanup-test-targets", "verify-test-cleanup"}:
            item.add_argument("--peer-database", required=True)
        if command == "record-test-migration":
            item.add_argument("--migration-file", required=True, choices=tuple(MIGRATIONS))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = parser().parse_args(argv)
        dispatch(arguments)
        return 0
    except (PrincipalError, OSError, pyodbc.Error, Exception):
        print("SQL principal operation failed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
