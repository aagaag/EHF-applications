"""Validation for the required scientific-contribution statement."""

from __future__ import annotations

import unicodedata


class ContributionError(ValueError):
    def __init__(self, message: str, original: str) -> None:
        super().__init__(message)
        self.original = original


def validate_contribution(value: str) -> str:
    if not isinstance(value, str):
        raise ContributionError("The scientific contribution must be text.", value)
    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    if not normalized.strip():
        raise ContributionError("The scientific contribution is required.", value)
    if len(normalized) > 1000:
        raise ContributionError("The scientific contribution is limited to 1,000 characters.", value)
    return normalized
