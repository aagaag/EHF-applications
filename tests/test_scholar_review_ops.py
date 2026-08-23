"""Google Scholar review operator and deployment contracts."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "app" / "importer" / "run_scholar_reviews.py"
IMPORT_SCRIPT = ROOT / "scripts" / "import-scholar-reviews-2026.ps1"
VERIFY_SCRIPT = ROOT / "scripts" / "verify-scholar-reviews-2026.ps1"


def test_release_requires_scholar_review_modules() -> None:
    source = (ROOT / "infra" / "install-isab01.py").read_text(encoding="utf-8")
    assert '"app/importer/scholar_reviews.py"' in source
    assert '"app/importer/run_scholar_reviews.py"' in source


def test_review_cli_is_plan_only_by_default_and_apply_is_root_mediated() -> None:
    assert CLI.exists()
    source = CLI.read_text(encoding="utf-8")
    assert "ImportMode.PLAN_ONLY" in source
    assert "arguments.apply" in source
    assert "os.geteuid() != 0" in source
    assert "--sql-admin-credential-file" in source
    assert "run_scholar_review_import" in source
    assert "Reviews: {result.review_count}" in source
    assert "Observed counts: {result.observed_count}" in source
    assert "Not found: {result.not_found_count}" in source


def test_review_wrapper_transfers_only_protected_private_inputs_and_cleans_up() -> None:
    assert IMPORT_SCRIPT.exists()
    source = IMPORT_SCRIPT.read_text(encoding="utf-8")
    assert "[CmdletBinding(DefaultParameterSetName = 'PlanOnly')]" in source
    assert "chmod 700" in source and "chmod 600" in source
    assert "/root/ehf-import/scholar-reviews-2026." in source
    assert "trap cleanup EXIT" in source
    assert "-m app.importer.run_scholar_reviews" in source
    assert "--plan-only" in source and "--apply" in source
    assert "The reviewed Scholar queue must remain outside the repository." in source
    assert "rm -rf -- '$RemoteTransfer'" in source


def test_review_verifier_checks_latest_scholar_state_and_safety() -> None:
    assert VERIFY_SCRIPT.exists()
    source = VERIFY_SCRIPT.read_text(encoding="utf-8")
    for fragment in (
        "ROW_NUMBER() OVER",
        "ObservedAtUtc DESC",
        "latest_google_scholar != 841",
        "pending_manual != 0",
        "observed + not_found != 841",
        "invalid_observed != 0",
        "EHF_INVITATIONS_ENABLED=false",
        "EHF_PRODUCTION_MAIL_ENABLED=false",
    ):
        assert fragment in source


def test_operator_documentation_covers_completed_review_validation_and_apply() -> None:
    source = (ROOT / "docs" / "import-2026.md").read_text(encoding="utf-8")

    assert "citation_status" in source
    assert "CAPTCHA or access-block responses are not `NOT_FOUND`" in source
    assert "scripts\\import-scholar-reviews-2026.ps1" in source
    assert "scripts\\verify-scholar-reviews-2026.ps1" in source
    assert "appends a separately audited Google Scholar observation" in source
