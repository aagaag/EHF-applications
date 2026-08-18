"""Systemd-credential keyring loading for document encryption."""

from __future__ import annotations

import base64
import binascii
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


class KeyringError(RuntimeError):
    """Raised without disclosing credential contents or locations."""


@dataclass(frozen=True, slots=True)
class Keyring:
    """Versioned AES-256 keys loaded only from a mounted credential file."""

    active_key_version: int
    keys: Mapping[int, bytes]

    def active_key(self) -> tuple[int, bytes]:
        return self.active_key_version, self.key_for(self.active_key_version)

    def key_for(self, version: int) -> bytes:
        try:
            return self.keys[version]
        except KeyError as error:
            raise KeyringError("A required document encryption key is unavailable.") from error


def _is_safe_posix_credential_mode(mode: int) -> bool:
    """Accept private files and systemd's root-group-readable credential mount."""
    return stat.S_IMODE(mode) in {0o400, 0o440, 0o600, 0o640}


def load_keyring(credential_path: Path) -> Keyring:
    """Read a versioned keyring from a systemd credential file, never the environment."""
    try:
        metadata = credential_path.stat()
        if not credential_path.is_file():
            raise KeyringError("The document encryption credential is unavailable.")
        if os.name != "nt" and not _is_safe_posix_credential_mode(metadata.st_mode):
            raise KeyringError("The document encryption credential permissions are unsafe.")
        value = json.loads(credential_path.read_text(encoding="utf-8"))
        active_version = value["active_key_version"]
        encoded_keys = value["keys"]
        if not isinstance(active_version, int) or active_version <= 0:
            raise ValueError
        if not isinstance(encoded_keys, dict):
            raise ValueError
        keys: dict[int, bytes] = {}
        for raw_version, encoded_key in encoded_keys.items():
            version = int(raw_version)
            if version <= 0 or not isinstance(encoded_key, str):
                raise ValueError
            key = base64.b64decode(encoded_key, validate=True)
            if len(key) != 32:
                raise ValueError
            keys[version] = key
        if active_version not in keys:
            raise ValueError
    except (KeyringError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error):
        raise KeyringError("The document encryption credential is invalid or unavailable.") from None
    return Keyring(active_version, MappingProxyType(keys))
