#!/usr/bin/env python3
"""Atomic, fail-closed deployment helper for the EHF service on ISAB01."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

try:
    import pwd
except ModuleNotFoundError:  # pragma: no cover - import-only safety tests run on Windows.
    pwd = None  # type: ignore[assignment]


APP_ROOT = Path("/opt/ehf")
RELEASE_ROOT = APP_ROOT / "r"
CURRENT = APP_ROOT / "current"
CONFIG_ROOT = Path("/etc/ehf")
ENVIRONMENT_FILE = CONFIG_ROOT / "ehf.env"
SERVICE_FILE = Path("/etc/systemd/system/ehf.service")
NGINX_AVAILABLE = Path("/etc/nginx/sites-available/ehf")
NGINX_ENABLED = Path("/etc/nginx/sites-enabled/ehf")
SERVICE_NAME = "ehf.service"
SERVICE_USER = "ehf"
SERVICE_GROUP = "ehf"
DOCUMENT_ROOT = Path("/var/lib/ehf/documents")
QUARANTINE_ROOT = Path("/var/lib/ehf/quarantine")
ARCHIVE_RE = re.compile(r"^/tmp/ehf-[0-9]+\.tar$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
REQUIRED_RELEASE_FILES = (
    "app/config.py",
    "app/main.py",
    "app/requirements.txt",
    "app/requirements-dev.txt",
    "infra/ehf.service",
    "infra/ehf.nginx.conf",
    "infra/setup-sql-login.sh",
    "infra/test-sql-login.sh",
    "infra/test-install-isab01.py",
)
REQUIRED_CREDENTIALS = (
    "sql-app-password",
    "document-keyring",
    "session-pepper",
    "otp-pepper",
    "turnstile-secret",
)
PREACTIVATION_CREDENTIALS = tuple(
    credential for credential in REQUIRED_CREDENTIALS if credential != "sql-app-password"
)


class DeploymentError(RuntimeError):
    """Raised without embedding credential values or command output."""


def _run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    try:
        subprocess.run(command, cwd=cwd, env=env, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise DeploymentError("A required deployment command failed.") from error


def _require_root() -> None:
    if os.geteuid() != 0:
        raise DeploymentError("This deployment operation must run as root.")


def release_path(commit: str) -> Path:
    if not COMMIT_RE.fullmatch(commit):
        raise DeploymentError("The release commit must be exactly 40 lowercase hexadecimal characters.")
    return RELEASE_ROOT / commit


def _release_commit(release: Path) -> str:
    marker = release / ".commit"
    try:
        commit = marker.read_text(encoding="ascii").strip()
    except OSError as error:
        raise DeploymentError("The named release has no immutable commit marker.") from error
    if not COMMIT_RE.fullmatch(commit) or release != release_path(commit):
        raise DeploymentError("The named release is not an immutable EHF release.")
    return commit


def safe_extract(archive: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive, "r:") as bundle:
            members = bundle.getmembers()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise DeploymentError("The release archive contains too many members.")
            total_size = 0
            for member in members:
                member_path = Path(member.name)
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                    or not (member.isfile() or member.isdir())
                ):
                    raise DeploymentError("The release archive contains an unsafe member.")
                total_size += max(member.size, 0)
                if total_size > MAX_ARCHIVE_BYTES:
                    raise DeploymentError("The release archive is unexpectedly large.")
            destination.mkdir(mode=0o755, parents=True, exist_ok=False)
            bundle.extractall(destination, filter="data")
    except (OSError, tarfile.TarError) as error:
        raise DeploymentError("The release archive could not be extracted safely.") from error


def _harden_release(release: Path) -> None:
    for path in [release, *release.rglob("*")]:
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise DeploymentError("The extracted release has an unsafe filesystem object.")
        mode = 0o755 if path.is_dir() else (path.stat().st_mode & 0o755)
        if path.is_file() and mode == 0:
            mode = 0o644
        if hasattr(os, "chown"):
            os.chown(path, 0, 0)
        os.chmod(path, mode)


def prepare_release(archive: Path, commit: str) -> Path:
    release = release_path(commit)
    marker = release / ".commit"
    if release.exists() or release.is_symlink():
        if release.is_symlink() or not release.is_dir() or not marker.is_file():
            raise DeploymentError("The existing release directory is unsafe.")
        if marker.read_text(encoding="ascii").strip() != commit:
            raise DeploymentError("The existing release directory has a different commit.")
        _harden_release(release)
        return release

    RELEASE_ROOT.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = RELEASE_ROOT / f".{commit}.{os.getpid()}"
    if temporary.exists() or temporary.is_symlink():
        raise DeploymentError("The fixed release staging path already exists.")
    try:
        safe_extract(archive, temporary)
        for relative in REQUIRED_RELEASE_FILES:
            if not (temporary / relative).is_file():
                raise DeploymentError("The release is missing a required deployment file.")
        (temporary / ".commit").write_text(f"{commit}\n", encoding="ascii")
        os.chmod(temporary / ".commit", 0o644)
        _harden_release(temporary)
        os.replace(temporary, release)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            shutil.rmtree(temporary)
    return release


def switch_current(release: Path) -> Path | None:
    _release_commit(release)
    APP_ROOT.mkdir(mode=0o755, parents=True, exist_ok=True)
    previous: Path | None = None
    if CURRENT.exists() or CURRENT.is_symlink():
        if not CURRENT.is_symlink():
            raise DeploymentError("The current EHF path must be a symbolic link.")
        previous = CURRENT.resolve(strict=True)
        _release_commit(previous)
    temporary = APP_ROOT / f".current.{os.getpid()}"
    if temporary.exists() or temporary.is_symlink():
        raise DeploymentError("The fixed current-link staging path already exists.")
    try:
        temporary.symlink_to(release)
        try:
            os.replace(temporary, CURRENT)
        except PermissionError:
            if os.name != "nt":
                raise
            # Windows cannot atomically replace a directory link in the local
            # import-only safety test. ISAB01 always uses the atomic POSIX path.
            if CURRENT.is_symlink():
                CURRENT.unlink()
            os.replace(temporary, CURRENT)
    finally:
        if temporary.is_symlink() or temporary.exists():
            temporary.unlink()
    return previous


def rollback_to_previous(previous: Path) -> None:
    _release_commit(previous)
    switch_current(previous)


def _service_active() -> bool:
    return subprocess.run(
        ["/usr/bin/systemctl", "is-active", "--quiet", SERVICE_NAME], check=False
    ).returncode == 0


def _ensure_account() -> pwd.struct_passwd:
    if pwd is None:
        raise DeploymentError("The EHF installer requires a Linux account database.")
    try:
        account = pwd.getpwnam(SERVICE_USER)
    except KeyError:
        _run(
            [
                "/usr/sbin/useradd",
                "--system",
                "--user-group",
                "--home-dir",
                "/nonexistent",
                "--shell",
                "/usr/sbin/nologin",
                SERVICE_USER,
            ]
        )
        account = pwd.getpwnam(SERVICE_USER)
    if account.pw_shell not in {"/usr/sbin/nologin", "/sbin/nologin"}:
        raise DeploymentError("The EHF service user must not have a login shell.")
    _run(["/usr/sbin/usermod", "--lock", SERVICE_USER])
    return account


def _ensure_directory(path: Path, account: pwd.struct_passwd) -> None:
    if path.is_symlink():
        raise DeploymentError("An EHF writable path must not be a symbolic link.")
    path.mkdir(mode=0o750, parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise DeploymentError("An EHF writable path has an unsafe shape.")
    os.chown(path, account.pw_uid, account.pw_gid)
    os.chmod(path, 0o750)


def _require_protected_file(path: Path, *, group_id: int | None = None) -> None:
    if path.is_symlink() or not path.is_file():
        raise DeploymentError("A required protected EHF configuration file is unavailable.")
    stat_result = path.stat()
    if stat_result.st_uid != 0 or stat_result.st_mode & 0o022:
        raise DeploymentError("A required protected EHF configuration file is unsafe.")
    if group_id is not None and stat_result.st_gid != group_id:
        raise DeploymentError("A required protected EHF credential has an unexpected group.")


def _install_configuration(release: Path, account: pwd.struct_passwd) -> None:
    _require_protected_file(ENVIRONMENT_FILE, group_id=account.pw_gid)
    for credential in PREACTIVATION_CREDENTIALS:
        _require_protected_file(CONFIG_ROOT / credential, group_id=account.pw_gid)
    shutil.copy2(release / "infra" / "ehf.service", SERVICE_FILE)
    os.chown(SERVICE_FILE, 0, 0)
    os.chmod(SERVICE_FILE, 0o644)
    NGINX_AVAILABLE.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    shutil.copy2(release / "infra" / "ehf.nginx.conf", NGINX_AVAILABLE)
    os.chown(NGINX_AVAILABLE, 0, 0)
    os.chmod(NGINX_AVAILABLE, 0o644)
    if NGINX_ENABLED.exists() or NGINX_ENABLED.is_symlink():
        if not NGINX_ENABLED.is_symlink() or NGINX_ENABLED.resolve() != NGINX_AVAILABLE:
            raise DeploymentError("The enabled EHF Nginx site has an unexpected target.")
    else:
        NGINX_ENABLED.symlink_to(NGINX_AVAILABLE)
    _run(["/usr/sbin/nginx", "-t"])


def _build_venv(release: Path) -> Path:
    python = Path("/usr/bin/python3.12")
    if not python.is_file():
        raise DeploymentError("Python 3.12 is unavailable on ISAB01.")
    venv = release / "venv"
    if not (venv / "bin" / "python").is_file():
        _run([str(python), "-m", "venv", str(venv)])
        _run(
            [
                str(venv / "bin" / "python"),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "-r",
                "app/requirements.txt",
                "-r",
                "app/requirements-dev.txt",
            ],
            cwd=release,
        )
    return venv / "bin" / "python"


def _preactivation_tests(
    release: Path, sql_admin_credential: Path, account: pwd.struct_passwd
) -> None:
    python = _build_venv(release)
    environment = os.environ.copy()
    environment.update(
        {
            "EHF_SQL_TEST_MODE": "1",
            "EHF_SQL_ADMIN_PASSWORD_FILE": str(sql_admin_credential),
            "EHF_SQL_PRINCIPAL_PYTHON": str(python),
        }
    )
    _run([str(python), "-m", "pytest", "infra/test-install-isab01.py", "-q"], cwd=release)
    _run([str(python), "-m", "pytest", "-q"], cwd=release)
    _run(["/bin/bash", "infra/test-sql-login.sh"], cwd=release, env=environment)
    _run(["/bin/bash", "infra/setup-sql-login.sh"], cwd=release, env=environment)
    _require_protected_file(CONFIG_ROOT / "sql-app-password", group_id=account.pw_gid)


def _ready() -> None:
    _run(
        [
            "/usr/bin/curl",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            "5",
            "--header",
            "Host: ehf.isab.science",
            "http://127.0.0.1:8086/health/ready",
        ]
    )


def _restore(previous: Path | None, service_was_active: bool) -> None:
    if previous is None:
        if CURRENT.is_symlink():
            CURRENT.unlink()
    else:
        rollback_to_previous(previous)
    _run(["/usr/bin/systemctl", "daemon-reload"])
    if service_was_active and previous is not None:
        _run(["/usr/bin/systemctl", "restart", SERVICE_NAME])
    else:
        _run(["/usr/bin/systemctl", "stop", SERVICE_NAME])


def deploy(archive: Path, commit: str, sql_admin_credential: Path) -> None:
    _require_root()
    if not ARCHIVE_RE.fullmatch(str(archive)) or not archive.is_file() or archive.is_symlink():
        raise DeploymentError("The release archive must use the fixed safe ISAB01 staging path.")
    _require_protected_file(sql_admin_credential)
    account = _ensure_account()
    _ensure_directory(DOCUMENT_ROOT, account)
    _ensure_directory(QUARANTINE_ROOT, account)
    release = prepare_release(archive, commit)
    _install_configuration(release, account)
    _preactivation_tests(release, sql_admin_credential, account)
    service_was_active = _service_active()
    previous = switch_current(release)
    try:
        _run(["/usr/bin/systemctl", "daemon-reload"])
        _run(["/usr/bin/systemctl", "enable", SERVICE_NAME])
        _run(["/usr/bin/systemctl", "restart", SERVICE_NAME])
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if _service_active():
                _ready()
                break
            time.sleep(0.5)
        else:
            raise DeploymentError("The EHF service did not become active.")
        _run(["/usr/bin/systemctl", "reload", "nginx.service"])
    except Exception:
        _restore(previous, service_was_active)
        raise


def rollback(commit: str) -> None:
    _require_root()
    release = release_path(commit)
    _release_commit(release)
    previous_service_state = _service_active()
    rollback_to_previous(release)
    try:
        _run(["/usr/bin/systemctl", "daemon-reload"])
        _run(["/usr/bin/systemctl", "restart", SERVICE_NAME])
        _ready()
    except Exception:
        if previous_service_state:
            _run(["/usr/bin/systemctl", "restart", SERVICE_NAME])
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deploy an immutable EHF release on ISAB01.")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--commit")
    parser.add_argument("--sql-admin-credential", type=Path)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--apply", action="store_true")
    actions.add_argument("--rollback")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.apply:
            if not arguments.archive or not arguments.commit or not arguments.sql_admin_credential:
                raise DeploymentError("Apply requires archive, commit, and SQL administrator credential path.")
            deploy(arguments.archive, arguments.commit, arguments.sql_admin_credential)
        else:
            rollback(arguments.rollback)
    except DeploymentError as error:
        print(f"EHF_DEPLOY_ERROR: {error}", file=sys.stderr)
        return 2
    print("EHF deployment operation completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
