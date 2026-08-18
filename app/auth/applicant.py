"""Opaque invitation, one-time-code, and applicant-session domain services."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4


NEUTRAL_CODE_MESSAGE = (
    "If the invitation is valid, a code was sent to the registered address."
)
PREAUTH_LIFETIME = timedelta(minutes=20)
OTP_LIFETIME = timedelta(minutes=10)
SESSION_IDLE_LIFETIME = timedelta(minutes=30)
SESSION_ABSOLUTE_LIFETIME = timedelta(hours=24)


def new_opaque_token() -> str:
    """Return a canonical 256-bit URL-safe bearer token."""
    return secrets.token_urlsafe(32)


def invitation_token_hash(token: str) -> bytes:
    """Hash a canonical invitation token without retaining it."""
    return hashlib.sha256(token.encode("ascii", "strict")).digest()


def _canonical_token(token: str) -> bool:
    if len(token) != 43:
        return False
    try:
        decoded = base64.urlsafe_b64decode(token + "=")
    except (ValueError, UnicodeEncodeError):
        return False
    return len(decoded) == 32 and new_token_text(decoded) == token


def new_token_text(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _keyed_hash(token: str, pepper: bytes) -> bytes:
    return hmac.new(pepper, token.encode("ascii", "strict"), hashlib.sha256).digest()


@dataclass(frozen=True, slots=True)
class VerificationDelivery:
    recipient: str
    code: str


class CapturingVerificationDelivery:
    """Non-production delivery sink used by synthetic tests and local development."""

    def __init__(self) -> None:
        self.messages: list[VerificationDelivery] = []

    def deliver(self, recipient: str, code: str) -> None:
        self.messages.append(VerificationDelivery(recipient, code))


@dataclass(slots=True)
class InvitationRecord:
    invitation_id: UUID
    application_id: UUID
    token_hash: bytes
    registered_email: str
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(slots=True)
class PreAuthRecord:
    context_hash: bytes
    invitation_id: UUID | None
    expires_at: datetime
    consumed_at: datetime | None = None


@dataclass(slots=True)
class ChallengeRecord:
    challenge_id: UUID
    context_hash: bytes
    invitation_id: UUID
    code_digest: bytes
    nonce: bytes
    expires_at: datetime
    attempt_count: int = 0
    max_attempts: int = 5
    consumed_at: datetime | None = None


@dataclass(slots=True)
class StoredSession:
    application_id: UUID
    session_hash: bytes
    csrf_hash: bytes
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None
    invitation_id: UUID | None = None
    entra_object_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class NewApplicantSession:
    application_id: UUID
    session_token: str
    csrf_token: str
    idle_expires_at: datetime
    absolute_expires_at: datetime


@dataclass(frozen=True, slots=True)
class ApplicantSessionContext:
    application_id: UUID
    csrf_hash: bytes
    idle_expires_at: datetime
    absolute_expires_at: datetime
    entra_object_id: UUID | None = None


class InMemoryApplicantAuthRepository:
    """Faithful in-memory state boundary for domain and HTTP tests."""

    def __init__(self) -> None:
        self._invitations: dict[bytes, InvitationRecord] = {}
        self._invitations_by_id: dict[UUID, InvitationRecord] = {}
        self._contexts: dict[bytes, PreAuthRecord] = {}
        self._challenges: dict[bytes, ChallengeRecord] = {}
        self._sessions: dict[bytes, StoredSession] = {}
        self._entra_applications: dict[UUID, UUID] = {}
        self._application_identities: dict[UUID, UUID] = {}

    def link_entra_identity(self, entra_object_id: UUID, application_id: UUID) -> None:
        existing_application = self._entra_applications.get(entra_object_id)
        existing_identity = self._application_identities.get(application_id)
        if existing_application not in {None, application_id} or existing_identity not in {
            None,
            entra_object_id,
        }:
            raise ValueError("an Entra identity and application must map one-to-one")
        self._entra_applications[entra_object_id] = application_id
        self._application_identities[application_id] = entra_object_id

    def application_for_entra(self, entra_object_id: UUID) -> UUID | None:
        return self._entra_applications.get(entra_object_id)

    def add_invitation(
        self,
        application_id: UUID,
        token_hash: bytes,
        registered_email: str,
        expires_at: datetime,
        *,
        revoked_at: datetime | None = None,
    ) -> InvitationRecord:
        invitation = InvitationRecord(
            uuid4(), application_id, token_hash, registered_email, expires_at, revoked_at
        )
        self._invitations[token_hash] = invitation
        self._invitations_by_id[invitation.invitation_id] = invitation
        return invitation

    def active_invitation(self, token_hash: bytes, now: datetime) -> InvitationRecord | None:
        record = self._invitations.get(token_hash)
        if record is None or record.revoked_at is not None or record.expires_at <= now:
            return None
        return record

    def put_context(self, record: PreAuthRecord) -> None:
        self._contexts[record.context_hash] = record

    def context(self, context_hash: bytes, now: datetime) -> PreAuthRecord | None:
        record = self._contexts.get(context_hash)
        if record is None or record.consumed_at is not None or record.expires_at <= now:
            return None
        return record

    def invitation_by_id(self, invitation_id: UUID) -> InvitationRecord | None:
        return self._invitations_by_id.get(invitation_id)

    def put_challenge(self, record: ChallengeRecord) -> None:
        prior = self._challenges.get(record.context_hash)
        if prior is not None and prior.consumed_at is None:
            prior.consumed_at = record.expires_at - OTP_LIFETIME
        self._challenges[record.context_hash] = record

    def challenge(self, context_hash: bytes) -> ChallengeRecord | None:
        return self._challenges.get(context_hash)

    def put_session(self, record: StoredSession) -> None:
        self._sessions[record.session_hash] = record

    def session(self, session_hash: bytes, now: datetime) -> StoredSession | None:
        record = self._sessions.get(session_hash)
        if (
            record is None
            or record.revoked_at is not None
            or record.idle_expires_at <= now
            or record.absolute_expires_at <= now
        ):
            return None
        return record


class ApplicantAuthService:
    """Apply neutral invitation and OTP semantics without exposing record existence."""

    def __init__(
        self,
        repository: InMemoryApplicantAuthRepository,
        delivery: CapturingVerificationDelivery,
        *,
        otp_pepper: bytes,
        session_pepper: bytes,
        code_factory: Callable[[], str] | None = None,
    ) -> None:
        if len(otp_pepper) < 32 or len(session_pepper) < 32:
            raise ValueError("applicant authentication peppers must be at least 32 bytes")
        self._repository = repository
        self._delivery = delivery
        self._otp_pepper = otp_pepper
        self._session_pepper = session_pepper
        self._code_factory = code_factory or (lambda: f"{secrets.randbelow(1_000_000):06d}")

    def establish(self, invitation_token: str, now: datetime | None = None) -> str:
        timestamp = _aware_utc(now)
        invitation = None
        if _canonical_token(invitation_token):
            invitation = self._repository.active_invitation(
                invitation_token_hash(invitation_token), timestamp
            )
        raw_context = new_opaque_token()
        self._repository.put_context(
            PreAuthRecord(
                _keyed_hash(raw_context, self._session_pepper),
                invitation.invitation_id if invitation is not None else None,
                timestamp + PREAUTH_LIFETIME,
            )
        )
        return raw_context

    def request_code(self, preauth_token: str, now: datetime | None = None) -> str:
        timestamp = _aware_utc(now)
        context_hash = self._context_hash(preauth_token)
        context = self._repository.context(context_hash, timestamp)
        if context is None or context.invitation_id is None:
            return NEUTRAL_CODE_MESSAGE
        invitation = self._repository.invitation_by_id(context.invitation_id)
        if invitation is None or invitation.revoked_at is not None or invitation.expires_at <= timestamp:
            return NEUTRAL_CODE_MESSAGE
        code = self._code_factory()
        if len(code) != 6 or not code.isascii() or not code.isdecimal():
            raise ValueError("verification-code factory must return six ASCII digits")
        nonce = secrets.token_bytes(32)
        digest = self._verification_digest(code, nonce, invitation.invitation_id)
        self._repository.put_challenge(
            ChallengeRecord(
                uuid4(),
                context_hash,
                invitation.invitation_id,
                digest,
                nonce,
                timestamp + OTP_LIFETIME,
            )
        )
        self._delivery.deliver(invitation.registered_email, code)
        return NEUTRAL_CODE_MESSAGE

    def verify_code(
        self, preauth_token: str, code: str, now: datetime | None = None
    ) -> NewApplicantSession | None:
        timestamp = _aware_utc(now)
        context_hash = self._context_hash(preauth_token)
        context = self._repository.context(context_hash, timestamp)
        challenge = self._repository.challenge(context_hash)
        if (
            context is None
            or context.invitation_id is None
            or challenge is None
            or challenge.invitation_id != context.invitation_id
            or challenge.consumed_at is not None
            or challenge.expires_at <= timestamp
            or challenge.attempt_count >= challenge.max_attempts
        ):
            return None
        supplied = (
            self._verification_digest(code, challenge.nonce, challenge.invitation_id)
            if len(code) == 6 and code.isascii() and code.isdecimal()
            else bytes(32)
        )
        if not hmac.compare_digest(supplied, challenge.code_digest):
            challenge.attempt_count += 1
            return None
        invitation = self._repository.invitation_by_id(challenge.invitation_id)
        if invitation is None or invitation.revoked_at is not None or invitation.expires_at <= timestamp:
            return None
        challenge.consumed_at = timestamp
        context.consumed_at = timestamp
        return self._create_session(invitation, timestamp)

    def establish_entra(
        self, entra_object_id: UUID, now: datetime | None = None
    ) -> NewApplicantSession | None:
        timestamp = _aware_utc(now)
        lookup = getattr(self._repository, "application_for_entra", None)
        application_id = lookup(entra_object_id) if lookup is not None else None
        if application_id is None:
            return None
        return self._create_session_for(
            application_id, timestamp, entra_object_id=entra_object_id
        )

    def _create_session(
        self, invitation: InvitationRecord, timestamp: datetime
    ) -> NewApplicantSession:
        return self._create_session_for(
            invitation.application_id, timestamp, invitation.invitation_id
        )

    def _create_session_for(
        self,
        application_id: UUID,
        timestamp: datetime,
        invitation_id: UUID | None = None,
        entra_object_id: UUID | None = None,
    ) -> NewApplicantSession:
        raw_session = new_opaque_token()
        raw_csrf = new_opaque_token()
        stored = StoredSession(
            application_id,
            _keyed_hash(raw_session, self._session_pepper),
            _keyed_hash(raw_csrf, self._session_pepper),
            timestamp + SESSION_IDLE_LIFETIME,
            timestamp + SESSION_ABSOLUTE_LIFETIME,
            invitation_id=invitation_id,
            entra_object_id=entra_object_id,
        )
        self._repository.put_session(stored)
        return NewApplicantSession(
            stored.application_id,
            raw_session,
            raw_csrf,
            stored.idle_expires_at,
            stored.absolute_expires_at,
        )

    def authenticate(
        self, session_token: str, now: datetime | None = None
    ) -> ApplicantSessionContext | None:
        timestamp = _aware_utc(now)
        if not _canonical_token(session_token):
            return None
        stored = self._repository.session(
            _keyed_hash(session_token, self._session_pepper), timestamp
        )
        if stored is None:
            return None
        stored.idle_expires_at = min(
            timestamp + SESSION_IDLE_LIFETIME,
            stored.absolute_expires_at,
        )
        return ApplicantSessionContext(
            stored.application_id,
            stored.csrf_hash,
            stored.idle_expires_at,
            stored.absolute_expires_at,
            stored.entra_object_id,
        )

    def valid_csrf(self, context: ApplicantSessionContext, csrf_token: str) -> bool:
        if not _canonical_token(csrf_token):
            return False
        return hmac.compare_digest(
            context.csrf_hash,
            _keyed_hash(csrf_token, self._session_pepper),
        )

    def _context_hash(self, token: str) -> bytes:
        if not _canonical_token(token):
            return bytes(32)
        return _keyed_hash(token, self._session_pepper)

    def _verification_digest(self, code: str, nonce: bytes, invitation_id: UUID) -> bytes:
        message = invitation_id.bytes + nonce + code.encode("ascii", "ignore")
        return hmac.new(self._otp_pepper, message, hashlib.sha256).digest()


def _aware_utc(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("authentication timestamps must be timezone-aware")
    return timestamp.astimezone(UTC)
