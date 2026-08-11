from __future__ import annotations

import pytest

from app.applicant.contribution import ContributionError, validate_contribution


@pytest.mark.parametrize("length", [1, 999, 1000])
def test_contribution_accepts_every_nonempty_value_through_one_thousand_code_points(
    length: int,
) -> None:
    """Break caught: a valid short or boundary-length contribution could be rejected."""
    value = "🧬" * length

    assert len(validate_contribution(value)) == length


def test_contribution_rejects_empty_and_one_thousand_one_without_shortening() -> None:
    """Break caught: the service could accept empty text or silently truncate pasted content."""
    for value in ("", " " * 10, "x" * 1001):
        with pytest.raises(ContributionError) as raised:
            validate_contribution(value)
        assert raised.value.original == value


def test_contribution_normalizes_line_endings_and_unicode_but_preserves_words() -> None:
    """Break caught: platform line endings could change counts or content unexpectedly."""
    value = "My contribution\r\ncombined e\u0301vidence."

    assert validate_contribution(value) == "My contribution\ncombined évidence."
