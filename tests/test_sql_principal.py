from __future__ import annotations

import importlib.util
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "infra" / "sql-principal.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("sql_principal", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCursor:
    def __init__(self, rows=(), error: Exception | None = None):
        self.rows = list(rows)
        self.error = error
        self.description = ("result",)
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, statement: str, *parameters: object):
        self.executions.append((statement, parameters))
        if self.error:
            raise self.error
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class DeferredResultCursor(FakeCursor):
    def __init__(self, rows=()):
        super().__init__(rows)
        self.description = None

    def nextset(self):
        self.description = ("result",)
        return True


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self.cursor_instance = cursor
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class FakePyodbc:
    class Error(Exception):
        pass

    def __init__(self, connection: FakeConnection):
        self.connection = connection
        self.calls: list[tuple[str, bool]] = []

    def connect(self, connection_string: str, autocommit: bool):
        self.calls.append((connection_string, autocommit))
        return self.connection


class ProbePyodbc(FakePyodbc):
    """ODBC double with real Driver 18-style database-login failures."""

    def __init__(self, connection: FakeConnection, error: Exception | None = None):
        super().__init__(connection)
        self.error = error

    def connect(self, connection_string: str, autocommit: bool):
        self.calls.append((connection_string, autocommit))
        if self.error is not None:
            raise self.error
        return self.connection


def test_helper_has_only_fixed_lifecycle_commands() -> None:
    """Break caught: a principal helper could become a generic SQL execution tool."""
    helper = load_helper()

    assert set(helper.COMMANDS) == {
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
        "verify-no-test-leftovers",
        "verify-test-targets-preserved",
        "verify-peer-database-denial",
        "run-admin-sqlcmd",
        "verify-test-preference-rollback",
    }


@pytest.mark.parametrize(
    ("database", "login", "user", "accepted"),
    (
        ("EHFApplications", "ehf_app", "ehf_app", True),
        ("EHFApplications_Test_sqlperm_0123456789abcdef01234567", "ehf_app_test_0123456789abcdef01234567", "ehf_app_test_0123456789abcdef01234567", True),
        ("EHFApplications_Test_sqlperm_peer_0123456789abcdef01234567", "ehf_app_test_0123456789abcdef01234567", "ehf_app_test_0123456789abcdef01234567", True),
        ("Finances2", "ehf_app", "ehf_app", False),
        ("EHFApplications_Test_sqlperm_ABC", "ehf_app_test_ABC", "ehf_app_test_ABC", False),
    ),
)
def test_name_validation_fails_closed_on_anything_except_expected_shapes(
    database: str, login: str, user: str, accepted: bool
) -> None:
    """Break caught: helper DDL could target a production or unrelated principal."""
    helper = load_helper()

    if accepted:
        helper.validate_target_names(database, login, user)
    else:
        with pytest.raises(helper.PrincipalError, match="Unexpected principal target"):
            helper.validate_target_names(database, login, user)


def test_create_login_binds_name_password_and_database_not_sql_text(monkeypatch) -> None:
    """Break caught: a password or identifier could be interpolated into client SQL."""
    helper = load_helper()
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    connection.autocommit = False
    safe_password = "Aa1._~" + "a" * 42
    monkeypatch.setattr(helper, "read_credential", lambda *_: safe_password)
    monkeypatch.setattr(helper, "inspect_production", lambda *_: "ABSENT")

    helper.create_production_login(
        connection,
        "EHFApplications",
        "ehf_app",
        Path("/protected/password"),
    )

    statement, parameters = cursor.executions[0]
    assert "CREATE LOGIN" in statement
    assert safe_password not in statement
    assert parameters == ("ehf_app", safe_password, "EHFApplications")
    assert connection.committed
    assert connection.autocommit is True


def test_test_login_creation_applies_the_exact_production_server_deny_set(monkeypatch) -> None:
    """Break caught: a disposable login could reintroduce the login-blocking CONTROL SERVER deny."""
    helper = load_helper()
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    suffix = "0123456789abcdef01234567"
    login = f"ehf_app_test_{suffix}"
    monkeypatch.setattr(helper, "read_credential", lambda *_: "Aa1._~" + "a" * 42)

    helper.create_test_login(
        connection,
        f"EHFApplications_Test_sqlperm_{suffix}",
        login,
        Path("/protected/test-password"),
    )

    statement, _ = cursor.executions[0]
    for permission_name in helper.EXPECTED_SERVER_DENIES:
        assert f"N'{permission_name}'" in statement
    assert "N'CONTROL SERVER'" not in statement
    assert "N'DENY '+@Permission+N' TO '" in statement


def test_test_login_shape_accepts_only_the_exact_server_permission_allowlist() -> None:
    """Break caught: cleanup could accept a temporary login missing a deny, CONTROL SERVER, or another extra permission."""
    helper = load_helper()
    suffix = "0123456789abcdef01234567"
    database = f"EHFApplications_Test_sqlperm_{suffix}"
    login = f"ehf_app_test_{suffix}"
    exact = FakeConnection(FakeCursor(rows=[(1,)]))
    unsafe = FakeConnection(FakeCursor(rows=[(0,)]))

    assert helper._test_login_shape(exact, database, login)
    assert not helper._test_login_shape(unsafe, database, login)
    statement, _ = exact.cursor_instance.executions[0]
    for permission_name in helper.EXPECTED_SERVER_DENIES:
        assert f"N'{permission_name}'" in statement
    assert "INNER JOIN sys.sql_logins AS login_row" in statement
    assert "login_row.is_policy_checked=1" in statement
    assert "login_row.is_expiration_checked=0" in statement
    assert "N'CONTROL SERVER'" not in statement
    assert "permission_name=N'CONNECT SQL' AND state_desc=N'GRANT'" in statement
    assert "state_desc=N'DENY'" in statement


def test_odbc_connection_uses_the_fixed_server_and_keeps_credential_out_of_output(
    monkeypatch,
) -> None:
    """Break caught: helper connection construction could accept another server or log a secret."""
    helper = load_helper()
    fake_driver = FakePyodbc(FakeConnection(FakeCursor()))
    monkeypatch.setattr(helper, "pyodbc", fake_driver)

    connection = helper._connect(
        "tcp:127.0.0.1,1433", "EHFApplications", "ehf_app", "Aa1._~" + "a" * 42
    )

    assert connection is fake_driver.connection
    connection_string, autocommit = fake_driver.calls[0]
    assert "SERVER={tcp:127.0.0.1,1433}" in connection_string
    assert "DATABASE={EHFApplications}" in connection_string
    assert autocommit is False
    with pytest.raises(helper.PrincipalError, match="Unexpected SQL Server target"):
        helper._connect("tcp:10.0.0.2,1433", "EHFApplications", "ehf_app", "Aa1._~" + "a" * 42)


def test_inspection_refuses_cross_database_mapping_or_ownership() -> None:
    """Break caught: an EHF login could silently retain access outside EHFApplications."""
    helper = load_helper()

    with pytest.raises(helper.PrincipalError, match="cross-database"):
        helper.require_no_cross_database_access(
            [("OtherDatabase", "DATABASE_USER")], "EHFApplications"
        )

    helper.require_no_cross_database_access([], "EHFApplications")


def test_production_and_cleanup_login_shape_queries_use_sql_logins_for_policy() -> None:
    """Break caught: querying policy columns on server_principals fails on SQL Server."""
    helper = load_helper()
    production = FakeConnection(FakeCursor(rows=[("ABSENT",)]))
    cleanup = FakeConnection(FakeCursor(rows=[(1,)]))

    assert helper._inspect_production_state(production, "EHFApplications", "ehf_app", "ehf_app") == "ABSENT"
    assert helper._test_login_shape(
        cleanup,
        "EHFApplications_Test_sqlperm_0123456789abcdef01234567",
        "ehf_app_test_0123456789abcdef01234567",
    )

    production_statement, _ = production.cursor_instance.executions[0]
    cleanup_statement, _ = cleanup.cursor_instance.executions[0]
    for statement in (production_statement, cleanup_statement):
        assert "INNER JOIN sys.sql_logins AS login_row" in statement
        assert "login_row.is_policy_checked=1" in statement
        assert "login_row.is_expiration_checked=0" in statement
        assert "sys.server_principals WHERE name=@LoginName AND type_desc=N''SQL_LOGIN'' AND is_disabled=0 AND default_database_name=@DatabaseName AND is_policy_checked=1" not in statement


def test_production_inspection_checks_its_own_database_owner_and_login_policy() -> None:
    """Break caught: ehf_app could own EHFApplications or weaken its password policy."""
    source = HELPER.read_text(encoding="utf-8")
    assert "owner_sid" in source
    assert "sys.sql_logins" in source


def test_cross_database_probe_accepts_only_sql_servers_cannot_open_database_login_denial(
    monkeypatch,
) -> None:
    """Break caught: a TLS or authentication failure could be accepted as database isolation."""
    helper = load_helper()
    cannot_open = FakePyodbc.Error(
        "42000",
        "[Microsoft][ODBC Driver 18 for SQL Server][SQL Server]Cannot open database 'Finances2' requested by the login. The login failed. (4060)",
    )
    driver = ProbePyodbc(FakeConnection(FakeCursor()), cannot_open)
    monkeypatch.setattr(helper, "pyodbc", driver)
    monkeypatch.setattr(helper, "read_credential", lambda *_: "Aa1._~" + "a" * 42)
    monkeypatch.setattr(helper, "_rows", lambda *_: [("Finances2",)])

    helper.require_no_effective_cross_database_access(
        FakeConnection(FakeCursor()), helper.SERVER, "EHFApplications", "ehf_app", Path("/protected/password")
    )

    assert "DATABASE={Finances2}" in driver.calls[0][0]


@pytest.mark.parametrize("sqlstate", ("08001", "HYT00", "28000"))
def test_cross_database_probe_rejects_fabricated_4060_text_under_other_sqlstates(
    monkeypatch, sqlstate: str
) -> None:
    """Break caught: TLS, timeout, or authentication errors could carry fabricated 4060 text."""
    helper = load_helper()
    driver = ProbePyodbc(
        FakeConnection(FakeCursor()),
        FakePyodbc.Error(
            sqlstate,
            "[42000] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]"
            "Cannot open database 'Finances2' requested by the login. "
            "The login failed. (4060) (SQLDriverConnect)",
        ),
    )
    monkeypatch.setattr(helper, "pyodbc", driver)
    monkeypatch.setattr(helper, "read_credential", lambda *_: "Aa1._~" + "a" * 42)
    monkeypatch.setattr(helper, "_rows", lambda *_: [("Finances2",)])

    with pytest.raises(helper.PrincipalError, match="effective cross-database"):
        helper.require_no_effective_cross_database_access(
            FakeConnection(FakeCursor()), helper.SERVER, "EHFApplications", "ehf_app", Path("/protected/password")
        )


def test_cross_database_probe_rejects_4060_for_the_wrong_database(monkeypatch) -> None:
    """Break caught: a denial for another database could be accepted for the enumerated target."""
    helper = load_helper()
    driver = ProbePyodbc(
        FakeConnection(FakeCursor()),
        FakePyodbc.Error(
            "42000",
            "[42000] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]"
            "Cannot open database 'WrongDatabase' requested by the login. "
            "The login failed. (4060) (SQLDriverConnect)",
        ),
    )
    monkeypatch.setattr(helper, "pyodbc", driver)
    monkeypatch.setattr(helper, "read_credential", lambda *_: "Aa1._~" + "a" * 42)
    monkeypatch.setattr(helper, "_rows", lambda *_: [("Finances2",)])

    with pytest.raises(helper.PrincipalError, match="effective cross-database"):
        helper.require_no_effective_cross_database_access(
            FakeConnection(FakeCursor()), helper.SERVER, "EHFApplications", "ehf_app", Path("/protected/password")
        )


@pytest.mark.parametrize(
    "diagnostic",
    (
        (),
        ("42000",),
        (42000, "Cannot open database 'Finances2' requested by the login. The login failed. (4060)"),
        ("42000", 4060),
        ("42000", "Cannot open database 'Finances2' requested by the login. The login failed."),
        ("42000", "Cannot open database Finances2 requested by the login. The login failed. (4060)"),
    ),
)
def test_4060_classifier_rejects_malformed_driver_diagnostics(diagnostic) -> None:
    """Break caught: partial or structurally invalid pyodbc args could be accepted as authentic."""
    helper = load_helper()

    assert not helper._expected_cannot_open_database_for_login(
        FakePyodbc.Error(*diagnostic), "Finances2"
    )


@pytest.mark.parametrize("expected_database", (None, 4060, "", "a" * 129, "bad\x00name"))
def test_4060_classifier_rejects_malformed_expected_database(expected_database) -> None:
    """Break caught: malformed database targets must fail closed rather than raise."""
    helper = load_helper()
    error = FakePyodbc.Error(
        "42000",
        "[42000] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]"
        "Cannot open database 'Finances2' requested by the login. "
        "The login failed. (4060) (SQLDriverConnect)",
    )

    assert not helper._expected_cannot_open_database_for_login(error, expected_database)


def test_peer_database_denial_accepts_only_native_4060_for_the_exact_test_pair(monkeypatch) -> None:
    """Break caught: the isolated peer check could accept a generic connection failure as isolation."""
    helper = load_helper()
    suffix = "0123456789abcdef01234567"
    cannot_open = FakePyodbc.Error(
        "42000",
        "[Microsoft][ODBC Driver 18 for SQL Server][SQL Server]Cannot open database "
        f"'EHFApplications_Test_sqlperm_peer_{suffix}' requested by the login. "
        "The login failed. (4060) (SQLDriverConnect)",
    )
    driver = ProbePyodbc(FakeConnection(FakeCursor()), cannot_open)
    monkeypatch.setattr(helper, "pyodbc", driver)
    monkeypatch.setattr(helper, "read_credential", lambda *_: "Aa1._~" + "a" * 42)

    helper.verify_peer_database_denial(
        helper.SERVER,
        f"EHFApplications_Test_sqlperm_peer_{suffix}",
        f"ehf_app_test_{suffix}",
        Path("/protected/test-password"),
    )

    assert "DATABASE={EHFApplications_Test_sqlperm_peer_0123456789abcdef01234567}" in driver.calls[0][0]


@pytest.mark.parametrize(
    "driver_error",
    (
        FakePyodbc.Error("28000", "Login failed for user. (18456)"),
        FakePyodbc.Error("08001", "TLS negotiation failed"),
        FakePyodbc.Error("HYT00", "Login timeout expired"),
        FakePyodbc.Error("IM002", "Data source name not found and no default driver specified"),
        FakePyodbc.Error("42000", "Incorrect syntax near SELECT"),
        FakePyodbc.Error("42000", "Cannot open database requested by the login without native code"),
    ),
)
def test_peer_database_denial_fails_closed_for_every_non_4060_odbc_error(monkeypatch, driver_error) -> None:
    """Break caught: authentication, TLS, timeout, driver, or query errors could false-pass the peer check."""
    helper = load_helper()
    suffix = "0123456789abcdef01234567"
    driver = ProbePyodbc(FakeConnection(FakeCursor()), driver_error)
    monkeypatch.setattr(helper, "pyodbc", driver)
    monkeypatch.setattr(helper, "read_credential", lambda *_: "Aa1._~" + "a" * 42)

    with pytest.raises(helper.PrincipalError, match="peer database denial"):
        helper.verify_peer_database_denial(
            helper.SERVER,
            f"EHFApplications_Test_sqlperm_peer_{suffix}",
            f"ehf_app_test_{suffix}",
            Path("/protected/test-password"),
        )


def test_peer_database_denial_rejects_authentic_4060_for_the_wrong_peer(monkeypatch) -> None:
    """Break caught: the peer helper could accept a 4060 diagnostic naming another database."""
    helper = load_helper()
    suffix = "0123456789abcdef01234567"
    driver = ProbePyodbc(
        FakeConnection(FakeCursor()),
        FakePyodbc.Error(
            "42000",
            "[42000] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]"
            "Cannot open database 'EHFApplications_Test_sqlperm_peer_ffffffffffffffffffffffff' "
            "requested by the login. The login failed. (4060) (SQLDriverConnect)",
        ),
    )
    monkeypatch.setattr(helper, "pyodbc", driver)
    monkeypatch.setattr(helper, "read_credential", lambda *_: "Aa1._~" + "a" * 42)

    with pytest.raises(helper.PrincipalError, match="peer database denial"):
        helper.verify_peer_database_denial(
            helper.SERVER,
            f"EHFApplications_Test_sqlperm_peer_{suffix}",
            f"ehf_app_test_{suffix}",
            Path("/protected/test-password"),
        )


def test_peer_database_denial_rejects_success_and_invalid_targets_before_secret_read(monkeypatch) -> None:
    """Break caught: a successful or caller-directed peer connection could be treated as denied."""
    helper = load_helper()
    suffix = "0123456789abcdef01234567"
    connection = FakeConnection(FakeCursor())
    driver = ProbePyodbc(connection)
    monkeypatch.setattr(helper, "pyodbc", driver)
    monkeypatch.setattr(helper, "read_credential", lambda *_: "Aa1._~" + "a" * 42)

    with pytest.raises(helper.PrincipalError, match="effective peer database access"):
        helper.verify_peer_database_denial(
            helper.SERVER,
            f"EHFApplications_Test_sqlperm_peer_{suffix}",
            f"ehf_app_test_{suffix}",
            Path("/protected/test-password"),
        )
    assert connection.closed

    monkeypatch.setattr(helper, "read_credential", lambda *_: pytest.fail("credential read was reached"))
    with pytest.raises(helper.PrincipalError, match="Unexpected principal target"):
        helper.verify_peer_database_denial(
            helper.SERVER,
            "Finances2",
            f"ehf_app_test_{suffix}",
            Path("/protected/test-password"),
        )


@pytest.mark.parametrize(
    ("operation", "state"),
    (("create_production_login", "READY"), ("map_production_user", "INVALID")),
)
def test_production_lifecycle_refuses_unsafe_state_before_any_mutation(monkeypatch, operation: str, state: str) -> None:
    """Break caught: setup could change a principal before discovering its unsafe shape."""
    helper = load_helper()
    connection = FakeConnection(FakeCursor())
    monkeypatch.setattr(helper, "inspect_production", lambda *_: state)
    monkeypatch.setattr(helper, "_execute", lambda *_: pytest.fail("principal mutation was reached"))
    monkeypatch.setattr(helper, "read_credential", lambda *_: "Aa1._~" + "a" * 42)

    with pytest.raises(helper.PrincipalError, match="unexpected shape"):
        if operation == "create_production_login":
            helper.create_production_login(connection, "EHFApplications", "ehf_app", Path("/protected/password"))
        else:
            helper.map_production_user(connection, "EHFApplications", "ehf_app", "ehf_app", Path("/protected/password"))


def test_production_mapping_proves_effective_database_isolation_before_mutation(monkeypatch) -> None:
    """Break caught: an unmapped login with access through another database could be mapped before that access was rejected."""
    helper = load_helper()
    connection = FakeConnection(FakeCursor())
    monkeypatch.setattr(helper, "inspect_production", lambda *_: "UNMAPPED")
    monkeypatch.setattr(
        helper,
        "require_no_effective_cross_database_access",
        lambda *_: (_ for _ in ()).throw(helper.PrincipalError("Expected effective cross-database access")),
    )
    monkeypatch.setattr(helper, "_map_user", lambda *_: pytest.fail("principal mutation was reached"))

    with pytest.raises(helper.PrincipalError, match="effective cross-database"):
        helper.map_production_user(
            connection,
            "EHFApplications",
            "ehf_app",
            "ehf_app",
            Path("/protected/password"),
        )


def test_production_mapping_revalidates_exact_user_shape_before_atomic_recreation(monkeypatch) -> None:
    """Break caught: an ownership, permission, authentication, or role race could reach recreation."""
    helper = load_helper()
    connection = FakeConnection(FakeCursor())
    monkeypatch.setattr(helper, "inspect_production", lambda *_: "UNMAPPED")
    monkeypatch.setattr(helper, "require_no_effective_cross_database_access", lambda *_: None)

    helper.map_production_user(
        connection,
        "EHFApplications",
        "ehf_app",
        "ehf_app",
        Path("/protected/password"),
    )

    assert len(connection.cursor_instance.executions) == 1
    statement, parameters = connection.cursor_instance.executions[0]
    transition_index = statement.index("ALTER ROLE [EHFApplicationRuntime] DROP MEMBER")
    for precondition in (
        "@Auth<>N''NONE''",
        "sys.schemas WHERE principal_id=@UserId",
        "sys.objects WHERE principal_id=@UserId",
        "sys.database_principals WHERE owning_principal_id=@UserId",
        "sys.database_permissions WHERE grantee_principal_id=@UserId",
        "SELECT COUNT(*) FROM sys.database_role_members WHERE member_principal_id=@UserId",
        "role_principal_id=DATABASE_PRINCIPAL_ID(N''EHFApplicationRuntime'')",
    ):
        assert precondition in statement
        assert statement.index(precondition) < transition_index
    assert parameters == ("EHFApplications", "ehf_app", "ehf_app")


def test_production_mapping_atomically_recreates_without_login_user_after_sql_33016(monkeypatch) -> None:
    """Break caught: ALTER USER cannot map a SQL_USER created WITHOUT LOGIN (SQL error 33016)."""
    helper = load_helper()
    connection = FakeConnection(FakeCursor())
    monkeypatch.setattr(helper, "inspect_production", lambda *_: "UNMAPPED")
    monkeypatch.setattr(helper, "require_no_effective_cross_database_access", lambda *_: None)

    helper.map_production_user(
        connection,
        "EHFApplications",
        "ehf_app",
        "ehf_app",
        Path("/protected/password"),
    )

    statement, _ = connection.cursor_instance.executions[0]
    transition_fragments = (
        "ALTER ROLE [EHFApplicationRuntime] DROP MEMBER ''+QUOTENAME(@UserName)",
        "DROP USER ''+QUOTENAME(@UserName)",
        "CREATE USER ''+QUOTENAME(@UserName)+N'' FOR LOGIN ''+QUOTENAME(@LoginName)",
        "ALTER ROLE [EHFApplicationRuntime] ADD MEMBER ''+QUOTENAME(@UserName)",
    )
    transition_indices = tuple(statement.index(fragment) for fragment in transition_fragments)
    transition_start = transition_indices[0]
    transition_execute = statement.index("EXEC(@Transition);")
    postcheck_start = statement.index("SET @UserId=NULL")
    assert "SET XACT_ABORT ON" in statement
    assert statement.index("BEGIN TRANSACTION") < transition_start
    assert statement.index("BEGIN TRY") < transition_start
    assert transition_indices == tuple(sorted(transition_indices))
    assert transition_indices[-1] < transition_execute < postcheck_start
    assert transition_indices[-1] < statement.rindex(
        "SELECT @UserId=principal_id,@ExistingSid=sid,@Auth=authentication_type_desc"
    )
    assert statement.count("authentication_type_desc") >= 2
    assert statement.count("sys.database_permissions WHERE grantee_principal_id=@UserId") >= 2
    assert statement.index("COMMIT TRANSACTION") > postcheck_start
    assert "BEGIN CATCH" in statement
    assert "IF XACT_STATE()<>0 ROLLBACK TRANSACTION" in statement
    assert "ALTER USER" not in statement
    assert statement.count("DROP USER") == 1
    assert statement.count("CREATE USER") == 1
    assert statement.count("ALTER ROLE [EHFApplicationRuntime]") == 2
    assert "REVOKE CONNECT" not in statement
    assert re.search(r"\bGRANT\s+[A-Z]", statement, re.IGNORECASE) is None


def test_production_mapping_revalidates_complete_topology_before_and_after_recreation(monkeypatch) -> None:
    """Break caught: server-login or runtime-role drift could escape the mapping transaction."""
    helper = load_helper()
    connection = FakeConnection(FakeCursor())
    monkeypatch.setattr(helper, "inspect_production", lambda *_: "UNMAPPED")
    monkeypatch.setattr(helper, "require_no_effective_cross_database_access", lambda *_: None)

    helper.map_production_user(
        connection,
        "EHFApplications",
        "ehf_app",
        "ehf_app",
        Path("/protected/password"),
    )

    statement, _ = connection.cursor_instance.executions[0]
    transition_index = statement.index("ALTER ROLE [EHFApplicationRuntime] DROP MEMBER")
    commit_index = statement.index("COMMIT TRANSACTION")
    for topology_check in (
        "INNER JOIN sys.sql_logins AS login_row",
        "principal_row.is_disabled=0",
        "principal_row.default_database_name=@DatabaseName",
        "login_row.is_policy_checked=1",
        "login_row.is_expiration_checked=0",
        "sys.server_permissions AS permission_row",
        "permission_row.permission_name=N''CONNECT SQL'' AND permission_row.state_desc=N''GRANT''",
        "permission_row.state_desc=N''DENY'' AND permission_row.permission_name IN",
        "SELECT COUNT(*) FROM sys.server_permissions",
        "sys.server_role_members AS membership",
        "sys.databases WHERE owner_sid=SUSER_SID(@LoginName)",
        "role_row.owning_principal_id=DATABASE_PRINCIPAL_ID(N''dbo'')",
        "SELECT COUNT(*) FROM sys.database_role_members WHERE role_principal_id=@RuntimeRoleId",
        "member_principal_id=@RuntimeRoleId",
        "sys.schemas WHERE principal_id=@RuntimeRoleId",
        "sys.objects WHERE principal_id=@RuntimeRoleId",
        "sys.database_principals WHERE owning_principal_id=@RuntimeRoleId",
    ):
        assert statement.count(topology_check) >= 2, topology_check
        assert statement.index(topology_check) < transition_index, topology_check
        assert transition_index < statement.rindex(topology_check) < commit_index, topology_check
    for denied_permission in helper.EXPECTED_SERVER_DENIES:
        assert statement.count(f"N''{denied_permission}''") >= 4
    assert statement.count(")<>5") >= 2


def test_production_mapping_binds_database_name_inside_dynamic_sql(monkeypatch) -> None:
    """Break caught: the production batch could reference an undeclared dynamic @DatabaseName."""
    helper = load_helper()

    class DynamicBindingCursor(FakeCursor):
        def execute(self, statement: str, *parameters: object):
            binding = re.search(
                r"EXEC\s+sys\.sp_executesql\s+@Sql\s*,\s*N'(?P<declarations>[^']+)'\s*,(?P<arguments>[^;]+);",
                statement,
            )
            assert binding is not None
            declarations = tuple(
                declaration.strip() for declaration in binding.group("declarations").split(",")
            )
            arguments = tuple(
                argument.strip() for argument in binding.group("arguments").split(",")
            )
            assert declarations == (
                "@DatabaseName sysname",
                "@LoginName sysname",
                "@UserName sysname",
            )
            assert arguments == ("@DatabaseName", "@LoginName", "@UserName")
            return super().execute(statement, *parameters)

    connection = FakeConnection(DynamicBindingCursor())
    monkeypatch.setattr(helper, "inspect_production", lambda *_: "UNMAPPED")
    monkeypatch.setattr(helper, "require_no_effective_cross_database_access", lambda *_: None)

    helper.map_production_user(
        connection,
        "EHFApplications",
        "ehf_app",
        "ehf_app",
        Path("/protected/password"),
    )

    assert connection.cursor_instance.executions[0][1] == (
        "EHFApplications",
        "ehf_app",
        "ehf_app",
    )


def test_helper_executes_only_fixed_admin_sqlcmd_artifacts_without_exposing_secret(monkeypatch) -> None:
    """Break caught: the verifier could reopen the admin secret or invoke arbitrary SQLCMD input."""
    helper = load_helper()
    invoked: list[tuple[list[str], dict[str, str]]] = []

    class Completed:
        returncode = 0

    monkeypatch.setattr(helper, "read_credential", lambda *_: "Aa1._~" + "a" * 42)
    monkeypatch.setattr(
        helper.subprocess,
        "run",
        lambda arguments, **kwargs: invoked.append((arguments, kwargs["env"])) or Completed(),
    )

    helper.run_admin_sqlcmd(
        helper.SERVER,
        "EHFApplications_Test_sqlperm_0123456789abcdef01234567",
        Path("/protected/admin-password"),
        "005_validate_application_permissions.sql",
    )

    arguments, environment = invoked[0]
    assert arguments[-1].endswith("005_validate_application_permissions.sql")
    assert "Aa1._~" not in " ".join(arguments)
    assert environment["SQLCMDPASSWORD"] == "Aa1._~" + "a" * 42
    with pytest.raises(helper.PrincipalError, match="Unexpected SQLCMD input"):
        helper.run_admin_sqlcmd(
            helper.SERVER,
            "EHFApplications_Test_sqlperm_0123456789abcdef01234567",
            Path("/protected/admin-password"),
            "../../Finances2.sql",
        )


def test_cleanup_only_accepts_exact_randomized_test_targets() -> None:
    """Break caught: cleanup could delete a non-test database or login."""
    helper = load_helper()
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    suffix = "0123456789abcdef01234567"

    helper.cleanup_test_targets(
        connection,
        f"EHFApplications_Test_sqlperm_{suffix}",
        f"EHFApplications_Test_sqlperm_peer_{suffix}",
        f"ehf_app_test_{suffix}",
        "0123456789abcdef0123456789abcdef",
    )

    assert all("0123456789abcdef01234567" not in sql for sql, _ in cursor.executions)
    assert all(parameters for _, parameters in cursor.executions)
    with pytest.raises(helper.PrincipalError, match="Unexpected principal target"):
        helper.cleanup_test_targets(
            connection,
            "EHFApplications",
            "Finances2",
            "ehf_app",
            "0123456789abcdef0123456789abcdef",
        )


def test_database_lifecycle_uses_autocommit_for_sql_server_database_ddl() -> None:
    """Break caught: CREATE/DROP DATABASE would fail inside an ODBC transaction."""
    helper = load_helper()
    connection = FakeConnection(FakeCursor())
    connection.autocommit = False

    helper.create_test_database(
        connection,
        "EHFApplications_Test_sqlperm_0123456789abcdef01234567",
        "0123456789abcdef0123456789abcdef",
    )

    assert connection.autocommit is True


def test_user_mapping_uses_autocommit_for_database_ddl() -> None:
    """Break caught: CREATE USER or ALTER ROLE could fail in an implicit ODBC transaction."""
    helper = load_helper()
    connection = FakeConnection(FakeCursor())
    connection.autocommit = False
    suffix = "0123456789abcdef01234567"

    helper.map_test_user(
            connection,
            f"EHFApplications_Test_sqlperm_{suffix}",
            f"ehf_app_test_{suffix}",
            f"ehf_app_test_{suffix}",
    )

    assert connection.autocommit is True
    statement, _ = connection.cursor_instance.executions[0]
    assert "Expected database user has direct permissions" in statement


def test_dynamic_identifier_ddl_is_assigned_before_server_side_execution() -> None:
    """Break caught: SQL Server rejects concatenated expressions directly in EXEC."""
    source = HELPER.read_text(encoding="utf-8")

    assert "EXEC(N'CREATE DATABASE" not in source
    assert "EXEC(N'CREATE LOGIN" not in source
    assert "EXEC(@Ddl);" in source


def test_target_database_operations_do_not_open_master(monkeypatch) -> None:
    """Break caught: migration recording or status fixtures would run against master."""
    helper = load_helper()
    captured: list[str] = []
    connection = FakeConnection(FakeCursor())
    monkeypatch.setattr(
        helper,
        "connect_admin",
        lambda _server, _credential, database="master": captured.append(database) or connection,
    )

    helper.admin_connection_database(
        "record-test-migration", "EHFApplications_Test_sqlperm_0123456789abcdef01234567"
    )
    helper.admin_connection_database(
        "exercise-test-status", "EHFApplications_Test_sqlperm_0123456789abcdef01234567"
    )

    assert captured == []
    assert helper.admin_connection_database("record-test-migration", "target") == "target"
    assert helper.admin_connection_database("create-test-database", "target") == "master"


def test_status_probe_uses_the_real_test_login_and_parameter_binding(monkeypatch) -> None:
    """Break caught: SetApplicationStatus could be checked only by an administrator."""
    helper = load_helper()
    cursor = FakeCursor(rows=[("01234567-89ab-cdef-0123-456789abcdef", b"12345678")])
    admin_connection = FakeConnection(cursor)
    runtime_connection = FakeConnection(FakeCursor())
    monkeypatch.setattr(helper, "read_credential", lambda *_: "Aa1._~" + "a" * 42)
    monkeypatch.setattr(helper, "_connect", lambda *_: runtime_connection)
    suffix = "0123456789abcdef01234567"

    helper.exercise_test_status(
        admin_connection,
            "tcp:127.0.0.1,1433",
            f"EHFApplications_Test_sqlperm_{suffix}",
            f"ehf_app_test_{suffix}",
            Path("/protected/test-password"),
        )

    runtime_sql, runtime_parameters = runtime_connection.cursor_instance.executions[0]
    assert "SetApplicationStatus" in runtime_sql
    assert "01234567-89ab-cdef-0123-456789abcdef" not in runtime_sql
    assert runtime_parameters[1] == "IN_REVIEW"


def test_fixture_reader_advances_past_non_result_sets() -> None:
    """Break caught: fixture DML can precede the SELECT result set in ODBC."""
    helper = load_helper()
    cursor = DeferredResultCursor(rows=[("fixture", b"rowversion")])

    assert helper.first_result_row(cursor) == ("fixture", b"rowversion")


def test_cli_redacts_driver_errors(monkeypatch, capsys) -> None:
    """Break caught: database-driver details could reveal secrets in automation logs."""
    helper = load_helper()
    monkeypatch.setattr(helper, "dispatch", lambda *_: (_ for _ in ()).throw(Exception("PWD=do-not-print")))

    assert helper.main(
        [
            "inspect-production",
            "--server",
            "tcp:127.0.0.1,1433",
            "--admin-credential-file",
            "/protected/admin",
            "--database",
            "EHFApplications",
            "--login",
            "ehf_app",
            "--user",
            "ehf_app",
        ]
    ) == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == "SQL_PRINCIPAL_ERROR: OPERATION_FAILED"
    assert "do-not-print" not in captured.err


def test_production_server_deny_set_is_exact_and_excludes_the_login_blocking_deny() -> None:
    """Break caught: CONTROL SERVER DENY would make SQL Server reject the runtime login with error 18456."""
    helper = load_helper()

    assert helper.EXPECTED_SERVER_DENIES == frozenset(
        {
            "ALTER ANY LOGIN",
            "ALTER ANY SERVER ROLE",
            "VIEW ANY DATABASE",
            "VIEW ANY DEFINITION",
            "VIEW SERVER STATE",
        }
    )
    assert "CONTROL SERVER" not in helper.EXPECTED_SERVER_DENIES


def test_odbc_components_are_braced_before_connecting(monkeypatch) -> None:
    """Break caught: a separator in an ODBC component could alter connection semantics."""
    helper = load_helper()
    fake_driver = FakePyodbc(FakeConnection(FakeCursor()))
    monkeypatch.setattr(helper, "pyodbc", fake_driver)

    helper._connect(
        helper.SERVER,
        "EHFApplications",
        "ehf_app",
        "Aa1._~" + "a" * 40 + ";}",
    )

    connection_string, _ = fake_driver.calls[0]
    assert "PWD={Aa1._~" in connection_string
    assert ";}}}" in connection_string
    assert "PWD=Aa1" not in connection_string


def test_test_cleanup_requires_token_and_current_run_credential() -> None:
    """Break caught: a peer matching a test name could be dropped without ownership proof."""
    helper = load_helper()
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    suffix = "0123456789abcdef01234567"

    with pytest.raises(helper.PrincipalError, match="run token"):
        helper.validate_run_token("not-a-token")

    helper.cleanup_test_targets(
        connection,
        f"EHFApplications_Test_sqlperm_{suffix}",
        f"EHFApplications_Test_sqlperm_peer_{suffix}",
        f"ehf_app_test_{suffix}",
        "0123456789abcdef0123456789abcdef",
    )
    statements = "\n".join(statement for statement, _ in cursor.executions)
    assert "DROP DATABASE" not in statements
    assert "DROP LOGIN" not in statements


def test_helper_has_no_path_read_text_credential_race_and_validates_before_connect(monkeypatch) -> None:
    """Break caught: a credential swap or malformed target could reach the ODBC driver."""
    helper = load_helper()
    source = HELPER.read_text(encoding="utf-8")
    fake_driver = FakePyodbc(FakeConnection(FakeCursor()))
    monkeypatch.setattr(helper, "pyodbc", fake_driver)

    assert "path.read_text" not in source
    assert "O_NOFOLLOW" in source
    with pytest.raises(helper.PrincipalError, match="Unexpected principal target"):
        helper.validate_command_arguments(
            "create-test-login",
            "tcp:127.0.0.1,1433",
            "Finances2",
            "ehf_app",
            None,
        )
    assert fake_driver.calls == []


def test_cleanup_uses_bound_markers_before_dropping_the_login() -> None:
    """Break caught: interrupted cleanup could delete a peer without its bound evidence."""
    source = HELPER.read_text(encoding="utf-8")
    cleanup = source[source.index("def cleanup_test_targets") : source.index("def verify_test_cleanup")]

    assert "marker_fallback" in cleanup
    assert "_database_marker(connection, database) == run_token" in cleanup


def test_test_login_cleanup_allows_only_the_implicit_connect_sql_grant() -> None:
    """Break caught: cleanup could preserve every normal SQL login as over-privileged."""
    source = HELPER.read_text(encoding="utf-8")

    assert "permission_name=N'CONNECT SQL' AND state_desc=N'GRANT'" in source


def test_test_user_mapping_revokes_sql_servers_implicit_connect_grant() -> None:
    """Break caught: a newly created temporary user could fail the exact direct-grant check."""
    source = HELPER.read_text(encoding="utf-8")

    assert "REVOKE CONNECT FROM ''+QUOTENAME(@UserName)" in source


def test_run_marker_is_bound_to_its_randomized_name_suffix() -> None:
    """Break caught: a lost credential could make cleanup trust an unrelated marker."""
    helper = load_helper()
    suffix = "0123456789abcdef01234567"

    helper.validate_run_token(suffix + "89abcdef", suffix)
    with pytest.raises(helper.PrincipalError):
        helper.validate_run_token("f" * 32, suffix)


def test_adverse_preservation_does_not_require_database_authentication() -> None:
    """Break caught: an intentionally unmapped adverse login cannot enter its database."""
    source = HELPER.read_text(encoding="utf-8")
    section = source[source.index("def verify_test_targets_preserved") : source.index("def admin_connection_database")]
    assert "authenticate_login(" not in section


def test_cleanup_does_not_accept_a_credential_argument() -> None:
    """Break caught: cleanup must converge deterministically after credential loss."""
    helper = load_helper()
    assert "credential_file" not in helper.cleanup_test_targets.__annotations__


def test_global_cleanup_verifier_rejects_any_matching_resource() -> None:
    """Break caught: named cleanup could pass while another test target remains."""
    helper = load_helper()

    helper.verify_no_test_leftovers(FakeConnection(FakeCursor()))
    with pytest.raises(helper.PrincipalError, match="cleanup verification"):
        helper.verify_no_test_leftovers(
            FakeConnection(FakeCursor(rows=[("EHFApplications_Test_sqlperm_leftover",)]))
        )


def test_global_cleanup_command_has_no_target_arguments() -> None:
    """Break caught: global verification could accidentally accept a narrowed target."""
    helper = load_helper()
    arguments = helper.parser().parse_args(
        [
            "verify-no-test-leftovers",
            "--server",
            "tcp:127.0.0.1,1433",
            "--admin-credential-file",
            "/protected/admin-password",
        ]
    )

    assert arguments.command == "verify-no-test-leftovers"
    assert not hasattr(arguments, "database")
