"""Administrator-bound synthetic applicant workspace creation."""

from __future__ import annotations

from typing import Protocol

from app.auth.applicant import NewApplicantSession
from app.navigation import INTERNAL_GROUPS


class SyntheticApplicantWorkspaceRepository(Protocol):
    def create(self, actor: str, actor_group: str) -> NewApplicantSession: ...


class SyntheticApplicantWorkspaceService:
    """Authorize synthetic workspaces without accepting browser-selected records."""

    def __init__(self, repository: SyntheticApplicantWorkspaceRepository) -> None:
        self._repository = repository

    def create(self, actor: str, actor_group: str) -> NewApplicantSession:
        actor_identity = actor.strip()
        if actor_group != INTERNAL_GROUPS.administrators or not actor_identity:
            raise PermissionError("Administrator authorization is required.")
        return self._repository.create(actor_identity, actor_group)
