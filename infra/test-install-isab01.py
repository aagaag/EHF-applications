"""Safety contracts for the Linux-side EHF ISAB01 installer."""

from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "infra" / "install-isab01.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("ehf_installer", INSTALLER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release_archive(path: Path, required_files: tuple[str, ...]) -> None:
    with tarfile.open(path, "w") as archive:
        for name in required_files:
            payload = b"test\n"
            entry = tarfile.TarInfo(name)
            entry.mode = 0o644
            entry.size = len(payload)
            archive.addfile(entry, io.BytesIO(payload))


def test_release_paths_bind_an_exact_40_character_commit() -> None:
    """Break caught: a truncated or malformed revision could share an immutable release path."""
    installer = load_installer()
    commit = "a" * 40

    assert installer.release_path(commit) == Path("/opt/ehf/r") / commit
    with pytest.raises(installer.DeploymentError):
        installer.release_path("a" * 12)
    with pytest.raises(installer.DeploymentError):
        installer.release_path("g" * 40)


def test_prepare_release_is_idempotent_and_rejects_a_conflicting_commit(tmp_path: Path) -> None:
    """Break caught: a release directory could be silently reused for different archive bytes."""
    installer = load_installer()
    installer.RELEASE_ROOT = tmp_path / "r"
    archive = tmp_path / "release.tar"
    commit = "b" * 40
    _release_archive(archive, installer.REQUIRED_RELEASE_FILES)

    prepared = installer.prepare_release(archive, commit)
    assert (prepared / ".commit").read_text(encoding="ascii") == f"{commit}\n"
    assert installer.prepare_release(archive, commit) == prepared
    (prepared / ".commit").write_text(f"{'c' * 40}\n", encoding="ascii")
    with pytest.raises(installer.DeploymentError, match="different commit"):
        installer.prepare_release(archive, commit)


def test_safe_extract_rejects_path_escape_links_and_oversized_archives(tmp_path: Path) -> None:
    """Break caught: deployment archive extraction could write outside its immutable release root."""
    installer = load_installer()
    unsafe = tmp_path / "unsafe.tar"
    with tarfile.open(unsafe, "w") as archive:
        escape = tarfile.TarInfo("../escape")
        escape.size = 0
        archive.addfile(escape)

    with pytest.raises(installer.DeploymentError, match="unsafe"):
        installer.safe_extract(unsafe, tmp_path / "release")


def test_atomic_activation_and_rollback_only_switch_the_current_symlink(tmp_path: Path) -> None:
    """Break caught: activation or rollback could copy mutable release contents instead of atomically switching links."""
    installer = load_installer()
    installer.APP_ROOT = tmp_path / "opt" / "ehf"
    installer.CURRENT = installer.APP_ROOT / "current"
    previous = installer.APP_ROOT / "r" / ("d" * 40)
    candidate = installer.APP_ROOT / "r" / ("e" * 40)
    previous.mkdir(parents=True)
    candidate.mkdir(parents=True)
    (previous / ".commit").write_text(f"{'d' * 40}\n", encoding="ascii")
    (candidate / ".commit").write_text(f"{'e' * 40}\n", encoding="ascii")
    installer.switch_current(previous)

    recorded_previous = installer.switch_current(candidate)
    assert recorded_previous == previous
    assert installer.CURRENT.is_symlink()
    assert installer.CURRENT.resolve() == candidate

    installer.rollback_to_previous(recorded_previous)
    assert installer.CURRENT.is_symlink()
    assert installer.CURRENT.resolve() == previous
