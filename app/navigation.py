"""Authorization-filtered EHF navigation inventories.

The inventory is deliberately data-only: future authentication supplies the
verified group names, while templates and help use this same filtered result.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InternalGroups:
    administrators: str = "EHF-Administrators"
    trustees: str = "EHF-Trustees"


INTERNAL_GROUPS = InternalGroups()


@dataclass(frozen=True, slots=True)
class NavigationEntry:
    key: str
    label: str
    href: str
    help_text: str
    permitted_groups: frozenset[str]


_INTERNAL_INVENTORY = (
    NavigationEntry(
        "overview",
        "Overview",
        "#overview",
        "See the 2026 call and current intake at a glance.",
        frozenset({INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees}),
    ),
    NavigationEntry(
        "applications",
        "Applications",
        "#applications",
        "Review the current application register and missing source observations.",
        frozenset({INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees}),
    ),
    NavigationEntry(
        "reports",
        "Reports",
        "#reports",
        "View aggregate citation reports without changing records.",
        frozenset({INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees}),
    ),
    NavigationEntry(
        "operations",
        "Operations",
        "#operations",
        "Prepare future operational work after authentication is activated.",
        frozenset({INTERNAL_GROUPS.administrators}),
    ),
)


def filtered_inventory(groups: set[str] | frozenset[str]) -> tuple[NavigationEntry, ...]:
    """Return only destinations granted by verified group membership."""
    return tuple(entry for entry in _INTERNAL_INVENTORY if entry.permitted_groups & groups)


def navigation_entries(entries: tuple[NavigationEntry, ...]) -> tuple[NavigationEntry, ...]:
    """Expose the one filtered inventory to the primary navigation renderer."""
    return entries


def help_entries(entries: tuple[NavigationEntry, ...]) -> tuple[NavigationEntry, ...]:
    """Expose the same filtered inventory to the Help renderer."""
    return entries


def internal_authorization_groups() -> tuple[str, str]:
    """Canonical EHF groups shown as informative navigation pills."""
    return (INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees)


def authorization_groups(entries: tuple[NavigationEntry, ...]) -> tuple[str, ...]:
    """Derive visible authorization pills from the same filtered destination inventory."""
    permitted = {group for entry in entries for group in entry.permitted_groups}
    return tuple(group for group in internal_authorization_groups() if group in permitted)
