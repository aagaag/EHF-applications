"""Create a private provisional given/family-name map for legacy import review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import unicodedata


def _key(value: str) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "",
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold(),
    )


def _split_reviewed_name(name: str, folder_alias: str) -> tuple[str, str]:
    parts = name.strip().split()
    alias_key = _key(folder_alias)
    candidates = [
        index
        for index in range(len(parts))
        if alias_key and alias_key in _key(" ".join(parts[index:]))
    ]
    if not candidates:
        raise ValueError("A reviewed folder alias does not identify a family-name component.")
    family_index = max(candidates)
    if family_index == 0 and len(parts) >= 2:
        # A legacy folder can use the complete name or a given-name alias;
        # retain the conventional final component as a provisional field.
        family_index = len(parts) - 1
    given_names = " ".join(parts[:family_index]).strip()
    family_name = " ".join(parts[family_index:]).strip()
    alias_is_non_family = max(candidates) == 0
    if not given_names or not family_name or (
        not alias_is_non_family and alias_key not in _key(family_name)
    ):
        raise ValueError("A reviewed identity could not be split without guessing.")
    return given_names, family_name


def build_map(alias_path: Path) -> dict[str, dict[str, str]]:
    payload = json.loads(alias_path.read_text(encoding="utf-8"))
    aliases = payload.get("aliases", payload)
    if not isinstance(aliases, dict) or not aliases:
        raise ValueError("The reviewed alias map is invalid.")
    result: dict[str, dict[str, str]] = {}
    for name, folder_alias in aliases.items():
        given_names, family_name = _split_reviewed_name(str(name), str(folder_alias))
        result[str(name)] = {"given_names": given_names, "family_name": family_name}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aliases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    repository = Path(__file__).resolve().parents[1]
    if output == repository or repository in output.parents:
        raise ValueError("Identity maps must stay outside Git.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_map(args.aliases), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Private identity map written for {len(build_map(args.aliases))} applicants.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
