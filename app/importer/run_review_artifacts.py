"""Plan or apply private reviewed applicant PDF extractions."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable

from app.config import Settings
from app.documents.keys import load_keyring
from app.documents.malware import ClamDScanner
from app.documents.store import EncryptedObjectStore
from app.importer.review_artifacts import (
    ReviewArtifactImportError,
    SqlReviewArtifactRepository,
    run_review_artifact_import,
)
from app.importer.run import _open_import_connection
from app.importer.run_publications import _validate_publication_credential


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan or apply reviewed applicant PDF extracts.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--sql-admin-credential-file", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    connection = None
    try:
        raw = arguments.manifest.read_bytes()
        repository = None
        if arguments.apply:
            if os.name != "posix" or os.geteuid() != 0:
                raise ReviewArtifactImportError(
                    "Apply must run through the root-mediated production path."
                )
            if arguments.sql_admin_credential_file is None:
                raise ReviewArtifactImportError(
                    "Apply requires the protected SQL administrator credential path."
                )
            _validate_publication_credential(arguments.sql_admin_credential_file)
            settings = Settings.from_environment()
            connection = _open_import_connection(arguments.sql_admin_credential_file)
            repository = SqlReviewArtifactRepository(
                connection,
                EncryptedObjectStore(
                    Path(settings.document_root or ""),
                    load_keyring(Path(settings.document_encryption_keyring_path or "")),
                    owner=_service_owner(),
                ),
                ClamDScanner(Path(os.environ.get("EHF_CLAMD_CONFIG", "/etc/clamav/clamd.conf"))),
                Path(settings.quarantine_root or ""),
            )
        result = run_review_artifact_import(
            raw,
            source_root=arguments.source_root,
            apply=arguments.apply,
            repository=repository,
        )
    except (OSError, ReviewArtifactImportError, ValueError) as error:
        print(f"EHF_REVIEW_ARTIFACT_IMPORT_ERROR: {error}")
        return 2
    finally:
        if connection is not None:
            connection.close()
    print(f"Mode: {result.mode}")
    print(f"Applications: {result.application_count}")
    print(f"Artifacts: {result.artifact_count}")
    print(f"Applied: {result.applied_count}")
    return 0


def _service_owner(
    user_lookup: Callable[[str], Any] | None = None,
    group_lookup: Callable[[str], Any] | None = None,
) -> tuple[int, int]:
    if user_lookup is None or group_lookup is None:
        import grp
        import pwd

        user_lookup = pwd.getpwnam
        group_lookup = grp.getgrnam
    return int(user_lookup("ehf").pw_uid), int(group_lookup("ehf").gr_gid)


if __name__ == "__main__":
    raise SystemExit(main())
