"""Fail-closed configuration for the EHF fellowship portal."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Mapping
from uuid import RFC_4122, UUID


class ConfigurationError(ValueError):
    """Raised when EHF configuration is missing, unsafe, or inconsistent."""


_DIRECT_SECRET_VARIABLES = (
    "EHF_SQL_PASSWORD",
    "EHF_DOCUMENT_ENCRYPTION_KEYRING",
    "EHF_SESSION_PEPPER",
    "EHF_OTP_PEPPER",
    "EHF_TURNSTILE_SECRET",
)

_CREDENTIAL_VARIABLES = {
    "EHF_SQL_CREDENTIAL_PATH": "SQL credential",
    "EHF_DOCUMENT_ENCRYPTION_KEYRING_PATH": "document encryption keyring",
    "EHF_SESSION_PEPPER_PATH": "session pepper",
    "EHF_OTP_PEPPER_PATH": "OTP pepper",
    "EHF_TURNSTILE_SECRET_PATH": "Turnstile secret",
}

_PRODUCTION_REQUIRED_VARIABLES = {
    **_CREDENTIAL_VARIABLES,
    "EHF_CLOUDFLARE_ACCESS_ISSUER": "Cloudflare Access issuer",
    "EHF_CLOUDFLARE_ACCESS_AUDIENCE": "Cloudflare Access audience",
    "EHF_ADMINISTRATOR_GROUP_ID": "administrator group ID",
    "EHF_TRUSTEE_GROUP_ID": "trustee group ID",
    "EHF_SELECTION_COMMITTEE_GROUP_ID": "selection-committee group ID",
    "EHF_ALLOWED_HOST": "allowed host",
    "EHF_DOCUMENT_ROOT": "document root",
    "EHF_QUARANTINE_ROOT": "quarantine root",
}

_APPROVED_SENDER_PATTERN = re.compile(
    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}"
)
_SUPPORTED_PRODUCTION_MAIL_TRANSPORTS = frozenset({"microsoft-graph"})


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated EHF runtime configuration without secret values."""

    environment: str
    allowed_host: str
    sql_credential_path: str | None
    document_encryption_keyring_path: str | None
    session_pepper_path: str | None
    otp_pepper_path: str | None
    turnstile_secret_path: str | None
    cloudflare_access_issuer: str | None
    cloudflare_access_audience: str | None
    administrator_group_id: str | None
    trustee_group_id: str | None
    selection_committee_group_id: str | None
    applicant_group_id: str | None
    document_root: str | None
    quarantine_root: str | None
    invitations_enabled: bool
    production_mail_enabled: bool
    applicant_portal_enabled: bool
    turnstile_site_key: str | None
    approved_mail_sender: str | None
    mail_transport: str | None
    internal_mail_delivery_test_receipt: str | None

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        """Load configuration without reading or retaining any secret material."""
        values = os.environ if environ is None else environ
        _reject_direct_secret_values(values)

        environment = _required_value(values, "EHF_ENVIRONMENT", "environment") or "development"
        if environment not in {"development", "production"}:
            raise ConfigurationError("environment must be development or production")

        if environment == "production":
            for variable, label in _PRODUCTION_REQUIRED_VARIABLES.items():
                _required_value(values, variable, label)

        allowed_host = _normalize_host(values.get("EHF_ALLOWED_HOST", "localhost"))
        if not allowed_host:
            raise ConfigurationError("allowed host is required")
        if environment == "production" and allowed_host != "ehf.isab.science":
            raise ConfigurationError("production allowed host must be ehf.isab.science")

        credential_paths = {
            variable: _credential_path(
                values.get(variable), label, production=environment == "production"
            )
            for variable, label in _CREDENTIAL_VARIABLES.items()
        }
        document_root = _storage_path(
            values.get("EHF_DOCUMENT_ROOT"),
            "document root",
            production=environment == "production",
        )
        quarantine_root = _storage_path(
            values.get("EHF_QUARANTINE_ROOT"),
            "quarantine root",
            production=environment == "production",
        )
        _reject_overlapping_storage_roots(document_root, quarantine_root)

        invitations_enabled = _boolean(values.get("EHF_INVITATIONS_ENABLED"), "invitations enabled")
        production_mail_enabled = _boolean(
            values.get("EHF_PRODUCTION_MAIL_ENABLED"), "production mail enabled"
        )
        applicant_portal_enabled = _boolean(
            values.get("EHF_APPLICANT_PORTAL_ENABLED"), "applicant portal enabled"
        )
        approved_mail_sender = _approved_sender(
            _optional_value(values, "EHF_APPROVED_MAIL_SENDER")
        )
        mail_transport = _production_mail_transport(
            _optional_value(values, "EHF_MAIL_TRANSPORT")
        )
        internal_mail_delivery_test_receipt = _delivery_test_receipt(
            _optional_value(values, "EHF_INTERNAL_MAIL_DELIVERY_TEST_RECEIPT")
        )
        if production_mail_enabled and not all(
            (approved_mail_sender, mail_transport, internal_mail_delivery_test_receipt)
        ):
            raise ConfigurationError(
                "production mail requires an approved sender, explicit mail transport, "
                "and internal delivery-test receipt"
            )
        applicant_group_id = _optional_value(values, "EHF_APPLICANT_GROUP_ID")
        turnstile_site_key = _optional_value(values, "EHF_TURNSTILE_SITE_KEY")
        if environment == "production" and applicant_portal_enabled and not applicant_group_id:
            raise ConfigurationError(
                "the applicant portal requires the EHF applicant group ID"
            )
        if environment == "production" and applicant_portal_enabled and not turnstile_site_key:
            raise ConfigurationError(
                "the applicant portal requires the Turnstile site key"
            )

        return cls(
            environment=environment,
            allowed_host=allowed_host,
            sql_credential_path=credential_paths["EHF_SQL_CREDENTIAL_PATH"],
            document_encryption_keyring_path=credential_paths[
                "EHF_DOCUMENT_ENCRYPTION_KEYRING_PATH"
            ],
            session_pepper_path=credential_paths["EHF_SESSION_PEPPER_PATH"],
            otp_pepper_path=credential_paths["EHF_OTP_PEPPER_PATH"],
            turnstile_secret_path=credential_paths["EHF_TURNSTILE_SECRET_PATH"],
            cloudflare_access_issuer=_optional_value(values, "EHF_CLOUDFLARE_ACCESS_ISSUER"),
            cloudflare_access_audience=_optional_value(values, "EHF_CLOUDFLARE_ACCESS_AUDIENCE"),
            administrator_group_id=_optional_value(values, "EHF_ADMINISTRATOR_GROUP_ID"),
            trustee_group_id=_optional_value(values, "EHF_TRUSTEE_GROUP_ID"),
            selection_committee_group_id=_optional_value(
                values, "EHF_SELECTION_COMMITTEE_GROUP_ID"
            ),
            applicant_group_id=applicant_group_id,
            document_root=document_root,
            quarantine_root=quarantine_root,
            invitations_enabled=invitations_enabled,
            production_mail_enabled=production_mail_enabled,
            applicant_portal_enabled=applicant_portal_enabled,
            turnstile_site_key=turnstile_site_key,
            approved_mail_sender=approved_mail_sender,
            mail_transport=mail_transport,
            internal_mail_delivery_test_receipt=internal_mail_delivery_test_receipt,
        )

    def read_sql_credential(self) -> str:
        return _read_credential_file(self.sql_credential_path, "SQL credential")

    def read_document_encryption_keyring(self) -> str:
        return _read_credential_file(
            self.document_encryption_keyring_path, "document encryption keyring"
        )

    def read_session_pepper(self) -> str:
        return _read_credential_file(self.session_pepper_path, "session pepper")

    def read_otp_pepper(self) -> str:
        return _read_credential_file(self.otp_pepper_path, "OTP pepper")

    def read_turnstile_secret(self) -> str:
        return _read_credential_file(self.turnstile_secret_path, "Turnstile secret")

    def diagnostics(self) -> dict[str, str | bool]:
        """Return a fixed, non-secret operational summary."""
        return {
            "environment": self.environment,
            "allowed_host": self.allowed_host,
            "invitations_enabled": self.invitations_enabled,
            "production_mail_enabled": self.production_mail_enabled,
            "applicant_portal_enabled": self.applicant_portal_enabled,
            "turnstile_site_key_configured": bool(self.turnstile_site_key),
            "cloudflare_access_configured": bool(
                self.cloudflare_access_issuer and self.cloudflare_access_audience
            ),
            "internal_groups_configured": all(
                (
                    self.administrator_group_id,
                    self.trustee_group_id,
                    self.selection_committee_group_id,
                )
            ),
            "document_storage_configured": bool(self.document_root and self.quarantine_root),
            "credential_files_configured": all(
                (
                    self.sql_credential_path,
                    self.document_encryption_keyring_path,
                    self.session_pepper_path,
                    self.otp_pepper_path,
                    self.turnstile_secret_path,
                )
            ),
            "mail_configuration_configured": all(
                (
                    self.approved_mail_sender,
                    self.mail_transport,
                    self.internal_mail_delivery_test_receipt,
                )
            ),
        }


def _reject_direct_secret_values(values: Mapping[str, str]) -> None:
    for variable in _DIRECT_SECRET_VARIABLES:
        if variable in values:
            raise ConfigurationError(
                f"{variable} is not accepted; use an absolute credential-file path"
            )


def _required_value(values: Mapping[str, str], variable: str, label: str) -> str | None:
    value = _optional_value(values, variable)
    if value is None and variable != "EHF_ENVIRONMENT":
        raise ConfigurationError(f"{label} is required")
    return value


def _optional_value(values: Mapping[str, str], variable: str) -> str | None:
    value = values.get(variable)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_host(value: str) -> str:
    return value.strip().lower().rstrip(".")


def _boolean(value: str | None, label: str) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ConfigurationError(f"{label} must be true or false")


def _credential_path(value: str | None, label: str, *, production: bool) -> str | None:
    if value is None:
        return None
    path = _absolute_path(value, f"{label} must be an absolute credential-file path")
    pure_path = _pure_path(path)
    systemd_root = PurePosixPath("/run/credentials")
    if production and (
        not isinstance(pure_path, PurePosixPath)
        or pure_path == systemd_root
        or not _contains(systemd_root, pure_path)
    ):
        raise ConfigurationError(f"{label} must be a systemd credential-file path")
    return path


def _storage_path(value: str | None, label: str, *, production: bool) -> str | None:
    if value is None:
        return None
    path = _absolute_path(value, f"{label} must be an absolute storage path")
    if production and not isinstance(_pure_path(path), PurePosixPath):
        raise ConfigurationError(f"{label} must use POSIX path semantics in production")
    return path


def _absolute_path(value: str, error_message: str) -> str:
    path = _canonical_path(_pure_path(value))
    if not path.is_absolute():
        raise ConfigurationError(error_message)
    return str(path)


def _pure_path(value: str) -> PurePath:
    if re.match(r"^[A-Za-z]:[\\\\/]", value) or value.startswith("\\\\"):
        return PureWindowsPath(value)
    return PurePosixPath(value)


def _canonical_path(path: PurePath) -> PurePath:
    """Lexically normalize a path without requiring the target to exist."""
    normalized_parts: list[str] = []
    for part in path.parts[1:]:
        if part == "..":
            if normalized_parts:
                normalized_parts.pop()
            continue
        if part != ".":
            normalized_parts.append(part)
    return type(path)(path.anchor, *normalized_parts)


def _reject_overlapping_storage_roots(
    document_root: str | None, quarantine_root: str | None
) -> None:
    if document_root is None or quarantine_root is None:
        return
    document_path = _canonical_path(_pure_path(document_root))
    quarantine_path = _canonical_path(_pure_path(quarantine_root))
    if type(document_path) is not type(quarantine_path):
        raise ConfigurationError("document root and quarantine root must use the same path semantics")
    if _contains(document_path, quarantine_path) or _contains(quarantine_path, document_path):
        raise ConfigurationError("document root and quarantine root must not overlap")


def _contains(parent: PurePath, child: PurePath) -> bool:
    parent = _canonical_path(parent)
    child = _canonical_path(child)
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _approved_sender(value: str | None) -> str | None:
    if value is None:
        return None
    if not _APPROVED_SENDER_PATTERN.fullmatch(value):
        raise ConfigurationError("approved sender must be a valid email address")
    return value


def _production_mail_transport(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.lower()
    if normalized not in _SUPPORTED_PRODUCTION_MAIL_TRANSPORTS:
        raise ConfigurationError("mail transport must be one of the supported production transports")
    return normalized


def _delivery_test_receipt(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        receipt = UUID(value)
    except ValueError:
        raise ConfigurationError("delivery-test receipt must be a canonical RFC 4122 UUIDv4") from None
    if receipt.version != 4 or receipt.variant != RFC_4122 or str(receipt) != value.lower():
        raise ConfigurationError("delivery-test receipt must be a canonical RFC 4122 UUIDv4")
    return str(receipt)


def _read_credential_file(path: str | None, label: str) -> str:
    if path is None:
        raise ConfigurationError(f"{label} credential-file path is not configured")
    try:
        secret = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        raise ConfigurationError(f"could not read {label} credential file") from None
    if not secret:
        raise ConfigurationError(f"{label} credential file is empty")
    return secret
