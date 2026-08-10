"""Contracts for the exact-name EHF production database bootstrap."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "infra" / "bootstrap-ehf-database.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("ehf_database_bootstrap", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Cursor:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str):
        self.statements.append(statement)
        return self


class Connection:
    def __init__(self) -> None:
        self.cursor_instance = Cursor()
        self.committed = False
        self.closed = False

    def cursor(self) -> Cursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def test_bootstrap_refuses_every_database_name_except_exact_ehfapplications() -> None:
    """Break caught: a production credential could create or migrate another database."""
    helper = load_helper()

    assert helper.validate_database_name("EHFApplications") == "EHFApplications"
    for name in ("master", "Finances2", "EHFApplications_Test", "ehfapplications"):
        with pytest.raises(helper.BootstrapError, match="database"):
            helper.validate_database_name(name)


def test_bootstrap_creates_only_the_exact_database_then_uses_checksum_migrations(monkeypatch) -> None:
    """Break caught: deployment could run an arbitrary SQL batch or skip checksum migration verification."""
    helper = load_helper()
    master = Connection()
    application = Connection()
    connected_to: list[str] = []

    def connect(database: str, _credential: Path) -> Connection:
        connected_to.append(database)
        return master if database == "master" else application

    migrations: list[str] = []
    validators: list[str] = []
    monkeypatch.setattr(helper, "connect_admin", connect)
    monkeypatch.setattr(helper, "apply_checksum_migrations", lambda connection: migrations.append("applied") or 9)
    monkeypatch.setattr(helper, "run_validators", lambda connection: validators.append("validated"))

    result = helper.bootstrap(Path("/protected/sql-admin-password"))

    assert result == 9
    assert connected_to == ["master", "EHFApplications"]
    assert master.cursor_instance.statements == [
        "IF DB_ID(N'EHFApplications') IS NULL CREATE DATABASE [EHFApplications];"
    ]
    assert master.committed and application.committed
    assert migrations == ["applied"]
    assert validators == ["validated"]


def test_master_creation_connection_is_autocommit_but_application_migration_is_not(monkeypatch) -> None:
    helper = load_helper()
    modes: list[bool] = []
    driver = SimpleNamespace(
        Error=RuntimeError,
        connect=lambda *_args, **kwargs: modes.append(kwargs["autocommit"]) or object(),
    )
    monkeypatch.setitem(sys.modules, "pyodbc", driver)
    monkeypatch.setattr(helper, "_read_admin_credential", lambda _path: "protected")

    helper.connect_admin("master", Path("/protected/sql-admin-password"))
    helper.connect_admin("EHFApplications", Path("/protected/sql-admin-password"))

    assert modes == [True, False]


@pytest.mark.parametrize(
    ("owner", "group", "mode", "accepted"),
    (
        (0, 0, 0o600, True),
        (0, 0, 0o640, True),
        (0, 0, 0o644, False),
        (0, 99, 0o600, False),
        (99, 0, 0o600, False),
        (0, 0, 0o660, False),
    ),
)
def test_sql_admin_credential_metadata_requires_root_root_safe_mode(
    owner: int, group: int, mode: int, accepted: bool
) -> None:
    """Break caught: bootstrap could read an administrator password exposed to non-root users."""
    helper = load_helper()
    details = SimpleNamespace(st_uid=owner, st_gid=group, st_mode=stat.S_IFREG | mode)

    if accepted:
        helper._validate_admin_credential_metadata(details)
    else:
        with pytest.raises(helper.BootstrapError, match="unsafe"):
            helper._validate_admin_credential_metadata(details)
