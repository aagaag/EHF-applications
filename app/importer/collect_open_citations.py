"""Collect a private reviewed Semantic Scholar citation snapshot."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from app.importer.open_citation_collector import (
    OfficialCitationApiClient,
    OpenCitationCollectionError,
    collect_open_citation_rows,
    write_open_citation_snapshot,
)
from app.importer.publications import (
    ManifestCounts,
    PublicationImportError,
    load_publication_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect citation counts from the official Semantic Scholar API."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--user-agent",
        default="EHF-applications/2026.4 open-citation-collector",
    )
    parser.add_argument("--expected-applicants", type=int, default=36)
    parser.add_argument("--expected-works", type=int, default=841)
    parser.add_argument("--expected-occurrences", type=int, default=883)
    parser.add_argument("--expected-citation-statuses", type=int, default=2523)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[2]
    output = arguments.output.resolve()
    try:
        output.relative_to(repository_root)
    except ValueError:
        pass
    else:
        print("EHF_OPEN_CITATION_COLLECTION_ERROR: output must remain outside Git.")
        return 2
    try:
        manifest = load_publication_manifest(
            arguments.manifest.read_bytes(),
            expected=ManifestCounts(
                arguments.expected_applicants,
                arguments.expected_works,
                arguments.expected_occurrences,
                arguments.expected_citation_statuses,
            ),
        )
        client = OfficialCitationApiClient(user_agent=arguments.user_agent)
        try:
            def progress(current: int, total: int, source: str) -> None:
                if current == total or current % 25 == 0:
                    print(f"{source}: {current}/{total}", flush=True)

            rows = collect_open_citation_rows(manifest, client, progress=progress)
        finally:
            client.close()
        write_open_citation_snapshot(output, rows)
    except (OSError, PublicationImportError, OpenCitationCollectionError, ValueError) as error:
        print(f"EHF_OPEN_CITATION_COLLECTION_ERROR: {error}")
        return 2
    semantic = sum(row["citation_status"] == "OBSERVED" and row["source_code"] == "SEMANTIC_SCHOLAR" for row in rows)
    print(f"Snapshot rows: {len(rows)}")
    print(f"Semantic Scholar observed: {semantic}")
    print(f"Output: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
