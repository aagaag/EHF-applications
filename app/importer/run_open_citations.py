"""Plan or apply a complete OpenAlex and Semantic Scholar snapshot."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

from app.importer.open_citations import (
    OpenCitationImportError,
    SqlOpenCitationRepository,
    run_open_citation_import,
)
from app.importer.publications import ManifestCounts, PublicationImportError
from app.importer.run import ImportMode, _open_import_connection
from app.importer.run_publications import _validate_publication_credential


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or apply source-specific open citation counts."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--sql-admin-credential-file", type=Path)
    parser.add_argument("--expected-applicants", type=int, default=36)
    parser.add_argument("--expected-works", type=int, default=841)
    parser.add_argument("--expected-occurrences", type=int, default=883)
    parser.add_argument("--expected-citation-statuses", type=int, default=2523)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    connection = None
    try:
        expected = ManifestCounts(
            arguments.expected_applicants,
            arguments.expected_works,
            arguments.expected_occurrences,
            arguments.expected_citation_statuses,
        )
        mode = ImportMode.APPLY if arguments.apply else ImportMode.PLAN_ONLY
        if mode == ImportMode.APPLY:
            if os.name != "posix" or os.geteuid() != 0:
                raise OpenCitationImportError(
                    "Apply must run through the root-mediated ISAB01 path."
                )
            if arguments.sql_admin_credential_file is None:
                raise OpenCitationImportError(
                    "Apply requires the protected SQL administrator credential path."
                )
            _validate_publication_credential(arguments.sql_admin_credential_file)
            connection = _open_import_connection(arguments.sql_admin_credential_file)
            repository_factory = lambda: SqlOpenCitationRepository(connection)
        else:
            repository_factory = lambda: (_ for _ in ()).throw(
                AssertionError("Plan-only must not construct a database repository.")
            )
        result = run_open_citation_import(
            arguments.manifest.read_bytes(),
            arguments.snapshot.read_bytes(),
            mode=mode,
            expected=expected,
            repository_factory=repository_factory,
        )
    except (OSError, PublicationImportError, OpenCitationImportError, ValueError) as error:
        print(f"EHF_OPEN_CITATION_IMPORT_ERROR: {error}")
        return 2
    finally:
        if connection is not None:
            connection.close()
    print(f"Mode: {mode.value}")
    print(f"Source observations: {result.review_count}")
    print(f"Observed counts: {result.observed_count}")
    print(f"Not found: {result.not_found_count}")
    print(f"Import fingerprint: {result.fingerprint}")
    print(f"Completed run reused: {str(result.reused_completed_run).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
