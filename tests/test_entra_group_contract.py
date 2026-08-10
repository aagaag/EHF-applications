"""Static safety contract for the EHF Entra group reconciliation."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reconcile-ehf-entra.ps1"


def test_reconciliation_uses_exact_tenant_groups_and_verified_people() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for value in (
        "8226a4c2-10fa-4742-b4c0-f4fdb97a0534",
        "8e199674-d599-45e1-9daa-d138a0b40753",
        "fc584ecb-8be3-4f70-89d0-a5f0ae37f21a",
        "EHF-Administrators",
        "EHF-Trustees",
        "d5c5fb6a-f9c3-456c-97b1-20b450647f8c",
        "0da50d11-f875-4a4d-8ac8-f7bbd44499d7",
        "70a7cbba-44f0-4689-b600-768b9c05ec6c",
        "7747ffa7-5193-4cc8-9221-08a1dd24b026",
        "09d14671-38e1-4763-8d67-512c9787d379",
        "adriano.aguzzi@isab.science",
        "margaryta.schaltegger@isab.science",
        "elena.dececco@isab.science",
        "ricky@weissmann.ch",
        "magdalini.polymenidou@uzh.ch",
    ):
        assert value in source


def test_reconciliation_is_idempotent_fail_closed_and_uses_the_real_azure_cli() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "[CmdletBinding(SupportsShouldProcess = $true)]" in source
    assert "$WhatIfPreference" in source
    assert "Get-Command az -ErrorAction Stop" in source
    assert r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd" in source
    assert "az.cmd rest" not in source
    assert "--method', 'PATCH'" in source
    assert "--method', 'POST'" in source
    assert "Unexpected members" in source
    assert "Get-GroupState" in source
    assert source.count("Get-GroupState") >= 3
    assert "DELETE" not in source.upper()
    assert "access token" not in source.casefold()
    assert "`$top=999" not in source


def test_dry_run_never_invokes_a_graph_write() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Invoke-GraphWrite" in source
    write_function = source[source.index("function Invoke-GraphWrite") :]
    assert "if (-not $Apply)" in write_function
    assert "Replace('\"', '\\\"')" in write_function
    assert "return" in write_function
