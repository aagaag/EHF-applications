from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from uuid import UUID

import pytest

from app.applicant.sql_pilot import ApplicantSqlSessionScope, SqlEntraApplicantAuthRepository
from app.applicant.synthetic import SyntheticApplicantWorkspaceService
from app.auth.applicant import (
    ApplicantAuthService,
    CapturingVerificationDelivery,
    InMemoryApplicantAuthRepository,
    NewApplicantSession,
    StoredSession,
    new_opaque_token,
)
from app.navigation import INTERNAL_GROUPS


APPLICATION = UUID("b1000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
PEPPER = b"synthetic-workspace-session-pepper-at-least-32-bytes"


class CapturingSyntheticRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def create(self, actor: str, actor_group: str) -> NewApplicantSession:
        self.calls.append((actor, actor_group))
        return NewApplicantSession(
            APPLICATION,
            "a" * 43,
            "b" * 43,
            NOW + timedelta(minutes=30),
            NOW + timedelta(hours=24),
        )


class Connection:
    def __init__(self, rows: list[object | None]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0

    def execute(self, statement: str, *arguments: object) -> "Connection":
        self.calls.append((statement, arguments))
        return self

    def fetchone(self) -> object | None:
        return self.rows.pop(0)

    def commit(self) -> None:
        self.commits += 1


def _connections(connection: Connection):
    @contextmanager
    def factory():
        yield connection

    return factory


def test_workspace_creation_binds_the_exact_administrator_identity() -> None:
    """Break caught: a synthetic workspace could be created for an unverified group or actor."""
    repository = CapturingSyntheticRepository()
    service = SyntheticApplicantWorkspaceService(repository)

    session = service.create("  cloudflare:administrator  ", INTERNAL_GROUPS.administrators)

    assert session.application_id == APPLICATION
    assert repository.calls == [("cloudflare:administrator", INTERNAL_GROUPS.administrators)]
    for actor, group in (("", INTERNAL_GROUPS.administrators), ("cloudflare:trustee", INTERNAL_GROUPS.trustees)):
        with pytest.raises(PermissionError):
            service.create(actor, group)
    assert repository.calls == [("cloudflare:administrator", INTERNAL_GROUPS.administrators)]


def test_sql_creation_uses_server_derived_tokens_and_only_the_returned_application() -> None:
    """Break caught: browser-controlled application IDs or reusable plaintext tokens could reach SQL."""
    connection = Connection([(APPLICATION,)])
    repository = SqlEntraApplicantAuthRepository(
        _connections(connection), ApplicantSqlSessionScope(), PEPPER
    )

    session = repository.create("cloudflare:administrator", INTERNAL_GROUPS.administrators)

    statement, arguments = connection.calls[0]
    assert "EXEC dbo.CreateSyntheticApplicantWorkspace" in statement
    assert len(arguments) == 6
    assert arguments[:2] == ("cloudflare:administrator", INTERNAL_GROUPS.administrators)
    assert arguments[2] != session.session_token
    assert arguments[3] != session.csrf_token
    assert isinstance(arguments[2], bytes) and len(arguments[2]) == 32
    assert isinstance(arguments[3], bytes) and len(arguments[3]) == 32
    assert arguments[2] == hmac.new(
        PEPPER, session.session_token.encode("ascii"), hashlib.sha256
    ).digest()
    assert arguments[3] == hmac.new(
        PEPPER, session.csrf_token.encode("ascii"), hashlib.sha256
    ).digest()
    assert session.application_id == APPLICATION
    assert connection.commits == 1


@pytest.mark.parametrize(
    ("invitation_id", "entra_object_id", "synthetic_actor_identity"),
    (
        (UUID("b2000000-0000-4000-8000-000000000001"), None, None),
        (None, UUID("b3000000-0000-4000-8000-000000000001"), None),
        (None, None, "cloudflare:administrator"),
    ),
)
def test_session_sources_are_exclusive_and_each_valid_source_is_retained(
    invitation_id: UUID | None,
    entra_object_id: UUID | None,
    synthetic_actor_identity: str | None,
) -> None:
    """Break caught: a session could combine invitation, Entra, or administrator authority."""
    stored = StoredSession(
        APPLICATION,
        bytes(range(32)),
        bytes(reversed(range(32))),
        NOW + timedelta(minutes=30),
        NOW + timedelta(hours=24),
        invitation_id=invitation_id,
        entra_object_id=entra_object_id,
        synthetic_actor_identity=synthetic_actor_identity,
    )

    assert (stored.invitation_id, stored.entra_object_id, stored.synthetic_actor_identity) == (
        invitation_id,
        entra_object_id,
        synthetic_actor_identity,
    )


@pytest.mark.parametrize(
    ("invitation_id", "entra_object_id", "synthetic_actor_identity"),
    (
        (None, None, None),
        (UUID("b2000000-0000-4000-8000-000000000001"), UUID("b3000000-0000-4000-8000-000000000001"), None),
        (UUID("b2000000-0000-4000-8000-000000000001"), None, "cloudflare:administrator"),
        (None, UUID("b3000000-0000-4000-8000-000000000001"), "cloudflare:administrator"),
    ),
)
def test_session_sources_reject_missing_or_combined_authority(
    invitation_id: UUID | None,
    entra_object_id: UUID | None,
    synthetic_actor_identity: str | None,
) -> None:
    """Break caught: corrupted session rows could bypass the one-source authorization rule."""
    with pytest.raises(ValueError, match="exactly one authentication source"):
        StoredSession(
            APPLICATION,
            bytes(range(32)),
            bytes(reversed(range(32))),
            NOW + timedelta(minutes=30),
            NOW + timedelta(hours=24),
            invitation_id=invitation_id,
            entra_object_id=entra_object_id,
            synthetic_actor_identity=synthetic_actor_identity,
        )


def test_closed_synthetic_workspace_fails_closed_at_session_lookup() -> None:
    """Break caught: closing a synthetic workspace could leave its browser session usable."""
    connection = Connection([None])
    scope = ApplicantSqlSessionScope()
    scope.bind(bytes(range(32)))
    repository = SqlEntraApplicantAuthRepository(_connections(connection), scope, PEPPER)

    session = repository.session(bytes(range(32)), NOW)

    assert session is None
    assert scope.current() is None
    statement, _arguments = connection.calls[0]
    assert "EXEC dbo.GetApplicantSessionV19" in statement


def test_malformed_session_sources_fail_closed_at_sql_lookup() -> None:
    """Break caught: a malformed SQL row could become an applicant session without one authority."""
    connection = Connection(
        [
            (
                APPLICATION,
                bytes(reversed(range(32))),
                NOW + timedelta(minutes=30),
                NOW + timedelta(hours=24),
                None,
                None,
                None,
            )
        ]
    )
    scope = ApplicantSqlSessionScope()
    repository = SqlEntraApplicantAuthRepository(_connections(connection), scope, PEPPER)

    assert repository.session(bytes(range(32)), NOW) is None
    assert scope.current() is None


def test_synthetic_session_lookup_retains_the_database_bound_actor_identity() -> None:
    """Break caught: synthetic session lookup could discard the administrator binding returned by SQL."""
    connection = Connection(
        [
            (
                APPLICATION,
                bytes(reversed(range(32))),
                NOW + timedelta(minutes=30),
                NOW + timedelta(hours=24),
                None,
                None,
                "cloudflare:administrator",
            )
        ]
    )
    repository = SqlEntraApplicantAuthRepository(
        _connections(connection), ApplicantSqlSessionScope(), PEPPER
    )

    session = repository.session(bytes(range(32)), NOW)

    assert session is not None
    assert session.application_id == APPLICATION
    assert session.synthetic_actor_identity == "cloudflare:administrator"
    assert session.invitation_id is None
    assert session.entra_object_id is None


def test_authenticated_context_exposes_the_synthetic_actor_identity() -> None:
    """Break caught: routes could not distinguish a synthetic session from an invitation session."""
    repository = InMemoryApplicantAuthRepository()
    service = ApplicantAuthService(
        repository,
        CapturingVerificationDelivery(),
        otp_pepper=b"synthetic-workspace-otp-pepper-at-least-32-bytes",
        session_pepper=PEPPER,
    )
    raw_session = new_opaque_token()
    repository.put_session(
        StoredSession(
            APPLICATION,
            hmac.new(PEPPER, raw_session.encode("ascii"), hashlib.sha256).digest(),
            bytes(reversed(range(32))),
            NOW + timedelta(minutes=30),
            NOW + timedelta(hours=24),
            synthetic_actor_identity="cloudflare:administrator",
        )
    )

    context = service.authenticate(raw_session, NOW)

    assert context is not None
    assert context.synthetic_actor_identity == "cloudflare:administrator"
    assert context.entra_object_id is None
