from __future__ import annotations

from pathlib import Path

import pytest

from app.config import ConfigurationError, Settings


def production_environment() -> dict[str, str]:
    return {
        "EHF_ENVIRONMENT": "production",
        "EHF_SQL_CREDENTIAL_PATH": "/run/credentials/ehf.service/sql-password",
        "EHF_DOCUMENT_ENCRYPTION_KEYRING_PATH": "/run/credentials/ehf.service/document-keyring",
        "EHF_SESSION_PEPPER_PATH": "/run/credentials/ehf.service/session-pepper",
        "EHF_OTP_PEPPER_PATH": "/run/credentials/ehf.service/otp-pepper",
        "EHF_TURNSTILE_SECRET_PATH": "/run/credentials/ehf.service/turnstile-secret",
        "EHF_CLOUDFLARE_ACCESS_ISSUER": "https://ehf.cloudflareaccess.com",
        "EHF_CLOUDFLARE_ACCESS_AUDIENCE": "ehf-internal-audience",
        "EHF_ADMINISTRATOR_GROUP_ID": "administrator-group-id",
        "EHF_TRUSTEE_GROUP_ID": "trustee-group-id",
        "EHF_SELECTION_COMMITTEE_GROUP_ID": "selection-committee-group-id",
        "EHF_ALLOWED_HOST": "ehf.isab.science",
        "EHF_DOCUMENT_ROOT": "/var/lib/ehf/documents",
        "EHF_QUARANTINE_ROOT": "/var/lib/ehf/quarantine",
    }


def test_development_defaults_keep_external_effects_disabled() -> None:
    """Break caught: changing a safe default could enable invitations or mail locally."""
    settings = Settings.from_environment({})

    assert settings.environment == "development"
    assert settings.allowed_host == "localhost"
    assert settings.invitations_enabled is False
    assert settings.production_mail_enabled is False
    assert settings.applicant_portal_enabled is False


def test_entra_applicant_portal_is_an_independent_non_mail_production_gate() -> None:
    """Break caught: a test pilot could silently enable real invitations or mail."""
    settings = Settings.from_environment(
        production_environment()
        | {
            "EHF_APPLICANT_PORTAL_ENABLED": "true",
            "EHF_APPLICANT_GROUP_ID": "applicant-group-id",
            "EHF_TURNSTILE_SITE_KEY": "0x4AAAAAAA-production-site-key",
        }
    )

    assert settings.applicant_portal_enabled is True
    assert settings.invitations_enabled is False
    assert settings.production_mail_enabled is False

@pytest.mark.parametrize(
    ("variable", "expected_name"),
    [
        ("EHF_SQL_CREDENTIAL_PATH", "SQL credential"),
        ("EHF_DOCUMENT_ENCRYPTION_KEYRING_PATH", "document encryption keyring"),
        ("EHF_SESSION_PEPPER_PATH", "session pepper"),
        ("EHF_OTP_PEPPER_PATH", "OTP pepper"),
        ("EHF_TURNSTILE_SECRET_PATH", "Turnstile secret"),
        ("EHF_CLOUDFLARE_ACCESS_ISSUER", "Cloudflare Access issuer"),
        ("EHF_CLOUDFLARE_ACCESS_AUDIENCE", "Cloudflare Access audience"),
        ("EHF_ADMINISTRATOR_GROUP_ID", "administrator group ID"),
        ("EHF_TRUSTEE_GROUP_ID", "trustee group ID"),
        ("EHF_SELECTION_COMMITTEE_GROUP_ID", "selection-committee group ID"),
        ("EHF_ALLOWED_HOST", "allowed host"),
        ("EHF_DOCUMENT_ROOT", "document root"),
        ("EHF_QUARANTINE_ROOT", "quarantine root"),
    ],
)
def test_production_rejects_each_missing_security_critical_setting(
    variable: str, expected_name: str
) -> None:
    """Break caught: production startup succeeding with a required control omitted."""
    environment = production_environment()
    del environment[variable]

    with pytest.raises(ConfigurationError, match=expected_name):
        Settings.from_environment(environment)


def test_production_normalizes_and_requires_the_exact_public_host() -> None:
    """Break caught: an unintended public hostname could be accepted in production."""
    normalized_environment = production_environment() | {
        "EHF_ALLOWED_HOST": " EHF.ISAB.SCIENCE. "
    }
    assert Settings.from_environment(normalized_environment).allowed_host == "ehf.isab.science"

    invalid_environment = production_environment() | {
        "EHF_ALLOWED_HOST": "staging.ehf.isab.science"
    }
    with pytest.raises(ConfigurationError, match="ehf.isab.science"):
        Settings.from_environment(invalid_environment)


@pytest.mark.parametrize(
    "variable",
    [
        "EHF_SQL_PASSWORD",
        "EHF_DOCUMENT_ENCRYPTION_KEYRING",
        "EHF_SESSION_PEPPER",
        "EHF_OTP_PEPPER",
        "EHF_TURNSTILE_SECRET",
    ],
)
def test_rejects_direct_secret_values_from_environment(variable: str) -> None:
    """Break caught: a deployment could inject a secret value instead of a credential file."""
    environment = production_environment() | {variable: "not-a-permitted-secret-source"}

    with pytest.raises(ConfigurationError, match="credential-file path"):
        Settings.from_environment(environment)


def test_production_rejects_relative_paths_and_overlapping_storage_roots() -> None:
    """Break caught: platform-dependent paths could bypass storage isolation."""
    relative_credential = production_environment() | {
        "EHF_SQL_CREDENTIAL_PATH": "credentials/sql-password"
    }
    with pytest.raises(ConfigurationError, match="absolute credential-file path"):
        Settings.from_environment(relative_credential)

    relative_document_root = production_environment() | {"EHF_DOCUMENT_ROOT": "documents"}
    with pytest.raises(ConfigurationError, match="absolute storage path"):
        Settings.from_environment(relative_document_root)

    overlapping_roots = production_environment() | {
        "EHF_QUARANTINE_ROOT": "/var/lib/ehf/documents/quarantine"
    }
    with pytest.raises(ConfigurationError, match="must not overlap"):
        Settings.from_environment(overlapping_roots)


def test_production_accepts_systemd_credential_paths_with_posix_semantics() -> None:
    """Break caught: production could read a credential from outside systemd's credential mount."""
    settings = Settings.from_environment(production_environment())
    assert settings.sql_credential_path == "/run/credentials/ehf.service/sql-password"

    outside_systemd = production_environment() | {
        "EHF_SQL_CREDENTIAL_PATH": "/var/lib/ehf/sql-password"
    }
    with pytest.raises(ConfigurationError, match="systemd credential-file path"):
        Settings.from_environment(outside_systemd)

    windows_path = production_environment() | {
        "EHF_SQL_CREDENTIAL_PATH": "C:\\credentials\\sql-password"
    }
    with pytest.raises(ConfigurationError, match="systemd credential-file path"):
        Settings.from_environment(windows_path)

    windows_storage = production_environment() | {"EHF_DOCUMENT_ROOT": "C:\\ehf\\documents"}
    with pytest.raises(ConfigurationError, match="POSIX"):
        Settings.from_environment(windows_storage)


def test_production_canonicalizes_in_root_systemd_credentials_and_rejects_traversal() -> None:
    """Break caught: lexical path checks could let a credential escape /run/credentials."""
    in_root_path = "/run/credentials/ehf.service/staging/../sql-password"
    settings = Settings.from_environment(
        production_environment() | {"EHF_SQL_CREDENTIAL_PATH": in_root_path}
    )
    assert settings.sql_credential_path == "/run/credentials/ehf.service/sql-password"

    escaped_path = "/run/credentials/ehf.service/../../../var/lib/ehf/sql-password"
    with pytest.raises(ConfigurationError, match="systemd credential-file path"):
        Settings.from_environment(
            production_environment() | {"EHF_SQL_CREDENTIAL_PATH": escaped_path}
        )


def test_development_canonicalizes_windows_credential_paths_without_reading_them() -> None:
    """Break caught: Windows-style path aliases could retain unresolved parent traversal."""
    settings = Settings.from_environment(
        {"EHF_SQL_CREDENTIAL_PATH": "C:\\ehf\\credentials\\unit\\..\\sql-password"}
    )

    assert settings.sql_credential_path == "C:\\ehf\\credentials\\sql-password"


@pytest.mark.parametrize(
    ("environment", "document_root", "quarantine_root"),
    [
        (
            production_environment(),
            "/var/lib/ehf/documents/../shared",
            "/var/lib/ehf/shared",
        ),
        (
            production_environment(),
            "/var/lib/ehf/documents/../shared",
            "/var/lib/ehf/shared/archive",
        ),
        (
            production_environment(),
            "/var/lib/ehf/shared",
            "/var/lib/ehf/shared",
        ),
        (
            {},
            "C:\\ehf\\documents\\..\\shared",
            "C:\\ehf\\shared",
        ),
        (
            {},
            "C:\\ehf\\documents\\..\\shared",
            "C:\\ehf\\shared\\archive",
        ),
        (
            {},
            "C:\\ehf\\shared",
            "C:\\ehf\\shared",
        ),
    ],
)
def test_storage_roots_reject_normalized_aliases_and_overlaps(
    environment: dict[str, str], document_root: str, quarantine_root: str
) -> None:
    """Break caught: aliasing could make document and quarantine roots overlap unnoticed."""
    with pytest.raises(ConfigurationError, match="must not overlap"):
        Settings.from_environment(
            environment
            | {
                "EHF_DOCUMENT_ROOT": document_root,
                "EHF_QUARANTINE_ROOT": quarantine_root,
            }
        )


def test_credential_helpers_read_file_contents_without_storing_them(tmp_path: Path) -> None:
    """Break caught: a helper could read secrets from the environment or retain them in Settings."""
    pepper_path = tmp_path / "session-pepper"
    pepper_path.write_text("test-only-pepper\n", encoding="utf-8")
    settings = Settings.from_environment({"EHF_SESSION_PEPPER_PATH": str(pepper_path)})

    assert settings.read_session_pepper() == "test-only-pepper"
    assert "test-only-pepper" not in repr(settings)
    assert "test-only-pepper" not in str(settings.diagnostics())


def test_diagnostics_are_a_redacted_allowlist() -> None:
    """Break caught: diagnostics could disclose credential paths or security configuration values."""
    environment = production_environment() | {
        "EHF_CLOUDFLARE_ACCESS_AUDIENCE": "audience-not-for-diagnostics",
        "EHF_APPROVED_MAIL_SENDER": "approved-sender-not-for-diagnostics@example.test",
    }
    settings = Settings.from_environment(environment)

    assert settings.diagnostics() == {
        "environment": "production",
        "allowed_host": "ehf.isab.science",
        "invitations_enabled": False,
        "production_mail_enabled": False,
        "applicant_portal_enabled": False,
        "turnstile_site_key_configured": False,
        "cloudflare_access_configured": True,
        "internal_groups_configured": True,
        "document_storage_configured": True,
        "credential_files_configured": True,
        "mail_configuration_configured": False,
    }
    assert "audience-not-for-diagnostics" not in str(settings.diagnostics())
    assert "approved-sender-not-for-diagnostics" not in str(settings.diagnostics())
    assert "/run/credentials" not in str(settings.diagnostics())


@pytest.mark.parametrize(
    "missing_variable",
    [
        "EHF_APPROVED_MAIL_SENDER",
        "EHF_MAIL_TRANSPORT",
        "EHF_INTERNAL_MAIL_DELIVERY_TEST_RECEIPT",
    ],
)
def test_production_mail_requires_all_approval_gate_configuration(
    missing_variable: str,
) -> None:
    """Break caught: production mail could be enabled before its independent approval gates exist."""
    environment = production_environment() | {
        "EHF_PRODUCTION_MAIL_ENABLED": "true",
        "EHF_APPROVED_MAIL_SENDER": "ehf-notifications@isab.science",
        "EHF_MAIL_TRANSPORT": "microsoft-graph",
        "EHF_INTERNAL_MAIL_DELIVERY_TEST_RECEIPT": "2f24c2d4-2be9-4eb3-937d-43f5f4b0af33",
    }
    del environment[missing_variable]

    with pytest.raises(ConfigurationError, match="production mail"):
        Settings.from_environment(environment)


def test_production_mail_gate_allows_a_complete_configuration() -> None:
    """Break caught: a future mail implementation could never be enabled after explicit approval."""
    settings = Settings.from_environment(
        production_environment()
        | {
            "EHF_PRODUCTION_MAIL_ENABLED": "true",
            "EHF_APPROVED_MAIL_SENDER": "ehf-notifications@isab.science",
            "EHF_MAIL_TRANSPORT": "microsoft-graph",
            "EHF_INTERNAL_MAIL_DELIVERY_TEST_RECEIPT": "2f24c2d4-2be9-4eb3-937d-43f5f4b0af33",
        }
    )

    assert settings.production_mail_enabled is True


@pytest.mark.parametrize(
    ("variable", "value", "expected_name"),
    [
        ("EHF_APPROVED_MAIL_SENDER", "not an email address", "approved sender"),
        ("EHF_APPROVED_MAIL_SENDER", "ehf-notifications@isab", "approved sender"),
        ("EHF_MAIL_TRANSPORT", "smtp", "mail transport"),
        ("EHF_INTERNAL_MAIL_DELIVERY_TEST_RECEIPT", "receipt-2026-08-10", "delivery-test receipt"),
        (
            "EHF_INTERNAL_MAIL_DELIVERY_TEST_RECEIPT",
            "2f24c2d4-2be9-3eb3-937d-43f5f4b0af34",
            "delivery-test receipt",
        ),
    ],
)
def test_production_mail_rejects_invalid_typed_gate_values(
    variable: str, value: str, expected_name: str
) -> None:
    """Break caught: arbitrary strings could make production mail appear release-ready."""
    environment = production_environment() | {
        "EHF_PRODUCTION_MAIL_ENABLED": "true",
        "EHF_APPROVED_MAIL_SENDER": "ehf-notifications@isab.science",
        "EHF_MAIL_TRANSPORT": "microsoft-graph",
        "EHF_INTERNAL_MAIL_DELIVERY_TEST_RECEIPT": "2f24c2d4-2be9-4eb3-937d-43f5f4b0af33",
        variable: value,
    }

    with pytest.raises(ConfigurationError, match=expected_name):
        Settings.from_environment(environment)


def test_production_mail_gate_accepts_typed_microsoft_graph_configuration() -> None:
    """Break caught: the supported explicit mail-release shape could be rejected."""
    settings = Settings.from_environment(
        production_environment()
        | {
            "EHF_PRODUCTION_MAIL_ENABLED": "true",
            "EHF_APPROVED_MAIL_SENDER": "ehf-notifications@isab.science",
            "EHF_MAIL_TRANSPORT": "microsoft-graph",
            "EHF_INTERNAL_MAIL_DELIVERY_TEST_RECEIPT": "2f24c2d4-2be9-4eb3-937d-43f5f4b0af33",
        }
    )

    assert settings.approved_mail_sender == "ehf-notifications@isab.science"
    assert settings.mail_transport == "microsoft-graph"
    assert settings.internal_mail_delivery_test_receipt == "2f24c2d4-2be9-4eb3-937d-43f5f4b0af33"


def test_production_applicant_portal_requires_a_turnstile_site_key() -> None:
    environment = production_environment() | {
        "EHF_APPLICANT_PORTAL_ENABLED": "true",
        "EHF_APPLICANT_GROUP_ID": "55caf353-80bb-4805-81f0-e31b6fc84b23",
    }

    with pytest.raises(ConfigurationError, match="Turnstile site key"):
        Settings.from_environment(environment)

    settings = Settings.from_environment(
        environment | {"EHF_TURNSTILE_SITE_KEY": "0x4AAAAAAA-production-site-key"}
    )
    assert settings.turnstile_site_key == "0x4AAAAAAA-production-site-key"
