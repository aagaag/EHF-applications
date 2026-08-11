from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.auth.applicant import (
    ApplicantAuthService,
    CapturingVerificationDelivery,
    InMemoryApplicantAuthRepository,
    invitation_token_hash,
    new_opaque_token,
)


NOW = datetime(2026, 8, 11, 11, 0, tzinfo=UTC)


def _invited_service() -> tuple[
    ApplicantAuthService,
    InMemoryApplicantAuthRepository,
    CapturingVerificationDelivery,
    str,
]:
    repository = InMemoryApplicantAuthRepository()
    delivery = CapturingVerificationDelivery()
    codes = iter(("654321", "123456", "222222"))
    service = ApplicantAuthService(
        repository,
        delivery,
        otp_pepper=b"synthetic-otp-pepper-with-at-least-32-bytes",
        session_pepper=b"synthetic-session-pepper-at-least-32-bytes",
        code_factory=lambda: next(codes),
    )
    token = new_opaque_token()
    repository.add_invitation(
        UUID("20000000-0000-4000-8000-000000000001"),
        invitation_token_hash(token),
        "otp@example.test",
        NOW + timedelta(days=1),
    )
    return service, repository, delivery, token


def test_valid_otp_creates_hashed_session_with_bounded_expiry() -> None:
    """Break caught: a correct code could create an unbounded or cleartext session."""
    service, repository, delivery, token = _invited_service()
    context = service.establish(token, NOW)
    service.request_code(context, NOW)

    session = service.verify_code(context, delivery.messages[-1].code, NOW + timedelta(minutes=1))

    assert session is not None
    assert session.idle_expires_at == NOW + timedelta(minutes=31)
    assert session.absolute_expires_at == NOW + timedelta(hours=24, minutes=1)
    assert session.session_token not in repr(repository)
    assert session.csrf_token not in repr(repository)
    assert service.authenticate(session.session_token, NOW + timedelta(minutes=2)) is not None
    assert service.authenticate(session.session_token, NOW + timedelta(hours=25)) is None


def test_authenticated_activity_extends_idle_expiry_but_not_absolute_expiry() -> None:
    """Break caught: an active applicant session could expire at the original idle deadline."""
    service, _repository, delivery, token = _invited_service()
    context = service.establish(token, NOW)
    service.request_code(context, NOW)
    session = service.verify_code(context, delivery.messages[-1].code, NOW)
    assert session is not None

    active = service.authenticate(session.session_token, NOW + timedelta(minutes=20))
    assert active is not None
    assert active.idle_expires_at == NOW + timedelta(minutes=50)
    assert active.absolute_expires_at == NOW + timedelta(hours=24)
    assert service.authenticate(session.session_token, NOW + timedelta(minutes=40)) is not None
    assert service.authenticate(session.session_token, NOW + timedelta(hours=24)) is None


def test_invalid_expired_reused_and_cross_invitation_codes_are_rejected_neutrally() -> None:
    """Break caught: OTP errors could be reusable, cross-bound, or reveal failure state."""
    service, repository, delivery, token = _invited_service()
    first_context = service.establish(token, NOW)
    service.request_code(first_context, NOW)
    first_code = delivery.messages[-1].code

    assert service.verify_code(first_context, "000000", NOW + timedelta(seconds=1)) is None
    assert service.verify_code(first_context, first_code, NOW + timedelta(minutes=11)) is None

    second_token = new_opaque_token()
    repository.add_invitation(
        UUID("20000000-0000-4000-8000-000000000002"),
        invitation_token_hash(second_token),
        "other@example.test",
        NOW + timedelta(days=1),
    )
    second_context = service.establish(second_token, NOW)
    service.request_code(second_context, NOW)
    second_code = delivery.messages[-1].code
    assert service.verify_code(second_context, first_code, NOW + timedelta(seconds=2)) is None
    session = service.verify_code(second_context, second_code, NOW + timedelta(seconds=3))
    assert session is not None
    assert service.verify_code(second_context, second_code, NOW + timedelta(seconds=4)) is None


def test_five_wrong_attempts_exhaust_the_challenge() -> None:
    """Break caught: brute-force attempts could continue after the configured ceiling."""
    service, _repository, delivery, token = _invited_service()
    context = service.establish(token, NOW)
    service.request_code(context, NOW)
    correct_code = delivery.messages[-1].code

    for attempt in range(5):
        assert service.verify_code(context, f"{attempt:06d}", NOW + timedelta(seconds=attempt)) is None

    assert service.verify_code(context, correct_code, NOW + timedelta(seconds=6)) is None


def test_otp_accepts_exactly_six_ascii_digits() -> None:
    """Break caught: ignored non-ASCII suffixes could make malformed OTP input valid."""
    service, _repository, delivery, token = _invited_service()
    context = service.establish(token, NOW)
    service.request_code(context, NOW)
    correct_code = delivery.messages[-1].code

    assert service.verify_code(context, f"{correct_code}☃", NOW) is None
