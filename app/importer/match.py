"""Fail-closed exact reconciliation of parsed applicants to source folders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.importer.normalize import candidate_keys
from app.importer.register import RegisterApplicant


@dataclass(frozen=True, slots=True)
class ApplicantFolderMatch:
    """A single, exact applicant-to-folder proposal."""

    applicant_name: str
    folder_name: str


@dataclass(frozen=True, slots=True)
class MatchException:
    """A reconciliation issue that blocks application creation."""

    code: str
    applicant_name: str | None


@dataclass(frozen=True, slots=True)
class ApplicantMatchResult:
    """All exact matches, or blocking exceptions with no selected match."""

    matches: tuple[ApplicantFolderMatch, ...]
    exceptions: tuple[MatchException, ...]


class ApplicantMatchError(ValueError):
    """Raised when an exact reconciliation contains any blocking exception."""


def match_applicants_to_folders(
    applicants: Sequence[RegisterApplicant],
    folder_names: Sequence[str],
    *,
    reviewed_aliases: Mapping[str, str] | None = None,
) -> ApplicantMatchResult:
    """Propose matches only when one normalized exact folder candidate exists per row."""
    aliases = reviewed_aliases or {}
    folders_by_key: dict[str, set[str]] = {}
    for folder_name in folder_names:
        for key in candidate_keys(folder_name):
            folders_by_key.setdefault(key, set()).add(folder_name)

    provisional: list[ApplicantFolderMatch] = []
    exceptions: list[MatchException] = []
    for applicant in applicants:
        keys = set(candidate_keys(applicant.applicant_name))
        if applicant.applicant_name in aliases:
            keys.update(candidate_keys(aliases[applicant.applicant_name]))
        candidates = {folder for key in keys for folder in folders_by_key.get(key, set())}
        if not candidates:
            exceptions.append(MatchException("no-folder-match", applicant.applicant_name))
        elif len(candidates) > 1:
            exceptions.append(MatchException("ambiguous-folder-match", applicant.applicant_name))
        else:
            provisional.append(ApplicantFolderMatch(applicant.applicant_name, candidates.pop()))

    rows_by_folder: dict[str, list[ApplicantFolderMatch]] = {}
    for proposal in provisional:
        rows_by_folder.setdefault(proposal.folder_name, []).append(proposal)
    for proposals in rows_by_folder.values():
        if len(proposals) > 1:
            exceptions.append(MatchException("cross-row-folder-match", proposals[0].applicant_name))

    consumed_folders = set(rows_by_folder)
    for folder_name in folder_names:
        if folder_name not in consumed_folders:
            exceptions.append(MatchException("unmatched-source-folder", None))

    if exceptions:
        return ApplicantMatchResult((), tuple(exceptions))
    return ApplicantMatchResult(tuple(provisional), ())


def require_exact_matches(result: ApplicantMatchResult) -> tuple[ApplicantFolderMatch, ...]:
    """Return proposed matches only when the entire reconciliation is unambiguous."""
    if result.exceptions:
        codes = ", ".join(exception.code for exception in result.exceptions)
        raise ApplicantMatchError(codes)
    return result.matches
