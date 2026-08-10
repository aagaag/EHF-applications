"""AES-256-GCM encrypted, atomically promoted document objects."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import struct
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.documents.keys import Keyring, KeyringError


_FORMAT_VERSION = 1
_MAGIC = b"EHFOD"
_HEADER = struct.Struct(">5sBH12s")
_OBJECT_KEY = re.compile(r"[0-9a-f]{32}")


class DocumentStoreError(RuntimeError):
    """Raised without exposing document names, paths, hashes, or plaintext."""


class DuplicatePlaintextError(DocumentStoreError):
    """Raised before a duplicate plaintext is promoted as a second object."""


@dataclass(frozen=True, slots=True)
class ObjectBinding:
    """Immutable identifiers included in every document object's authenticated data."""

    application_id: UUID
    document_id: UUID
    version_id: UUID
    object_id: UUID

    def aad(self) -> bytes:
        return b"EHF-DOCUMENT\x00" + bytes([_FORMAT_VERSION]) + b"".join(
            identifier.bytes
            for identifier in (
                self.application_id,
                self.document_id,
                self.version_id,
                self.object_id,
            )
        )


@dataclass(frozen=True, slots=True)
class StoredObjectRecord:
    """Metadata required to verify and decrypt one encrypted object."""

    object_key: str
    key_version: int
    envelope_version: int
    nonce: bytes
    plaintext_sha256: bytes
    ciphertext_sha256: bytes
    byte_size: int


class EncryptedObjectStore:
    """Private filesystem object store with fsync-plus-rename promotion."""

    def __init__(
        self, root: Path, keyring: Keyring, *, owner: tuple[int, int] | None = None
    ) -> None:
        self._root = root
        self._objects = root / "o"
        self._quarantine = root / "q"
        self._keyring = keyring
        self._owner = owner
        self._plaintext_hashes: set[bytes] = set()
        self._lock = threading.Lock()
        self._ensure_directories()

    def path_for(self, object_key: str) -> Path:
        if _OBJECT_KEY.fullmatch(object_key) is None:
            raise DocumentStoreError("The document object identifier is invalid.")
        return self._objects / object_key

    def store_bytes(
        self,
        plaintext: bytes,
        binding: ObjectBinding,
        *,
        register: Callable[[StoredObjectRecord], Any] | None = None,
    ) -> StoredObjectRecord:
        """Encrypt bytes to a new private object and remove it if registration fails."""
        if not plaintext:
            raise DocumentStoreError("An empty document cannot be stored.")
        plaintext_hash = hashlib.sha256(plaintext).digest()
        with self._lock:
            if plaintext_hash in self._plaintext_hashes:
                raise DuplicatePlaintextError("An identical document is already registered.")
            record = self._encrypt_and_promote(plaintext, plaintext_hash, binding)
            try:
                if register is not None:
                    register(record)
            except Exception:
                self.path_for(record.object_key).unlink(missing_ok=True)
                raise DocumentStoreError("Document metadata registration failed.") from None
            self._plaintext_hashes.add(plaintext_hash)
            return record

    def ingest_file(
        self,
        source: Path,
        binding: ObjectBinding,
        *,
        validator: Callable[[Path], Any],
        scanner: Any,
        register: Callable[[StoredObjectRecord], Any] | None = None,
    ) -> StoredObjectRecord:
        """Copy an input to mode-0600 quarantine, validate and scan it, then encrypt it."""
        quarantine = self._quarantine / f".{secrets.token_hex(16)}.tmp"
        try:
            self._write_private_file(quarantine, source.read_bytes())
            validator(quarantine)
            scanner.scan(quarantine)
            return self.store_bytes(quarantine.read_bytes(), binding, register=register)
        except DocumentStoreError:
            raise
        except Exception:
            raise DocumentStoreError("Document ingestion failed.") from None
        finally:
            quarantine.unlink(missing_ok=True)

    def decrypt_bytes(self, record: StoredObjectRecord, binding: ObjectBinding) -> bytes:
        """Verify an object envelope and decrypt it only with its original binding."""
        try:
            payload = self.path_for(record.object_key).read_bytes()
            if hashlib.sha256(payload).digest() != record.ciphertext_sha256:
                raise ValueError
            magic, envelope_version, key_version, nonce = _HEADER.unpack(payload[: _HEADER.size])
            if (
                magic != _MAGIC
                or envelope_version != record.envelope_version
                or key_version != record.key_version
                or nonce != record.nonce
            ):
                raise ValueError
            plaintext = AESGCM(self._keyring.key_for(key_version)).decrypt(
                nonce,
                payload[_HEADER.size :],
                binding.aad(),
            )
            if len(plaintext) != record.byte_size or hashlib.sha256(plaintext).digest() != record.plaintext_sha256:
                raise ValueError
            return plaintext
        except (DocumentStoreError, KeyringError, InvalidTag, OSError, ValueError, struct.error):
            raise DocumentStoreError("The encrypted document object failed integrity validation.") from None

    def cleanup_temporary_files(self) -> None:
        """Remove only controlled temporary files left by an interrupted worker."""
        for directory in (self._objects, self._quarantine):
            for path in directory.glob(".*.tmp"):
                if path.is_file():
                    path.unlink(missing_ok=True)

    def _encrypt_and_promote(
        self,
        plaintext: bytes,
        plaintext_hash: bytes,
        binding: ObjectBinding,
    ) -> StoredObjectRecord:
        key_version, key = self._keyring.active_key()
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, binding.aad())
        envelope = _HEADER.pack(_MAGIC, _FORMAT_VERSION, key_version, nonce) + ciphertext
        object_key = secrets.token_hex(16)
        destination = self.path_for(object_key)
        temporary = self._objects / f".{object_key}.{secrets.token_hex(8)}.tmp"
        try:
            self._write_private_file(temporary, envelope)
            os.replace(temporary, destination)
            self._fsync_directory(self._objects)
        except OSError:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise DocumentStoreError("Encrypted document storage failed.") from None
        return StoredObjectRecord(
            object_key=object_key,
            key_version=key_version,
            envelope_version=_FORMAT_VERSION,
            nonce=nonce,
            plaintext_sha256=plaintext_hash,
            ciphertext_sha256=hashlib.sha256(envelope).digest(),
            byte_size=len(plaintext),
        )

    def _ensure_directories(self) -> None:
        for directory in (self._root, self._objects, self._quarantine):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
            if self._owner is not None:
                os.chown(directory, *self._owner)

    def _write_private_file(self, path: Path, payload: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            if self._owner is not None:
                os.fchown(descriptor, *self._owner)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
