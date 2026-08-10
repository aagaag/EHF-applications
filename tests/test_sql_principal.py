from __future__ import annotations

import importlib.util
from pathlib import Path

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
    assert "SERVER=tcp:127.0.0.1,1433" in connection_string
    assert "DATABASE=EHFApplications" in connection_string
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
    )

    assert all("0123456789abcdef01234567" not in sql for sql, _ in cursor.executions)
    assert all(parameters for _, parameters in cursor.executions)
    with pytest.raises(helper.PrincipalError, match="Unexpected principal target"):
        helper.cleanup_test_targets(connection, "EHFApplications", "Finances2", "ehf_app")


def test_database_lifecycle_uses_autocommit_for_sql_server_database_ddl() -> None:
    """Break caught: CREATE/DROP DATABASE would fail inside an ODBC transaction."""
    helper = load_helper()
    connection = FakeConnection(FakeCursor())
    connection.autocommit = False

    helper.create_test_database(
        connection, "EHFApplications_Test_sqlperm_0123456789abcdef01234567"
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
    assert "Test user lacks its runtime role" in statement


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
    assert captured.err.strip() == "SQL principal operation failed."
    assert "do-not-print" not in captured.err
