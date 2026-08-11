from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.auth.rate_limit import InMemoryRateLimiter, RateLimitPolicy


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def test_rate_limit_blocks_only_after_five_attempts_and_resets_next_window() -> None:
    """Break caught: the limiter could allow a sixth attempt or never recover."""
    limiter = InMemoryRateLimiter(RateLimitPolicy(limit=5, window=timedelta(minutes=10)))

    assert [limiter.allow("INVITATION", "alpha", NOW) for _ in range(6)] == [
        True,
        True,
        True,
        True,
        True,
        False,
    ]
    assert limiter.allow("INVITATION", "alpha", NOW + timedelta(minutes=10)) is True


def test_rate_limit_isolates_subjects_scopes_and_supports_global_ceiling() -> None:
    """Break caught: one applicant could block another or bypass a global scope."""
    limiter = InMemoryRateLimiter(RateLimitPolicy(limit=1, window=timedelta(minutes=1)))

    assert limiter.allow("INVITATION", "alpha", NOW) is True
    assert limiter.allow("INVITATION", "alpha", NOW) is False
    assert limiter.allow("INVITATION", "beta", NOW) is True
    assert limiter.allow("IP", "alpha", NOW) is True
    assert limiter.allow("GLOBAL", "all", NOW) is True
    assert limiter.allow("GLOBAL", "all", NOW) is False
