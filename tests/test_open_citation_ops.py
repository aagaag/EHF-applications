from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "app" / "importer" / "run_open_citations.py"
COLLECTOR = ROOT / "app" / "importer" / "collect_open_citations.py"
COLLECT_SCRIPT = ROOT / "scripts" / "collect-open-citations-2026.ps1"
IMPORT_SCRIPT = ROOT / "scripts" / "import-open-citations-2026.ps1"
VERIFY_SCRIPT = ROOT / "scripts" / "verify-open-citations-2026.ps1"


def test_release_contains_open_citation_modules_and_release_23_database_artifacts() -> None:
    source = (ROOT / "infra" / "install-isab01.py").read_text(encoding="utf-8")
    for path in (
        "app/importer/open_citations.py",
        "app/importer/open_citation_collector.py",
        "app/importer/collect_open_citations.py",
        "app/importer/run_open_citations.py",
        "database/migrations/023_open_citation_sources.sql",
        "database/tests/023_validate_open_citation_sources.sql",
    ):
        assert f'"{path}"' in source


def test_collector_and_import_cli_are_separate_and_apply_is_root_mediated() -> None:
    assert COLLECTOR.exists() and CLI.exists()
    collector = COLLECTOR.read_text(encoding="utf-8")
    cli = CLI.read_text(encoding="utf-8")
    assert "OfficialCitationApiClient" in collector
    assert "output must remain outside Git" in collector
    assert "ImportMode.PLAN_ONLY" in cli
    assert "os.geteuid() != 0" in cli
    assert "--sql-admin-credential-file" in cli


def test_collection_wrapper_runs_unprivileged_on_isab01_and_cleans_private_staging() -> None:
    assert COLLECT_SCRIPT.exists()
    source = COLLECT_SCRIPT.read_text(encoding="utf-8")
    assert "aag@10.10.20.29" in source
    assert "chmod 700" in source and "chmod 600" in source
    assert "/opt/ehf/current/venv/bin/python" in source
    assert "-m app.importer.collect_open_citations" in source
    assert "sudo" not in source.lower()
    assert "finally" in source and "rm -rf -- '$RemoteTransfer'" in source
    assert "must remain outside the repository" in source
    assert "GetRelativePath" not in source
    assert "[StringComparison]::OrdinalIgnoreCase" in source


def test_import_wrapper_protects_private_snapshot_and_verifier_requires_semantic_scholar() -> None:
    assert IMPORT_SCRIPT.exists() and VERIFY_SCRIPT.exists()
    importer = IMPORT_SCRIPT.read_text(encoding="utf-8")
    verifier = VERIFY_SCRIPT.read_text(encoding="utf-8")
    assert "chmod 700" in importer and "chmod 600" in importer
    assert "trap cleanup EXIT" in importer
    assert "-m app.importer.run_open_citations" in importer
    assert "The open citation snapshot must remain outside the repository." in importer
    for fragment in (
        "SEMANTIC_SCHOLAR",
        "source_rows != 841",
        "semantic_rows != 841",
        "observation_rows != 841",
        "observation.ImportRunId=?",
        "EHF_INVITATIONS_ENABLED=false",
        "EHF_PRODUCTION_MAIL_ENABLED=false",
    ):
        assert fragment in verifier
    for obsolete_requirement in (
        "OPENALEX",
        "source_rows != 1682",
        "openalex_rows != 841",
        "citation_disagreements",
    ):
        assert obsolete_requirement not in verifier


def test_collection_cli_reports_semantic_scholar_only() -> None:
    collector = COLLECTOR.read_text(encoding="utf-8")
    assert "Semantic Scholar observed:" in collector
    assert "OpenAlex observed:" not in collector
