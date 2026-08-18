"""Safety contracts for the Linux-side EHF ISAB01 installer."""

from __future__ import annotations

import importlib.util
import io
from types import SimpleNamespace
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


class ProtectedFile:
    def __init__(self, *, owner: int, group: int, mode: int) -> None:
        self.details = SimpleNamespace(st_uid=owner, st_gid=group, st_mode=mode)

    def is_symlink(self) -> bool:
        return False

    def is_file(self) -> bool:
        return True

    def stat(self) -> SimpleNamespace:
        return self.details


def _immutable_release(path: Path, commit: str) -> Path:
    release = path / commit
    release.mkdir(parents=True)
    (release / ".commit").write_text(f"{commit}\n", encoding="ascii")
    return release


def test_release_paths_bind_an_exact_40_character_commit() -> None:
    """Break caught: a truncated or malformed revision could share an immutable release path."""
    installer = load_installer()
    commit = "a" * 40

    assert installer.release_path(commit) == Path("/opt/ehf/r") / commit
    with pytest.raises(installer.DeploymentError):
        installer.release_path("a" * 12)
    with pytest.raises(installer.DeploymentError):
        installer.release_path("g" * 40)


def test_release_bundle_requires_the_scoped_sql_bootstrap_and_every_migration_artifact() -> None:
    """Break caught: a release could activate without the exact database bootstrap or checksum inputs it needs."""
    installer = load_installer()

    assert "infra/sql-principal.py" in installer.REQUIRED_RELEASE_FILES
    assert "infra/bootstrap-ehf-database.py" in installer.REQUIRED_RELEASE_FILES
    for name in (
        "001_database_contract.sql",
        "002_application_core.sql",
        "003_audit_and_preferences.sql",
        "004_audit_and_preference_hardening.sql",
        "005_application_permissions.sql",
        "006_user_preference_read.sql",
        "007_document_store.sql",
        "008_import_provenance.sql",
        "009_document_permissions.sql",
        "010_report_export_audit.sql",
        "011_applicant_access.sql",
        "012_applicant_drafts.sql",
        "013_applicant_confirmations.sql",
        "014_applicant_projection.sql",
        "015_applicant_document_slots.sql",
        "016_entra_applicant_workflow.sql",
    ):
        assert f"database/migrations/{name}" in installer.REQUIRED_RELEASE_FILES
        assert f"database/tests/{name.replace('_', '_validate_', 1)}" in installer.REQUIRED_RELEASE_FILES


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


def test_virtual_environment_is_copy_based_and_leaves_no_compatibility_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Break caught: an interrupted deployment could make the immutable release fail its own retry check."""
    installer = load_installer()
    release = tmp_path / "release"
    release.mkdir()
    system_python = tmp_path / "python3.12"
    system_python.write_bytes(b"python")
    monkeypatch.setattr(installer, "SYSTEM_PYTHON", system_python)
    commands: list[tuple[str, ...]] = []

    def fake_run(command, **_kwargs) -> None:
        commands.append(tuple(str(value) for value in command))
        if command[1:4] == ["-m", "venv", "--copies"]:
            venv = release / "venv"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python").write_bytes(b"python")
            (venv / "lib").mkdir()
            (venv / "lib64").symlink_to("lib", target_is_directory=True)

    monkeypatch.setattr(installer, "_run", fake_run)

    executable = installer._build_venv(release)

    assert "--copies" in commands[0]
    assert executable == release / "venv" / "bin" / "python"
    assert not (release / "venv" / "lib64").exists()
    assert (release / "venv" / ".complete").read_text(encoding="ascii") == "ready\n"
    installer._harden_release(release)


def test_interrupted_dependency_install_is_removed_and_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = load_installer()
    release = tmp_path / "release"
    release.mkdir()
    system_python = tmp_path / "python3.12"
    system_python.write_bytes(b"python")
    monkeypatch.setattr(installer, "SYSTEM_PYTHON", system_python)

    def interrupted_run(command, **_kwargs) -> None:
        if command[1:4] == ["-m", "venv", "--copies"]:
            (release / "venv" / "bin").mkdir(parents=True)
            (release / "venv" / "bin" / "python").write_bytes(b"python")
        elif command[1:4] == ["-m", "pip", "install"]:
            raise installer.DeploymentError("interrupted")

    monkeypatch.setattr(installer, "_run", interrupted_run)
    with pytest.raises(installer.DeploymentError, match="interrupted"):
        installer._build_venv(release)
    assert not (release / "venv").exists()

    def successful_run(command, **_kwargs) -> None:
        if command[1:4] == ["-m", "venv", "--copies"]:
            (release / "venv" / "bin").mkdir(parents=True)
            (release / "venv" / "bin" / "python").write_bytes(b"python")

    monkeypatch.setattr(installer, "_run", successful_run)
    assert installer._build_venv(release).is_file()
    assert (release / "venv" / ".complete").is_file()


def test_marked_complete_but_corrupt_virtual_environment_is_rebuilt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Break caught: a completion marker alone could preserve a partially installed package set."""
    installer = load_installer()
    release = tmp_path / "release"
    executable = release / "venv" / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"corrupt")
    (release / "venv" / ".complete").write_text("ready\n", encoding="ascii")
    system_python = tmp_path / "python3.12"
    system_python.write_bytes(b"python")
    monkeypatch.setattr(installer, "SYSTEM_PYTHON", system_python)
    validations = 0

    def fake_run(command, **_kwargs) -> None:
        nonlocal validations
        if command[1:4] == ["-m", "pip", "check"]:
            validations += 1
            if validations == 1:
                raise installer.DeploymentError("corrupt")
        elif command[1:4] == ["-m", "venv", "--copies"]:
            (release / "venv" / "bin").mkdir(parents=True)
            (release / "venv" / "bin" / "python").write_bytes(b"rebuilt")

    monkeypatch.setattr(installer, "_run", fake_run)

    assert installer._build_venv(release).read_bytes() == b"rebuilt"
    assert validations == 2
    assert (release / "venv" / ".complete").read_text(encoding="ascii") == "ready\n"


def test_hard_interruption_leftover_is_rebuilt_only_when_release_is_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = load_installer()
    release = tmp_path / "release"
    (release / "venv" / "bin").mkdir(parents=True)
    (release / "venv" / "bin" / "python").write_bytes(b"incomplete")
    system_python = tmp_path / "python3.12"
    system_python.write_bytes(b"python")
    installer.CURRENT = tmp_path / "current"
    monkeypatch.setattr(installer, "SYSTEM_PYTHON", system_python)

    def successful_run(command, **_kwargs) -> None:
        if command[1:4] == ["-m", "venv", "--copies"]:
            (release / "venv" / "bin").mkdir(parents=True)
            (release / "venv" / "bin" / "python").write_bytes(b"complete")

    monkeypatch.setattr(installer, "_run", successful_run)
    assert installer._build_venv(release).read_bytes() == b"complete"
    assert (release / "venv" / ".complete").is_file()

    (release / "venv" / ".complete").unlink()
    installer.CURRENT.symlink_to(release, target_is_directory=True)
    with pytest.raises(installer.DeploymentError, match="active.*incomplete"):
        installer._build_venv(release)


def test_atomic_activation_and_rollback_only_switch_the_current_symlink(tmp_path: Path) -> None:
    """Break caught: activation or rollback could copy mutable release contents instead of atomically switching links."""
    installer = load_installer()
    installer.APP_ROOT = tmp_path / "opt" / "ehf"
    installer.RELEASE_ROOT = installer.APP_ROOT / "r"
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


def test_configuration_snapshot_restores_exact_previous_bytes_and_absence(tmp_path: Path) -> None:
    installer = load_installer()
    existing = tmp_path / "existing.conf"
    newly_created = tmp_path / "new.conf"
    existing.write_bytes(b"approved previous bytes\n")
    snapshot = {
        existing: installer._snapshot_path(existing),
        newly_created: installer._snapshot_path(newly_created),
    }
    existing.write_bytes(b"candidate bytes\n")
    newly_created.write_bytes(b"candidate new file\n")

    installer._restore_path(existing, snapshot[existing])
    installer._restore_path(newly_created, snapshot[newly_created])

    assert existing.read_bytes() == b"approved previous bytes\n"
    assert not newly_created.exists()


def test_readiness_wait_tolerates_service_startup_race(monkeypatch: pytest.MonkeyPatch) -> None:
    """Break caught: the first readiness miss could remove current while Python was still starting."""
    installer = load_installer()
    readiness_attempts = 0
    sleeps: list[float] = []

    monkeypatch.setattr(installer, "_service_active", lambda: True)

    def eventually_ready() -> None:
        nonlocal readiness_attempts
        readiness_attempts += 1
        if readiness_attempts == 1:
            raise installer.DeploymentError("still starting")

    monkeypatch.setattr(installer, "_ready", eventually_ready)
    monkeypatch.setattr(installer.time, "sleep", sleeps.append)

    installer._wait_until_ready(timeout_seconds=20, interval_seconds=0.25)

    assert readiness_attempts == 2
    assert sleeps == [0.25]


def test_explicit_rollback_restores_the_prior_symlink_when_target_readiness_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Break caught: a failed explicit rollback could leave current on the unreadable target release."""
    installer = load_installer()
    installer.APP_ROOT = tmp_path / "opt" / "ehf"
    installer.RELEASE_ROOT = installer.APP_ROOT / "r"
    installer.CURRENT = installer.APP_ROOT / "current"
    prior = _immutable_release(installer.RELEASE_ROOT, "d" * 40)
    target = _immutable_release(installer.RELEASE_ROOT, "e" * 40)
    installer.APP_ROOT.mkdir(parents=True, exist_ok=True)
    installer.CURRENT.symlink_to(prior)
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(installer, "_require_root", lambda: None)
    monkeypatch.setattr(installer, "_service_active", lambda: True)
    monkeypatch.setattr(installer, "_ensure_account", lambda: SimpleNamespace(pw_gid=4242))
    monkeypatch.setattr(installer, "_configuration_snapshot", lambda: {})
    monkeypatch.setattr(installer, "_install_configuration", lambda *_args: None)
    monkeypatch.setattr(installer, "_restore_configuration", lambda _snapshot: None)
    monkeypatch.setattr(installer, "_run", lambda command: commands.append(tuple(command)))
    monkeypatch.setattr(
        installer,
        "_wait_until_ready",
        lambda: (_ for _ in ()).throw(installer.DeploymentError("readiness failed")),
    )

    with pytest.raises(installer.DeploymentError, match="readiness failed"):
        installer.rollback("e" * 40)

    assert installer.CURRENT.resolve() == prior
    assert commands.count(("/usr/bin/systemctl", "restart", installer.SERVICE_NAME)) == 2


def test_explicit_rollback_restores_a_previously_inactive_service_when_target_readiness_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Break caught: a failed explicit rollback could leave a previously stopped service running."""
    installer = load_installer()
    installer.APP_ROOT = tmp_path / "opt" / "ehf"
    installer.RELEASE_ROOT = installer.APP_ROOT / "r"
    installer.CURRENT = installer.APP_ROOT / "current"
    prior = _immutable_release(installer.RELEASE_ROOT, "d" * 40)
    _immutable_release(installer.RELEASE_ROOT, "e" * 40)
    installer.APP_ROOT.mkdir(parents=True, exist_ok=True)
    installer.CURRENT.symlink_to(prior)
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(installer, "_require_root", lambda: None)
    monkeypatch.setattr(installer, "_service_active", lambda: False)
    monkeypatch.setattr(installer, "_ensure_account", lambda: SimpleNamespace(pw_gid=4242))
    monkeypatch.setattr(installer, "_configuration_snapshot", lambda: {})
    monkeypatch.setattr(installer, "_install_configuration", lambda *_args: None)
    monkeypatch.setattr(installer, "_restore_configuration", lambda _snapshot: None)
    monkeypatch.setattr(installer, "_run", lambda command: commands.append(tuple(command)))
    monkeypatch.setattr(
        installer,
        "_wait_until_ready",
        lambda: (_ for _ in ()).throw(installer.DeploymentError("readiness failed")),
    )

    with pytest.raises(installer.DeploymentError, match="readiness failed"):
        installer.rollback("e" * 40)

    assert installer.CURRENT.resolve() == prior
    assert commands[-1] == ("/usr/bin/systemctl", "stop", installer.SERVICE_NAME)


@pytest.mark.parametrize(
    ("owner", "group", "mode", "accepted"),
    (
        (0, 4242, 0o640, True),
        (0, 4242, 0o600, False),
        (0, 4242, 0o644, False),
        (0, 4242, 0o660, False),
        (0, 99, 0o640, False),
        (99, 4242, 0o640, False),
    ),
)
def test_application_and_environment_credentials_require_exact_root_ehf_0640(
    owner: int, group: int, mode: int, accepted: bool
) -> None:
    """Break caught: the runtime could load a credential readable by an unintended account."""
    installer = load_installer()
    credential = ProtectedFile(owner=owner, group=group, mode=mode)

    if accepted:
        installer._require_protected_file(credential, group_id=4242)
    else:
        with pytest.raises(installer.DeploymentError, match="unsafe|group"):
            installer._require_protected_file(credential, group_id=4242)


@pytest.mark.parametrize(
    ("owner", "group", "mode", "accepted"),
    (
        (0, 0, 0o600, True),
        (0, 0, 0o640, True),
        (0, 0, 0o644, False),
        (0, 99, 0o600, False),
        (99, 0, 0o600, False),
        (0, 0, 0o660, False),
    ),
)
def test_sql_admin_credential_requires_root_root_safe_mode(
    owner: int, group: int, mode: int, accepted: bool
) -> None:
    """Break caught: SQL administrator credentials could be exposed beyond root."""
    installer = load_installer()
    credential = ProtectedFile(owner=owner, group=group, mode=mode)

    if accepted:
        installer._require_protected_file(credential)
    else:
        with pytest.raises(installer.DeploymentError, match="unsafe|group"):
            installer._require_protected_file(credential)
