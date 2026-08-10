"""Repository-level contracts for the EHF ISAB01 deployment boundary."""

from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "infra" / "ehf.service"
NGINX = ROOT / "infra" / "ehf.nginx.conf"
DEPLOY = ROOT / "scripts" / "deploy-isab01.ps1"
VERIFY = ROOT / "scripts" / "verify-isab01.ps1"


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


def test_nginx_only_serves_the_exact_ehf_host_and_loopback_upstream() -> None:
    """Break caught: a default vhost or public upstream could broaden EHF exposure."""
    source = NGINX.read_text(encoding="utf-8")

    assert "server_name ehf.isab.science;" in source
    assert "proxy_pass http://127.0.0.1:8086;" in source
    assert "proxy_set_header Host $host;" in source
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in source
    assert "proxy_set_header X-Forwarded-Proto https;" in source
    assert "0.0.0.0:8086" not in source


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


def test_deploy_and_verify_scripts_parse_without_executing_a_live_deployment() -> None:
    """Break caught: a syntax error could be discovered only after a release archive has been staged remotely."""
    for script in (DEPLOY, VERIFY):
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"[void][scriptblock]::Create((Get-Content -Raw '{script}'))"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
