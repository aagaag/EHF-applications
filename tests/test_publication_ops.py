"""Publication import operator and deployment contracts."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPORT_SCRIPT = ROOT / "scripts" / "import-publications-2026.ps1"
VERIFY_SCRIPT = ROOT / "scripts" / "verify-publications-2026.ps1"
CLI = ROOT / "app" / "importer" / "run_publications.py"


def test_deploy_release_requires_both_publication_import_modules() -> None:
    source = (ROOT / "infra" / "install-isab01.py").read_text(encoding="utf-8")

    assert '"app/importer/publications.py"' in source
    assert '"app/importer/run_publications.py"' in source


def test_publication_cli_is_plan_only_by_default_and_apply_is_root_mediated() -> None:
    source = CLI.read_text(encoding="utf-8")

    assert "ImportMode.PLAN_ONLY" in source
    assert "arguments.apply" in source
    assert "os.geteuid() != 0" in source
    assert "st_uid != 0" in source
    assert 'Path("/root/.config/finances2")' in source
    assert "--sql-admin-credential-file" in source
    assert "_open_import_connection" in source
    assert "write_google_scholar_queue" in source
    assert "Applicants: {result.application_count}" in source
    assert "Publications: {result.publication_count}" in source


def test_publication_wrapper_transfers_one_manifest_with_protected_cleanup() -> None:
    source = IMPORT_SCRIPT.read_text(encoding="utf-8")

    assert "[CmdletBinding(DefaultParameterSetName = 'PlanOnly')]" in source
    assert "[Parameter(ParameterSetName = 'Apply', Mandatory)]" in source
    assert "Test-Path -LiteralPath $_ -PathType Leaf" in source
    assert "chmod 700" in source
    assert "chmod 600" in source
    assert "/root/ehf-import/publications-2026." in source
    assert "trap cleanup EXIT" in source
    assert "case \"$stage\" in /root/ehf-import/publications-2026.*)" in source
    assert "-m app.importer.run_publications" in source
    assert "--scholar-queue" in source
    assert "--plan-only" in source
    assert "rm -rf -- '$RemoteTransfer'" in source
    assert "The publication manifest must remain outside the repository." in source


def test_publication_wrapper_preserves_existing_review_queue_and_replaces_atomically() -> None:
    source = IMPORT_SCRIPT.read_text(encoding="utf-8")

    assert "$RemoteExistingQueue" in source
    assert "Test-Path -LiteralPath $QueueFullPath -PathType Leaf" in source
    assert "existing-google-scholar-review.csv" in source
    assert 'install -m 0600 -o root -g root "$existing_queue"' in source
    assert "$LocalQueueTemp" in source
    assert "Import-Csv -LiteralPath $LocalQueueTemp" in source
    assert "$LocalQueueBackup" in source
    assert "[IO.File]::Replace($LocalQueueTemp, $QueueFullPath, $LocalQueueBackup)" in source
    assert "[IO.File]::Move($LocalQueueTemp, $QueueFullPath)" in source
    assert "final_work_id" in source
    assert "841" in source


def test_publication_verifier_requires_exact_root_owned_credential_boundary() -> None:
    source = VERIFY_SCRIPT.read_text(encoding="utf-8")

    assert "import stat" in source
    assert "details.st_uid != 0" in source
    assert "stat.S_IMODE(details.st_mode) != 0o600" in source
    assert "resolved.parent != Path('/root/.config/finances2')" in source


def test_publication_verifier_checks_exact_counts_integrity_conflicts_and_safety() -> None:
    source = VERIFY_SCRIPT.read_text(encoding="utf-8")

    for expected in (
        "publications != 841",
        "occurrences != 883",
        "metadata != 841",
        "citations != 2523",
        "doi_rows != 519",
        "google_scholar_manual != 841",
        "citation_topology_count != 0",
        "preprint_status_error_count != 0",
        "orphan_count != 0",
        "duplicate_doi_count != 0",
        "EHF_INVITATIONS_ENABLED=false",
        "EHF_PRODUCTION_MAIL_ENABLED=false",
        "Publication field conflicts:",
    ):
        assert expected in source


def test_operator_documentation_keeps_publication_manifest_and_queue_out_of_git() -> None:
    source = (ROOT / "docs" / "import-2026.md").read_text(encoding="utf-8")

    assert "## Publication records" in source
    assert "publication-import-manifest.json" in source
    assert "manual Google Scholar" in source
    assert "must remain outside the repository" in source
    assert "841" in source and "883" in source and "2,523" in source
