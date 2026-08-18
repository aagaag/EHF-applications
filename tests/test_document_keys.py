from __future__ import annotations

from app.documents.keys import _is_safe_posix_credential_mode


def test_systemd_credential_modes_are_accepted_without_allowing_public_read() -> None:
    """Break caught: systemd mounts service credentials as root-readable 0440 files."""
    for mode in (0o400, 0o440, 0o600, 0o640):
        assert _is_safe_posix_credential_mode(mode)
    for mode in (0o444, 0o644, 0o660, 0o700):
        assert not _is_safe_posix_credential_mode(mode)
