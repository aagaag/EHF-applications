"""Deterministic exact-key normalization for reviewed applicant identity matching."""

from __future__ import annotations

import re
import unicodedata


_TRANSLITERATIONS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def candidate_keys(value: str) -> frozenset[str]:
    """Return explicit spelling and word-order variants, never a fuzzy similarity score."""
    keys: set[str] = set()
    for form in (value.casefold(), value.casefold().translate(_TRANSLITERATIONS)):
        normalized = unicodedata.normalize("NFKD", form)
        tokens = re.findall(r"[a-z0-9]+", "".join(
            character for character in normalized if not unicodedata.combining(character)
        ))
        if tokens:
            keys.add("".join(tokens))
            keys.add("".join(reversed(tokens)))
    return frozenset(keys)
