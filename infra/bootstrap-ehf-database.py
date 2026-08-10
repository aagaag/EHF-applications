#!/usr/bin/env python3
"""Create and checksum-migrate only the EHF production database."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
DATABASE = "EHFApplications"
SERVER = "tcp:127.0.0.1,1433"


class BootstrapError(RuntimeError):
    """Raised without printing credentials, SQL text, or driver output."""


def validate_database_name(name: str) -> str:
    if name != DATABASE:
        raise BootstrapError("The EHF database name is invalid.")
    return name


def _validate_admin_credential_metadata(details: os.stat_result) -> None:
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != 0
        or details.st_gid != 0
        or stat.S_IMODE(details.st_mode) not in {0o600, 0o640}
    ):
        raise BootstrapError("The protected SQL administrator credential is unsafe.")


def _read_admin_credential(path: Path) -> str:
    if not path.is_absolute() or path.is_symlink():
        raise BootstrapError("The protected SQL administrator credential path is invalid.")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise BootstrapError("The protected SQL administrator credential is unavailable.") from error
    try:
        details = os.fstat(descriptor)
        _validate_admin_credential_metadata(details)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            credential = handle.read().strip()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not credential:
        raise BootstrapError("The protected SQL administrator credential is unavailable.")
    return credential


def _odbc_component(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


def connect_admin(database: str, credential_path: Path):
    validate_database_name(DATABASE)
    if database not in {"master", DATABASE}:
        raise BootstrapError("The SQL bootstrap target is invalid.")
    try:
        import pyodbc
    except ImportError as error:
        raise BootstrapError("The pinned SQL bootstrap runtime is unavailable.") from error
    credential = _read_admin_credential(credential_path)
    try:
        return pyodbc.connect(
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={_odbc_component(SERVER)};"
            f"DATABASE={_odbc_component(database)};"
            "UID={sa};"
            f"PWD={_odbc_component(credential)};"
            "Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=15;",
            autocommit=database == "master",
        )
    except pyodbc.Error as error:
        raise BootstrapError("The SQL bootstrap connection failed.") from error


def _migration_inputs() -> tuple[Path, Path]:
    migrations = ROOT / "database" / "migrations"
    validators = ROOT / "database" / "tests"
    if not migrations.is_dir() or not validators.is_dir():
        raise BootstrapError("The checked-in EHF SQL migration inputs are unavailable.")
    return migrations, validators


def apply_checksum_migrations(connection) -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.migrations import MigrationError, apply_migrations, discover_migrations

    migrations, _ = _migration_inputs()
    try:
        return apply_migrations(connection, discover_migrations(migrations))
    except MigrationError as error:
        raise BootstrapError("The EHF checksum migration run failed.") from error


def run_validators(connection) -> None:
    _, validators = _migration_inputs()
    files = sorted(validators.glob("[0-9][0-9][0-9]_validate_*.sql"))
    if [path.name for path in files] != [
        "001_validate_database_contract.sql",
        "002_validate_application_core.sql",
        "003_validate_audit_and_preferences.sql",
        "004_validate_audit_and_preference_hardening.sql",
        "005_validate_application_permissions.sql",
        "006_validate_user_preference_read.sql",
        "007_validate_document_store.sql",
        "008_validate_import_provenance.sql",
        "009_validate_document_permissions.sql",
    ]:
        raise BootstrapError("The EHF validator set is incomplete or unexpected.")
    try:
        for path in files:
            connection.cursor().execute(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise BootstrapError("The EHF SQL validator failed.") from error


def bootstrap(credential_path: Path) -> int:
    validate_database_name(DATABASE)
    master = connect_admin("master", credential_path)
    try:
        master.cursor().execute(
            "IF DB_ID(N'EHFApplications') IS NULL CREATE DATABASE [EHFApplications];"
        )
        master.commit()
    except Exception as error:
        raise BootstrapError("The exact EHF database could not be created or verified.") from error
    finally:
        master.close()

    application = connect_admin(DATABASE, credential_path)
    try:
        applied = apply_checksum_migrations(application)
        application.autocommit = True
        run_validators(application)
        application.commit()
        return applied
    except BootstrapError:
        application.rollback()
        raise
    except Exception as error:
        application.rollback()
        raise BootstrapError("The EHF database bootstrap failed.") from error
    finally:
        application.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--admin-credential-file", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        applied = bootstrap(arguments.admin_credential_file)
    except BootstrapError as error:
        print(f"EHF_DATABASE_BOOTSTRAP_ERROR: {error}", file=sys.stderr)
        return 2
    print(f"EHF database bootstrap applied {applied} migration(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
