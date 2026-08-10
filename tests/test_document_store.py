"""Application-encrypted document-object store tests."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from app.documents.keys import load_keyring
from app.documents.store import (
    DocumentStoreError,
    DuplicatePlaintextError,
    EncryptedObjectStore,
    ObjectBinding,
)


def write_keyring(path: Path, *, active: int, keys: dict[int, bytes]) -> None:
    path.write_text(
        json.dumps(
            {
                "active_key_version": active,
                "keys": {str(version): base64.b64encode(key).decode("ascii") for version, key in keys.items()},
            }
        ),
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def binding(number: int) -> ObjectBinding:
    return ObjectBinding(
        application_id=UUID(f"00000000-0000-0000-0000-0000000000{number:02d}"),
        document_id=UUID(f"10000000-0000-0000-0000-0000000000{number:02d}"),
        version_id=UUID(f"20000000-0000-0000-0000-0000000000{number:02d}"),
        object_id=UUID(f"30000000-0000-0000-0000-0000000000{number:02d}"),
    )


def store(tmp_path: Path) -> EncryptedObjectStore:
    credential = tmp_path / "keyring.json"
    write_keyring(credential, active=1, keys={1: bytes(range(32))})
    return EncryptedObjectStore(tmp_path / "objects", load_keyring(credential))


def test_round_trip_encrypts_with_binding_specific_aad(tmp_path: Path) -> None:
    """Break caught: encrypted bytes could be recoverable without their document binding."""
    object_store = store(tmp_path)
    record = object_store.store_bytes(b"synthetic confidential bytes", binding(1))

    assert object_store.decrypt_bytes(record, binding(1)) == b"synthetic confidential bytes"
    with pytest.raises(DocumentStoreError):
        object_store.decrypt_bytes(record, binding(2))


def test_each_object_uses_a_fresh_nonce(tmp_path: Path) -> None:
    """Break caught: AES-GCM nonce reuse could make two encrypted objects unsafe."""
    object_store = store(tmp_path)
    first = object_store.store_bytes(b"first synthetic PDF", binding(1))
    second = object_store.store_bytes(b"second synthetic PDF", binding(2))

    assert first.nonce != second.nonce
    assert first.ciphertext_sha256 != second.ciphertext_sha256


def test_rotated_keyring_reads_old_objects_and_writes_new_version(tmp_path: Path) -> None:
    """Break caught: rotating an active key could make existing encrypted documents unreadable."""
    credential = tmp_path / "keyring.json"
    first_key = bytes(range(32))
    second_key = bytes(reversed(range(32)))
    write_keyring(credential, active=1, keys={1: first_key})
    old_store = EncryptedObjectStore(tmp_path / "objects", load_keyring(credential))
    old_record = old_store.store_bytes(b"old document", binding(1))

    write_keyring(credential, active=2, keys={1: first_key, 2: second_key})
    rotated_store = EncryptedObjectStore(tmp_path / "objects", load_keyring(credential))
    new_record = rotated_store.store_bytes(b"new document", binding(2))

    assert old_record.key_version == 1
    assert new_record.key_version == 2
    assert rotated_store.decrypt_bytes(old_record, binding(1)) == b"old document"
    assert rotated_store.decrypt_bytes(new_record, binding(2)) == b"new document"


def test_missing_retired_key_is_a_redacted_store_failure(tmp_path: Path) -> None:
    """Break caught: a lost retired key could leak keyring details or decrypt unpredictably."""
    credential = tmp_path / "keyring.json"
    first_key = bytes(range(32))
    second_key = bytes(reversed(range(32)))
    write_keyring(credential, active=1, keys={1: first_key})
    old_store = EncryptedObjectStore(tmp_path / "objects", load_keyring(credential))
    record = old_store.store_bytes(b"retired key document", binding(1))
    write_keyring(credential, active=2, keys={2: second_key})
    replacement_store = EncryptedObjectStore(tmp_path / "objects", load_keyring(credential))

    with pytest.raises(DocumentStoreError):
        replacement_store.decrypt_bytes(record, binding(1))


@pytest.mark.parametrize("mutation", ["tamper", "truncate"])
def test_tampered_or_truncated_ciphertext_is_rejected(tmp_path: Path, mutation: str) -> None:
    """Break caught: corrupted encrypted-object bytes could be accepted as a document."""
    object_store = store(tmp_path)
    record = object_store.store_bytes(b"encrypted source", binding(1))
    path = object_store.path_for(record.object_key)
    payload = path.read_bytes()
    path.write_bytes(payload[:-1] if mutation == "truncate" else payload[:-1] + b"x")

    with pytest.raises(DocumentStoreError):
        object_store.decrypt_bytes(record, binding(1))


def test_wrong_object_substitution_is_rejected_by_aad(tmp_path: Path) -> None:
    """Break caught: one valid ciphertext could be substituted for another document object."""
    object_store = store(tmp_path)
    first = object_store.store_bytes(b"first encrypted source", binding(1))
    second = object_store.store_bytes(b"second encrypted source", binding(2))

    with pytest.raises(DocumentStoreError):
        object_store.decrypt_bytes(replace(first, object_key=second.object_key), binding(1))


def test_duplicate_plaintext_hash_is_rejected_before_a_second_object_is_promoted(tmp_path: Path) -> None:
    """Break caught: duplicate plaintext could create unnecessary encrypted copies."""
    object_store = store(tmp_path)
    object_store.store_bytes(b"same source", binding(1))

    with pytest.raises(DuplicatePlaintextError):
        object_store.store_bytes(b"same source", binding(2))
    assert len(list((tmp_path / "objects" / "o").iterdir())) == 1


def test_metadata_failure_removes_only_the_unregistered_new_object(tmp_path: Path) -> None:
    """Break caught: a metadata failure could leave an orphaned encrypted object behind."""
    object_store = store(tmp_path)
    existing = object_store.store_bytes(b"already registered", binding(1))

    def reject_metadata(_record: object) -> None:
        raise RuntimeError("synthetic database failure")

    with pytest.raises(DocumentStoreError):
        object_store.store_bytes(b"not registered", binding(2), register=reject_metadata)

    assert object_store.path_for(existing.object_key).exists()
    assert len(list((tmp_path / "objects" / "o").iterdir())) == 1


def test_promotion_leaves_no_temporary_file_and_cleanup_removes_crash_leftovers(tmp_path: Path) -> None:
    """Break caught: a crash could expose or accumulate temporary encrypted-object files."""
    object_store = store(tmp_path)
    record = object_store.store_bytes(b"atomically promoted", binding(1))

    assert object_store.path_for(record.object_key).exists()
    assert not list((tmp_path / "objects" / "o").glob("*.tmp"))
    orphan = tmp_path / "objects" / "o" / ".interrupted.tmp"
    orphan.write_bytes(b"partial")
    object_store.cleanup_temporary_files()
    assert not orphan.exists()
