"""Bounded in-process rate limiter used in addition to edge and SQL controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    limit: int
    window: timedelta

    def __post_init__(self) -> None:
        if self.limit < 1 or not timedelta(seconds=1) <= self.window <= timedelta(days=1):
            raise ValueError("rate-limit policy is outside the supported bounds")


@dataclass(slots=True)
class _Bucket:
    started_at: datetime
    count: int


class InMemoryRateLimiter:
    def __init__(self, policy: RateLimitPolicy) -> None:
        self._policy = policy
        self._buckets: dict[tuple[str, str], _Bucket] = {}

    def allow(self, scope: str, subject: str, now: datetime) -> bool:
        if len(self._buckets) >= 10_000:
            self._buckets = {
                key: bucket
                for key, bucket in self._buckets.items()
                if now < bucket.started_at + self._policy.window
            }
        key = (scope, subject)
        bucket = self._buckets.get(key)
        if bucket is None or now >= bucket.started_at + self._policy.window:
            self._buckets[key] = _Bucket(now, 1)
            return True
        if bucket.count >= self._policy.limit:
            return False
        bucket.count += 1
        return True
