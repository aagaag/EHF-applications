"""Ordered, checksummed, transactional database migrations."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from app.config import Settings
from app.db import connect


_MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{3})_(?P<name>[a-z0-9_]+)\.sql$")
_MIGRATION_DIRECTORY = Path(__file__).resolve().parents[1] / "database" / "migrations"


class MigrationError(RuntimeError):
    """Raised with migration metadata only, never SQL or driver details."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path
    checksum: bytes
    sql: str


def discover_migrations(directory: Path = _MIGRATION_DIRECTORY) -> tuple[Migration, ...]:
    """Load valid migration files in numeric version order."""
    migrations: list[Migration] = []
    versions: set[int] = set()
    for path in directory.iterdir():
        match = _MIGRATION_NAME.fullmatch(path.name)
        if not match or not path.is_file():
            continue
        version = int(match.group("version"))
        if version in versions:
            raise MigrationError("Migration versions must be unique.")
        versions.add(version)
        payload = path.read_bytes()
        try:
            sql = payload.decode("utf-8")
        except UnicodeDecodeError:
            raise MigrationError(f"Migration {path.name} is not UTF-8.") from None
        if re.search(r"^\s*GO\s*(?:--.*)?$", sql, flags=re.IGNORECASE | re.MULTILINE):
            raise MigrationError(f"Migration {path.name} contains an unsupported batch separator.")
        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                path=path,
                checksum=hashlib.sha256(payload).digest(),
                sql=sql,
            )
        )
    return tuple(sorted(migrations, key=lambda migration: migration.version))


def _applied_migrations(cursor: Any) -> dict[int, tuple[str, bytes]]:
    table_row = cursor.execute(
        "SELECT OBJECT_ID(N'dbo.SchemaMigration', N'U');"
    ).fetchone()
    if table_row is None or table_row[0] is None:
        return {}
    rows = cursor.execute(
        """
        SELECT MigrationVersion, MigrationName, ChecksumSha256
        FROM dbo.SchemaMigration
        ORDER BY MigrationVersion;
        """
    ).fetchall()
    return {
        int(version): (str(name), bytes(checksum))
        for version, name, checksum in rows
    }


def _verify_history(
    applied: dict[int, tuple[str, bytes]], migrations: Sequence[Migration]
) -> None:
    expected_prefix = [
        migration.version for migration in migrations[: len(applied)]
    ]
    if sorted(applied) != expected_prefix:
        raise MigrationError("Applied migration history is not a local version prefix.")
    discovered = {migration.version: migration for migration in migrations}
    for version, (recorded_name, recorded_checksum) in applied.items():
        migration = discovered.get(version)
        if migration is None:
            raise MigrationError(f"Applied migration {version:03d} is missing locally.")
        if recorded_name != migration.name or recorded_checksum != migration.checksum:
            raise MigrationError(f"Migration {version:03d} checksum or name drift detected.")


def apply_migrations(connection: Any, migrations: Iterable[Migration]) -> int:
    """Apply all pending migrations in one transaction and return their count."""
    ordered = tuple(migrations)
    if any(
        earlier.version >= later.version
        for earlier, later in zip(ordered, ordered[1:])
    ):
        raise MigrationError("Migrations must be supplied in strict version order.")
    cursor = connection.cursor()
    try:
        applied = _applied_migrations(cursor)
        _verify_history(applied, ordered)
    except MigrationError:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        raise MigrationError("Migration history could not be read.") from None

    pending = [migration for migration in ordered if migration.version not in applied]
    if not pending:
        return 0

    current: Migration | None = None
    try:
        cursor.execute("SET XACT_ABORT ON;")
        for current in pending:
            cursor.execute(current.sql)
            cursor.execute(
                """
                INSERT dbo.SchemaMigration
                    (MigrationVersion, MigrationName, ChecksumSha256)
                VALUES (?, ?, ?);
                """,
                current.version,
                current.name,
                current.checksum,
            )
        connection.commit()
    except Exception:
        connection.rollback()
        label = current.path.name if current is not None else "unknown"
        raise MigrationError(f"Migration {label} failed.") from None
    return len(pending)


def main() -> int:
    settings = Settings.from_environment()
    with connect(settings) as connection:
        count = apply_migrations(connection, discover_migrations())
    print(f"Applied {count} migration(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
