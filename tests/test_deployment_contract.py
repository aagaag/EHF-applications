"""Repository-level contracts for the EHF ISAB01 deployment boundary."""

from __future__ import annotations

import base64
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "infra" / "ehf.service"
NGINX = ROOT / "infra" / "ehf.nginx.conf"
DEPLOY = ROOT / "scripts" / "deploy-isab01.ps1"
VERIFY = ROOT / "scripts" / "verify-isab01.ps1"
IMPORT_2026 = ROOT / "scripts" / "import-call-2026.ps1"
PWSH = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
SQL_LOGIN_TEST = ROOT / "infra" / "test-sql-login.sh"


def test_service_uses_systemd_credentials_and_hardens_a_loopback_only_runtime() -> None:
    """Break caught: the deployed application could receive secrets through environment values or a public listener."""
    source = SERVICE.read_text(encoding="utf-8")

    for entry in (
        "User=ehf",
        "Group=ehf",
        "LoadCredential=sql-password:/etc/ehf/sql-app-password",
        "LoadCredential=document-keyring:/etc/ehf/document-keyring",
        "LoadCredential=session-pepper:/etc/ehf/session-pepper",
        "LoadCredential=otp-pepper:/etc/ehf/otp-pepper",
        "LoadCredential=turnstile-secret:/etc/ehf/turnstile-secret",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "PrivateTmp=true",
        "NoNewPrivileges=true",
        "CapabilityBoundingSet=",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "ReadWritePaths=/var/lib/ehf/documents /var/lib/ehf/quarantine",
        "127.0.0.1",
        "8086",
    ):
        assert entry in source
    assert "EHF_SQL_PASSWORD=" not in source
    assert "EHF_INVITATIONS_ENABLED=true" not in source
    assert "EHF_PRODUCTION_MAIL_ENABLED=true" not in source


def test_import_loads_document_keyring_through_a_transient_systemd_credential() -> None:
    """Break caught: the importer could bypass the credential-path boundary with /etc secret files."""
    source = IMPORT_2026.read_text(encoding="utf-8")

    assert "systemd-run --quiet --wait --pipe --collect" in source
    assert "LoadCredential=document-keyring:/etc/ehf/document-keyring" in source
    assert 'EHF_DOCUMENT_ENCRYPTION_KEYRING_PATH="$CREDENTIALS_DIRECTORY/document-keyring"' in source
    assert "export EHF_DOCUMENT_ENCRYPTION_KEYRING_PATH=/etc/ehf/document-keyring" not in source


def test_nginx_only_serves_the_exact_ehf_host_and_loopback_upstream() -> None:
    """Break caught: a default vhost or public upstream could broaden EHF exposure."""
    source = NGINX.read_text(encoding="utf-8")

    assert "server_name ehf.isab.science;" in source
    assert "proxy_pass http://127.0.0.1:8086;" in source
    assert "proxy_set_header Host $host;" in source
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in source
    assert "proxy_set_header X-Forwarded-Proto https;" in source
    assert "0.0.0.0:8086" not in source


def test_sql_dml_denial_probe_uses_columns_declared_by_current_import_migrations() -> None:
    """Break caught: the isolated permission probe could stop at a nonexistent migration column."""
    source = SQL_LOGIN_TEST.read_text(encoding="utf-8")
    migration_source = (ROOT / "database" / "migrations" / "008_import_provenance.sql").read_text(
        encoding="utf-8"
    )

    for table, column in (
        ("ImportRun", "ImporterVersion"),
        ("ImportRow", "SourceRowNumber"),
        ("SourceOccurrence", "SourceLocatorSha256"),
    ):
        assert f"(N'{table}',N'{column}')" in source
        assert f"CREATE TABLE dbo.{table}" in migration_source
        assert f"    {column} " in migration_source


@pytest.mark.skipif(os.name != "nt", reason="PowerShell deployment contracts run on the Windows controller")
def test_deploy_whatif_names_the_exact_commit_without_starting_remote_mutation() -> None:
    """Break caught: a dry run could connect to ISAB01 or hide the release revision it would deploy."""
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-File", str(DEPLOY), "-WhatIf"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    assert head in completed.stdout
    assert "ssh.exe" not in completed.stdout
    assert "scp.exe" not in completed.stdout


@pytest.mark.skipif(os.name != "nt", reason="PowerShell deployment contracts run on the Windows controller")
def test_deploy_and_verify_scripts_parse_without_executing_a_live_deployment() -> None:
    """Break caught: a syntax error could be discovered only after a release archive has been staged remotely."""
    for script in (DEPLOY, VERIFY):
        completed = subprocess.run(
            [PWSH, "-NoProfile", "-Command", f"[void][scriptblock]::Create((Get-Content -Raw '{script}'))"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.skipif(os.name != "nt", reason="PowerShell deployment contracts run on the Windows controller")
def test_verify_whatif_never_invokes_ssh_and_names_its_read_only_checks() -> None:
    """Break caught: verification preview could contact ISAB01 despite being requested as a dry run."""
    command = (
        "function ssh.exe { throw 'SSH_CALLED' }; "
        f"& '{VERIFY}' -WhatIf"
    )
    completed = subprocess.run(
        [PWSH, "-NoProfile", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "WhatIf: would verify" in completed.stdout
    assert "SSH_CALLED" not in completed.stdout + completed.stderr


@pytest.mark.skipif(os.name != "nt", reason="PowerShell deployment contracts run on the Windows controller")
def test_verify_transports_a_base64_decoded_remote_script_without_nested_shell_quotes(
    tmp_path: Path,
) -> None:
    """Break caught: a quoted ss filter could terminate the remote shell command before verification runs."""
    captured = tmp_path / "ssh-arguments.txt"
    command = (
        f"function ssh.exe {{ $args | Set-Content -LiteralPath '{captured}'; $global:LASTEXITCODE = 0 }}; "
        f"& '{VERIFY}'"
    )
    completed = subprocess.run(
        [PWSH, "-NoProfile", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    remote_command = captured.read_text(encoding="utf-8")
    encoded = re.search(r"'([A-Za-z0-9+/=]+)'\s*\|\s*/usr/bin/base64", remote_command)
    assert encoded is not None
    decoded = base64.b64decode(encoded.group(1)).decode("utf-8")
    assert "ss -ltn '( sport = :8086 )'" in decoded
    assert "Host: ehf.isab.science" in decoded
    assert "^[[:space:]]*server_name" in decoded
    assert "^[[:space:]]*proxy_pass" in decoded
