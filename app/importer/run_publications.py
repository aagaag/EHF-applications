"""Plan or apply the reviewed EHF 2026 publication manifest."""

from __future__ import annotations

import argparse
import os
import stat
from collections.abc import Sequence
from pathlib import Path

from app.importer.publications import (
    PRODUCTION_COUNTS,
    PublicationImportError,
    SqlPublicationRepository,
    load_publication_manifest,
    run_publication_import,
    write_google_scholar_queue,
)
from app.importer.run import ImportMode, _open_import_connection


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or apply the reviewed EHF 2026 publication manifest."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--scholar-queue", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--sql-admin-credential-file", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    connection = None
    try:
        raw_bytes = arguments.manifest.read_bytes()
        manifest = load_publication_manifest(raw_bytes, expected=PRODUCTION_COUNTS)
        write_google_scholar_queue(manifest, arguments.scholar_queue)
        mode = ImportMode.APPLY if arguments.apply else ImportMode.PLAN_ONLY
        if arguments.apply:
            if os.name != "posix" or os.geteuid() != 0:
                raise PublicationImportError(
                    "Apply must run through the root-mediated ISAB01 path."
                )
            if arguments.sql_admin_credential_file is None:
                raise PublicationImportError(
                    "Apply requires the protected SQL administrator credential path."
                )
            _validate_publication_credential(arguments.sql_admin_credential_file)
            connection = _open_import_connection(arguments.sql_admin_credential_file)
            repository_factory = lambda: SqlPublicationRepository(connection)
        else:
            repository_factory = lambda: (_ for _ in ()).throw(
                AssertionError("Plan-only must not construct a database repository.")
            )
        result = run_publication_import(
            raw_bytes,
            mode=mode,
            expected=PRODUCTION_COUNTS,
            repository_factory=repository_factory,
        )
    except (OSError, PublicationImportError, ValueError) as error:
        print(f"EHF_PUBLICATION_IMPORT_ERROR: {error}")
        return 2
    finally:
        if connection is not None:
            connection.close()
    print(f"Mode: {result.mode.value}")
    print(f"Applicants: {result.application_count}")
    print(f"Publications: {result.publication_count}")
    print(f"Source occurrences: {result.source_occurrence_count}")
    print(f"Citation-source observations: {result.citation_observation_count}")
    print(f"Publication field conflicts: {result.conflict_count}")
    print(f"Import fingerprint: {result.fingerprint}")
    print(f"Completed run reused: {str(result.reused_completed_run).lower()}")
    print("Google Scholar review queue: written for manual review; no Scholar scraping was used.")
    return 0


def _validate_publication_credential(path: Path) -> None:
    approved_parent = Path("/root/.config/finances2")
    if path.is_symlink() or not path.is_file():
        raise PublicationImportError("The SQL administrator credential path is unsafe.")
    details = path.stat()
    if details.st_uid != 0 or stat.S_IMODE(details.st_mode) != 0o600:
        raise PublicationImportError("The SQL administrator credential file is not root-owned mode 0600.")
    if path.parent.resolve() != approved_parent:
        raise PublicationImportError("The SQL administrator credential path is outside the approved directory.")


if __name__ == "__main__":
    raise SystemExit(main())
