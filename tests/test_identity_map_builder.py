"""Private identity-map builder tests."""

import importlib.util
import json
from pathlib import Path


def _module():
    script = Path(__file__).parents[1] / "scripts" / "build-identity-map.py"
    spec = importlib.util.spec_from_file_location("build_identity_map", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_map_uses_reviewed_full_name_without_exposing_alias_as_legal_name(tmp_path: Path) -> None:
    path = tmp_path / "aliases.json"
    path.write_text(
        json.dumps({"call": "2026", "aliases": {"Example Applicant": "Applicant"}}),
        encoding="utf-8",
    )

    assert _module().build_map(path) == {
        "Example Applicant": {"given_names": "Example", "family_name": "Applicant"}
    }


def test_reviewed_alias_preserves_compound_family_name_suffix(tmp_path: Path) -> None:
    path = tmp_path / "aliases.json"
    path.write_text(
        json.dumps({"aliases": {"Example Gonzalez-Acosta Perez": "Acosta"}}),
        encoding="utf-8",
    )

    assert _module().build_map(path) == {
        "Example Gonzalez-Acosta Perez": {
            "given_names": "Example",
            "family_name": "Gonzalez-Acosta Perez",
        }
    }
