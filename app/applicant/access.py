"""Prospective-applicant Entra access requests with reviewer approval."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.applicant.approval import REVIEWER_GROUPS


_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+\Z")


@dataclass(frozen=True, slots=True)
class ApplicantAccessRequest:
    request_id: UUID
    requested_email: str
    requested_display_name: str
    requested_at_utc: datetime
    status: str = "PENDING"
    reviewed_by: str | None = None
    reviewer_group: str | None = None
    reviewed_at_utc: datetime | None = None


class InMemoryApplicantAccessRepository:
    def __init__(self) -> None:
        self._requests: dict[UUID, ApplicantAccessRequest] = {}
        self._entra_applications: dict[UUID, UUID] = {}
        self._application_identities: dict[UUID, UUID] = {}

    def request(self, email: str, display_name: str) -> ApplicantAccessRequest:
        existing = next((
            item for item in self._requests.values()
            if item.requested_email == email and item.status in {"PENDING", "APPROVED"}
        ), None)
        if existing is not None:
            return existing
        request = ApplicantAccessRequest(uuid4(), email, display_name, datetime.now(UTC))
        self._requests[request.request_id] = request
        return request

    def pending(self) -> tuple[ApplicantAccessRequest, ...]:
        return tuple(sorted(
            (item for item in self._requests.values() if item.status == "PENDING"),
            key=lambda item: (item.requested_at_utc, str(item.request_id)),
        ))

    def actionable(self) -> tuple[ApplicantAccessRequest, ...]:
        return tuple(sorted(
            (
                item for item in self._requests.values()
                if item.status in {"PENDING", "APPROVED"}
            ),
            key=lambda item: (item.requested_at_utc, str(item.request_id)),
        ))

    def review(
        self, request_id: UUID, decision: str, actor: str, actor_group: str
    ) -> ApplicantAccessRequest:
        request = self._requests.get(request_id)
        if request is None or request.status != "PENDING":
            raise LookupError("The access request is unavailable.")
        reviewed = replace(
            request, status=decision, reviewed_by=actor,
            reviewer_group=actor_group, reviewed_at_utc=datetime.now(UTC),
        )
        self._requests[request_id] = reviewed
        return reviewed

    def provision(
        self,
        request_id: UUID,
        application_id: UUID,
        entra_object_id: UUID,
        actor: str,
        actor_group: str,
    ) -> ApplicantAccessRequest:
        request = self._requests.get(request_id)
        if request is None or request.status != "APPROVED":
            raise LookupError("The approved access request is unavailable.")
        if self._entra_applications.get(entra_object_id) not in {None, application_id}:
            raise ValueError("The Entra identity is already linked.")
        if self._application_identities.get(application_id) not in {None, entra_object_id}:
            raise ValueError("The application is already linked.")
        provisioned = replace(request, status="PROVISIONED")
        self._requests[request_id] = provisioned
        self._entra_applications[entra_object_id] = application_id
        self._application_identities[application_id] = entra_object_id
        return provisioned

    def application_for_entra(self, entra_object_id: UUID) -> UUID | None:
        return self._entra_applications.get(entra_object_id)


class ApplicantAccessService:
    def __init__(self, repository: object) -> None:
        self._repository = repository

    def request(self, email: str, display_name: str) -> ApplicantAccessRequest:
        normalized_email = email.strip().casefold()
        normalized_name = " ".join(display_name.split())
        if len(normalized_email) > 320 or _EMAIL.fullmatch(normalized_email) is None:
            raise ValueError("Enter a valid email address.")
        if not normalized_name or len(normalized_name) > 300:
            raise ValueError("Enter your name.")
        return self._repository.request(normalized_email, normalized_name)

    def pending(self) -> tuple[ApplicantAccessRequest, ...]:
        return self._repository.pending()

    def actionable(self) -> tuple[ApplicantAccessRequest, ...]:
        return self._repository.actionable()

    def review(
        self, request_id: UUID, *, decision: str, actor: str, actor_group: str
    ) -> ApplicantAccessRequest:
        if actor_group not in REVIEWER_GROUPS or not actor.strip():
            raise PermissionError("Administrator or trustee authorization is required.")
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("The access-request decision is invalid.")
        return self._repository.review(
            request_id, decision, actor.strip(), actor_group
        )

    def provision(
        self,
        request_id: UUID,
        *,
        application_id: UUID,
        entra_object_id: UUID,
        actor: str,
        actor_group: str,
    ) -> ApplicantAccessRequest:
        if actor_group not in REVIEWER_GROUPS or not actor.strip():
            raise PermissionError("Administrator or trustee authorization is required.")
        return self._repository.provision(
            request_id,
            application_id,
            entra_object_id,
            actor.strip(),
            actor_group,
        )
