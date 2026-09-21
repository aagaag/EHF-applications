from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from pypdf import PdfReader, PdfWriter

from app.documents.keys import load_keyring
from app.documents.store import EncryptedObjectStore, ObjectBinding
from app.importer.review_artifacts import (
    ReviewArtifactImportError,
    ReviewArtifactSegment,
    load_review_artifact_manifest,
    run_review_artifact_import,
    _matches_provenance,
)
from app.importer.run_review_artifacts import _service_owner


ROOT = Path(__file__).resolve().parents[1]


APPLICATION = "a1000000-0000-4000-8000-000000000001"
VERSION = "a1000000-0000-4000-8000-000000000002"


def _pdf(widths: tuple[int, ...] = (101, 202), *, metadata: dict[str, str] | None = None) -> bytes:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=100)
    if metadata:
        writer.add_metadata(metadata)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def _manifest(relative_path: str, payload: bytes, **overrides: object) -> bytes:
    segment = {
        "sourceVersionId": VERSION,
        "sourceSha256": hashlib.sha256(payload).hexdigest(),
        "relativePath": relative_path,
        "firstPage": 1,
        "lastPage": 1,
    }
    segment.update(overrides)
    return json.dumps({
        "version": 1,
        "reviewedBy": "internal-reviewer",
        "artifacts": [{
            "applicationId": APPLICATION,
            "category": "APPLICATION",
            "segments": [segment],
        }],
    }).encode()


def test_manifest_plan_validates_hash_bounds_and_produces_sanitized_pdf(tmp_path: Path) -> None:
    """Break caught: a reviewed manifest could silently point at changed pages or retain metadata."""
    payload = _pdf(metadata={"/Author": "Applicant"})
    source = tmp_path / "source.pdf"
    source.write_bytes(payload)

    result = run_review_artifact_import(
        _manifest("source.pdf", payload), source_root=tmp_path, apply=False
    )

    assert result.mode == "PLAN_ONLY"
    assert result.application_count == 1 and result.artifact_count == 1
    reader = PdfReader(io.BytesIO(result.prepared[0].payload), strict=True)
    assert len(reader.pages) == 1
    assert float(reader.pages[0].mediabox.width) == 101
    assert reader.metadata.author == "Ernst Hadorn Foundation"
    assert "Applicant" not in str(reader.metadata)


@pytest.mark.parametrize(
    "relative_path, overrides, message",
    (
        ("../outside.pdf", {}, "inside"),
        ("source.pdf", {"sourceSha256": "0" * 64}, "hash"),
        ("source.pdf", {"firstPage": 0}, "page"),
        ("source.pdf", {"lastPage": 3}, "unavailable"),
    ),
)
def test_manifest_rejects_unsafe_paths_stale_hashes_and_invalid_ranges(
    tmp_path: Path, relative_path: str, overrides: dict[str, object], message: str
) -> None:
    """Break caught: path traversal or stale page evidence could enter an artifact."""
    payload = _pdf()
    (tmp_path / "source.pdf").write_bytes(payload)
    with pytest.raises(ReviewArtifactImportError, match=message):
        run_review_artifact_import(
            _manifest(relative_path, payload, **overrides),
            source_root=tmp_path,
            apply=False,
        )


def test_manifest_rejects_recommendation_pages(tmp_path: Path) -> None:
    """Break caught: recommendation material could be copied into reviewer action PDFs."""
    payload = _pdf(metadata={"/Subject": "Letter of recommendation"})
    (tmp_path / "source.pdf").write_bytes(payload)
    with pytest.raises(ReviewArtifactImportError, match="recommendation"):
        run_review_artifact_import(
            _manifest("source.pdf", payload), source_root=tmp_path, apply=False
        )


class _Repository:
    def __init__(self, source: bytes, store: EncryptedObjectStore):
        self.source = source
        self.store = store
        self.applied: dict[tuple[UUID, str], tuple[bytes, object, ObjectBinding]] = {}
        self.fail = False

    def source_pdf(self, application_id: UUID, version_id: UUID, expected_sha256: bytes) -> bytes:
        assert application_id == UUID(APPLICATION) and version_id == UUID(VERSION)
        assert hashlib.sha256(self.source).digest() == expected_sha256
        return self.source

    def apply(self, prepared):  # type: ignore[no-untyped-def]
        snapshot = dict(self.applied)
        try:
            for artifact in prepared:
                key = (artifact.application_id, artifact.category)
                digest = hashlib.sha256(artifact.payload).digest()
                if key in self.applied and self.applied[key][0] == digest:
                    continue
                binding = ObjectBinding(
                    artifact.application_id,
                    UUID("a1000000-0000-4000-8000-000000000010"),
                    UUID("a1000000-0000-4000-8000-000000000011"),
                    UUID("a1000000-0000-4000-8000-000000000012"),
                )
                record = self.store.store_bytes(artifact.payload, binding)
                self.applied[key] = (digest, record, binding)
                if self.fail:
                    raise RuntimeError("synthetic rollback")
        except Exception:
            self.applied = snapshot
            raise
        return len(self.applied) - len(snapshot)


def test_apply_is_encrypted_idempotent_and_rolls_back_repository_state(tmp_path: Path) -> None:
    """Break caught: retries could duplicate artifacts or partial failures could activate half a manifest."""
    payload = _pdf()
    source = tmp_path / "source.pdf"
    source.write_bytes(payload)
    key_path = tmp_path / "keys.json"
    key_path.write_text(json.dumps({
        "active_key_version": 1,
        "keys": {"1": base64.b64encode(bytes(range(32))).decode()},
    }))
    os.chmod(key_path, 0o600)
    store = EncryptedObjectStore(tmp_path / "objects", load_keyring(key_path))
    repository = _Repository(payload, store)
    manifest = load_review_artifact_manifest(_manifest("source.pdf", payload))

    first = run_review_artifact_import(
        _manifest("source.pdf", payload), source_root=tmp_path,
        apply=True, repository=repository,
    )
    second = run_review_artifact_import(
        _manifest("source.pdf", payload), source_root=tmp_path,
        apply=True, repository=repository,
    )

    assert first.applied_count == 1 and second.applied_count == 0
    _digest, record, binding = next(iter(repository.applied.values()))
    assert store.decrypt_bytes(record, binding) == first.prepared[0].payload
    repository.fail = True
    changed = json.loads(_manifest("source.pdf", payload))
    changed["artifacts"][0]["category"] = "CURRICULUM"
    with pytest.raises(RuntimeError, match="rollback"):
        run_review_artifact_import(
            json.dumps(changed).encode(), source_root=tmp_path,
            apply=True, repository=repository,
        )
    assert len(repository.applied) == 1
    assert manifest.artifacts[0].category == "APPLICATION"


def test_production_verifier_uses_the_root_owned_admin_credential_and_safety_gates() -> None:
    source = (ROOT / "scripts" / "verify-review-artifacts-2026.ps1").read_text(
        encoding="utf-8"
    )

    for expected in (
        "EHF_INVITATIONS_ENABLED=false",
        "EHF_PRODUCTION_MAIL_ENABLED=false",
        "/etc/ehf/sql-admin-password",
        "details.st_uid != 0",
        "stat.S_IMODE(details.st_mode) != 0o600",
        "sudo -n /bin/sh -s",
        "APPLICATION",
        "CURRICULUM",
        "PUBLICATIONS",
    ):
        assert expected in source
    assert "connect(Settings.from_environment())" not in source
    assert "'CURRICULUM': (35, 35)" in source


def test_release_contains_review_artifact_import_modules() -> None:
    source = (ROOT / "infra" / "install-ehf.py").read_text(encoding="utf-8")

    assert '"app/importer/review_artifacts.py"' in source
    assert '"app/importer/run_review_artifacts.py"' in source


def test_idempotency_requires_the_same_ordered_source_provenance() -> None:
    segment = ReviewArtifactSegment(UUID(VERSION), bytes.fromhex("11" * 32), "source.pdf", 2, 3)
    same = [(UUID(VERSION), 1, 2, 3, bytes.fromhex("11" * 32))]
    changed_range = [(UUID(VERSION), 1, 1, 3, bytes.fromhex("11" * 32))]

    assert _matches_provenance(same, (segment,))
    assert not _matches_provenance(changed_range, (segment,))
    assert not _matches_provenance([], (segment,))


def test_private_review_artifact_manifests_are_ignored_by_git() -> None:
    source = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "review-artifact-manifest*.json" in source
    assert "ehf-review-artifacts*.json" in source


def test_database_sources_allow_legacy_unreviewed_but_not_confidential_material() -> None:
    source = (ROOT / "app" / "importer" / "review_artifacts.py").read_text(encoding="utf-8")

    assert "version_row.Classification IN ('UNREVIEWED','APPLICANT_VISIBLE')" in source
    assert "CONFIDENTIAL_RECOMMENDATION" not in source


def test_root_mediated_import_assigns_objects_to_the_runtime_service_account() -> None:
    assert _service_owner(
        lambda name: SimpleNamespace(pw_uid=410) if name == "ehf" else None,
        lambda name: SimpleNamespace(gr_gid=420) if name == "ehf" else None,
    ) == (410, 420)
