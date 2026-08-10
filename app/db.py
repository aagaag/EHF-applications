"""EHF-only SQL Server connection handling."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Protocol

from app.config import Settings


_SESSION_OPTIONS = """
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET ARITHABORT ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET NUMERIC_ROUNDABORT OFF;
"""


class SqlCredentialSettings(Protocol):
    def read_sql_credential(self) -> str: ...


class DatabaseError(RuntimeError):
    """Raised without propagating driver text that could contain credentials."""


def _component(values: Mapping[str, str], name: str, default: str) -> str:
    value = values.get(name, default).strip()
    if not value or any(character in value for character in ";{}\r\n\0"):
        raise DatabaseError(f"{name} is invalid")
    return value


def _password_component(value: str) -> str:
    if any(character in value for character in ";{}\r\n\0"):
        return "{" + value.replace("}", "}}") + "}"
    return value


def connection_string(
    settings: SqlCredentialSettings,
    environ: Mapping[str, str] | None = None,
    *,
    connect_timeout_seconds: int = 15,
    query_timeout_seconds: int = 15,
) -> str:
    """Build the dedicated EHF connection string from EHF-prefixed settings."""
    _validated_timeout(connect_timeout_seconds, "connection")
    _validated_timeout(query_timeout_seconds, "query")
    values = os.environ if environ is None else environ
    server = _component(values, "EHF_SQL_SERVER", "tcp:127.0.0.1,1433")
    database = _component(values, "EHF_SQL_DATABASE", "EHFApplications")
    user = _component(values, "EHF_SQL_USER", "ehf_app")
    password = _password_component(settings.read_sql_credential())
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
        f"Connection Timeout={connect_timeout_seconds};"
    )


@contextmanager
def connect(
    settings: Settings | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    autocommit: bool = False,
    connect_timeout_seconds: int = 15,
    query_timeout_seconds: int = 15,
) -> Iterator[Any]:
    """Open one configured EHF connection and apply the standard session options."""
    try:
        import pyodbc
    except ImportError:
        raise DatabaseError("The SQL Server driver package is unavailable.") from None
    resolved_settings = settings or Settings.from_environment(environ)
    try:
        connection = pyodbc.connect(
            connection_string(
                resolved_settings,
                environ,
                connect_timeout_seconds=connect_timeout_seconds,
                query_timeout_seconds=query_timeout_seconds,
            ),
            autocommit=autocommit,
        )
    except pyodbc.Error:
        raise DatabaseError("Database connection failed.") from None
    try:
        try:
            connection.timeout = query_timeout_seconds
            connection.execute(_SESSION_OPTIONS)
        except pyodbc.Error:
            raise DatabaseError("Database session configuration failed.") from None
        yield connection
    finally:
        connection.close()


def _validated_timeout(value: int, label: str) -> None:
    if isinstance(value, bool) or not 1 <= value <= 15:
        raise DatabaseError(f"{label} timeout is invalid")
