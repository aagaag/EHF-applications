"""Shared role-filtered shell fragments for protected internal pages."""

from __future__ import annotations

from html import escape

from app.identity import AuthenticatedIdentity
from app.navigation import authorization_groups, filtered_inventory


def primary_navigation(principal: AuthenticatedIdentity) -> str:
    return "".join(
        f'<a class="app-nav-link" href="{escape(entry.href)}">{escape(entry.label)}</a>'
        for entry in filtered_inventory(principal.groups)
    )


def help_navigation(principal: AuthenticatedIdentity) -> str:
    return "".join(
        f'<a class="app-nav-link" href="{escape(entry.href)}">{escape(entry.label)} help</a>'
        for entry in filtered_inventory(principal.groups)
    )


def authorization_pills(principal: AuthenticatedIdentity) -> str:
    groups = authorization_groups(filtered_inventory(principal.groups))
    pills = "".join(
        f'<span class="app-nav-authorization-pill group-pill-{index}">{escape(group)}</span>'
        for index, group in enumerate(groups, start=1)
    )
    return (
        '<div class="app-nav-authorizations" '
        'aria-label="Groups authorized to use EHF Fellowships"><strong>Authorizations:</strong>'
        f'<span class="app-nav-authorization-pills">{pills}</span></div>'
    )


def render_internal_page(template: str, principal: AuthenticatedIdentity) -> str:
    """Filter the static review shell without duplicating its page content."""
    return (
        template.replace("{{PRIMARY_NAVIGATION}}", primary_navigation(principal))
        .replace("{{HELP_NAVIGATION}}", help_navigation(principal))
        .replace("{{AUTHORIZATION_PILLS}}", authorization_pills(principal))
    )
