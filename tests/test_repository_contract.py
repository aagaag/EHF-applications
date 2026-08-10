from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPROVED_SPEC = "docs/superpowers/specs/2026-08-09-ehf-applications-portal-design.md"

EXPECTED_RUNTIME_REQUIREMENTS = [
    "fastapi==0.139.2",
    "uvicorn==0.51.0",
    "pyodbc==5.3.0",
    "python-multipart==0.0.32",
    "python-docx==1.2.0",
    "pypdf==6.10.0",
    "pypdfium2==5.12.1",
    "Pillow==12.3.0",
    "PyJWT[crypto]==2.13.0",
    "cryptography==49.0.0",
    "openpyxl==3.1.5",
]

EXPECTED_DEV_REQUIREMENTS = [
    "pytest==9.1.1",
    "httpx==0.28.1",
    "playwright==1.62.0",
    "axe-playwright-python==0.1.8",
]

BOOTSTRAP_FILES = [
    ".gitignore",
    "AGENTS.md",
    "CODEX_COORDINATION.md",
    "README.md",
    "app/__init__.py",
    "app/requirements.txt",
    "app/requirements-dev.txt",
    "pytest.ini",
]


def _read_requirement_lines(relative_path: str) -> list[str]:
    path = ROOT / relative_path
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _is_ignored(relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "--", relative_path],
        cwd=ROOT,
        check=False,
    )
    return result.returncode == 0


def test_repository_bootstrap_contract_is_present_and_safe() -> None:
    missing_files = [path for path in BOOTSTRAP_FILES if not (ROOT / path).is_file()]
    assert not missing_files, f"missing bootstrap files: {missing_files}"

    for directory in ("app", "docs", "tests"):
        assert (ROOT / directory).is_dir(), f"missing required directory: {directory}"

    assert _read_requirement_lines("app/requirements.txt") == EXPECTED_RUNTIME_REQUIREMENTS
    assert _read_requirement_lines("app/requirements-dev.txt") == EXPECTED_DEV_REQUIREMENTS
    pin_pattern = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[^\]]+\])?==[^#\s]+$")
    for requirement in EXPECTED_RUNTIME_REQUIREMENTS + EXPECTED_DEV_REQUIREMENTS:
        assert pin_pattern.fullmatch(requirement), f"unparseable dependency pin: {requirement}"

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert APPROVED_SPEC in readme
    assert (ROOT / APPROVED_SPEC).is_file()

    for ignored_path in (
        ".env",
        "app/.env",
        "credentials/app.secret",
        "documents/example.pdf",
        "imports/output/result.csv",
    ):
        assert _is_ignored(ignored_path), f"not ignored: {ignored_path}"

    coordination = (ROOT / "CODEX_COORDINATION.md").read_text(encoding="utf-8")
    token_patterns = (
        r"gh[pousr]_[A-Za-z0-9_]{20,}",
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"sk-[A-Za-z0-9_-]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN [A-Z ]+ PRIVATE KEY-----",
        r"(?i)\b(?:token|secret|password)\s*[:=]\s*\S+",
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{20,}",
    )
    for pattern in token_patterns:
        assert not re.search(pattern, coordination), f"token-like value found: {pattern}"


def test_import_and_deploy_commands_define_python_runtime_in_each_block() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runtime_definition = "$Python = 'C:\\Users\\aag\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe'"

    import_section = readme.split("## Import", 1)[1].split("## Deploy and rollback", 1)[0]
    deploy_section = readme.split("## Deploy and rollback", 1)[1].split("## Production invitation gate", 1)[0]

    assert runtime_definition in import_section
    assert runtime_definition in deploy_section


def test_deploy_commands_require_main_and_empty_git_status() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    deploy_section = readme.split("## Deploy and rollback", 1)[1].split("## Production invitation gate", 1)[0]

    assert "$Branch = git branch --show-current" in deploy_section
    assert "if ($Branch -ne 'main')" in deploy_section
    assert "$Status = git status --short" in deploy_section
    assert "if ($Status)" in deploy_section
    assert "Expected: main branch and empty git status --short output." in deploy_section
