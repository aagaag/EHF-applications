"""Conservative bibliographic matching used before an audited promotion."""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def normalized_title(value: str) -> str:
    """Normalize harmless citation-style differences without weakening matching."""
    text = value.casefold().replace("versus", "vs")
    text = re.sub(r"\bvs\.?\b", "vs", text)
    return " ".join(re.findall(r"[\w]+", text))


def matches_verified_candidate(
    reported_title: str,
    candidate_title: str,
    *,
    reported_year: int | None,
    candidate_online_year: int | None = None,
    candidate_issue_year: int | None = None,
) -> bool:
    """Return whether a candidate clears the limited formatting/year reconciliation rules.

    This deliberately does not identify a work on title similarity alone.  It is
    used after DOI and author checks have identified the candidate; its role is
    to avoid rejecting the same work merely because one source expands ``vs.``
    or records the online-first rather than issue year.
    """
    reported = normalized_title(reported_title)
    candidate = normalized_title(candidate_title)
    if not reported or not candidate:
        return False
    title_match = reported == candidate or SequenceMatcher(
        None, reported, candidate
    ).ratio() >= 0.92
    if not title_match:
        return False
    if reported_year is None:
        return True
    return reported_year in {candidate_online_year, candidate_issue_year}
