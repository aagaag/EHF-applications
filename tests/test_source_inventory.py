from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.importer.inventory import inventory_source_tree, write_inventory_manifests


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_SCRIPT = ROOT / "scripts" / "inventory-call-2026.ps1"


def test_inventory_records_each_file_occurrence_with_stable_relative_paths(tmp_path: Path) -> None:
    """Break caught: an inventory could omit an occurrence or make paths machine-dependent."""
    source_root = tmp_path / "call"
    (source_root / "Ada Lovelace").mkdir(parents=True)
    (source_root / "Selection Committee").mkdir()
    first = source_root / "Ada Lovelace" / "cv.PDF"
    second = source_root / "Selection Committee" / "copy.pdf"
    first.write_bytes(b"same synthetic PDF bytes")
    second.write_bytes(b"same synthetic PDF bytes")

    report = inventory_source_tree(source_root)

    assert [occurrence.relative_path for occurrence in report.occurrences] == [
        "Ada Lovelace/cv.PDF",
        "Selection Committee/copy.pdf",
    ]
    assert [occurrence.sha256 for occurrence in report.occurrences] == [
        hashlib.sha256(b"same synthetic PDF bytes").hexdigest(),
        hashlib.sha256(b"same synthetic PDF bytes").hexdigest(),
    ]
    assert [occurrence.is_internal for occurrence in report.occurrences] == [False, True]
    assert report.duplicate_hashes == {
        hashlib.sha256(b"same synthetic PDF bytes").hexdigest(): (
            "Ada Lovelace/cv.PDF",
            "Selection Committee/copy.pdf",
        )
    }


def test_inventory_writes_short_external_manifests_without_mutating_or_escaping_source(
    tmp_path: Path,
) -> None:
    """Break caught: inventory output could alter source material or traverse an external link."""
    source_root = tmp_path / "call"
    applicant = source_root / "Ada Lovelace"
    applicant.mkdir(parents=True)
    (applicant / "CV.PdF").write_bytes(b"synthetic cv")
    (applicant / "notes.txt").write_bytes(b"synthetic note")
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    (outside_root / "private.pdf").write_bytes(b"must not be inventoried")
    try:
        os.symlink(outside_root, source_root / "linked-outside", target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    before = {
        path.relative_to(source_root).as_posix(): path.read_bytes()
        for path in source_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    report = inventory_source_tree(source_root)
    output_root = tmp_path / "manifests"
    json_path, csv_path = write_inventory_manifests(report, output_root)

    assert json_path.name == "i.json"
    assert csv_path.name == "i.csv"
    assert json.loads(json_path.read_text(encoding="utf-8"))["occurrences"] == [
        {
            "byte_size": 12,
            "is_internal": False,
            "is_pdf": True,
            "relative_path": "Ada Lovelace/CV.PdF",
            "sha256": hashlib.sha256(b"synthetic cv").hexdigest(),
        },
        {
            "byte_size": 14,
            "is_internal": False,
            "is_pdf": False,
            "relative_path": "Ada Lovelace/notes.txt",
            "sha256": hashlib.sha256(b"synthetic note").hexdigest(),
        },
    ]
    assert "linked-outside" in {issue.relative_path for issue in report.issues}
    assert all("private.pdf" not in item.relative_path for item in report.occurrences)
    after = {
        path.relative_to(source_root).as_posix(): path.read_bytes()
        for path in source_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    assert after == before

    with pytest.raises(ValueError, match="outside the source tree"):
        write_inventory_manifests(report, source_root / "output")


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell controller contract")
def test_inventory_script_reports_synthetic_counts_and_leaves_its_source_unchanged(
    tmp_path: Path,
) -> None:
    """Break caught: the operator script could hide exceptions or alter the call source."""
    source_root = tmp_path / "call"
    (source_root / "Synthetic Applicant").mkdir(parents=True)
    source_file = source_root / "Synthetic Applicant" / "cv.pdf"
    source_file.write_bytes(b"synthetic source")
    before = source_file.read_bytes()

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-File",
            str(INVENTORY_SCRIPT),
            "-SourceRoot",
            str(source_root),
            "-OutputRoot",
            str(tmp_path / "output"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Applicant directory candidates: 1" in completed.stdout
    assert "PDF occurrences: 1" in completed.stdout
    assert "Exceptions: 0" in completed.stdout
    assert "Source hash unchanged: True" in completed.stdout
    assert source_file.read_bytes() == before
    assert (tmp_path / "output" / "i.json").is_file()
    assert (tmp_path / "output" / "i.csv").is_file()
