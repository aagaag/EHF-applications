"""Reviewer-only approval state for applicant-proposed changes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID
from typing import Any

from app.applicant.finalize import FinalConfirmation
from app.navigation import INTERNAL_GROUPS


REVIEWER_GROUPS = frozenset(
    {INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees}
)


@dataclass(frozen=True, slots=True)
class ApplicantSubmissionReview:
    confirmation_id: UUID
    application_id: UUID
    submitted_at_utc: datetime
    status: str = "PENDING"
    reviewed_by: str | None = None
    reviewed_at_utc: datetime | None = None


@dataclass(frozen=True, slots=True)
class ApplicantDocumentReview:
    submission_id: UUID
    application_id: UUID
    slot_id: UUID
    version_id: UUID
    display_name: str
    submitted_at_utc: datetime
    status: str = "PENDING"
    reviewed_by: str | None = None
    reviewed_at_utc: datetime | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ApplicantSubmissionBundle:
    confirmation_id: UUID
    application_id: UUID
    baseline: dict[str, Any]
    manifest: dict[str, Any]
    drafts: dict[str, dict[str, Any]]


class ApplicantApprovalService:
    """In-memory implementation used by domain and HTTP tests."""

    def __init__(self) -> None:
        self._reviews: dict[UUID, ApplicantSubmissionReview] = {}
        self._document_reviews: dict[UUID, ApplicantDocumentReview] = {}

    def queue(self, confirmation: FinalConfirmation) -> ApplicantSubmissionReview:
        review = self._reviews.get(confirmation.confirmation_id)
        if review is None:
            review = ApplicantSubmissionReview(
                confirmation.confirmation_id,
                confirmation.application_id,
                confirmation.confirmed_at_utc,
            )
            self._reviews[confirmation.confirmation_id] = review
        return review

    def pending(self) -> tuple[ApplicantSubmissionReview, ...]:
        return tuple(
            sorted(
                (item for item in self._reviews.values() if item.status == "PENDING"),
                key=lambda item: (item.submitted_at_utc, str(item.confirmation_id)),
            )
        )

    def detail(self, confirmation_id: UUID) -> ApplicantSubmissionBundle:
        review = self._reviews.get(confirmation_id)
        if review is None:
            raise LookupError("The applicant submission is unavailable.")
        return ApplicantSubmissionBundle(
            confirmation_id, review.application_id, {}, {}, {}
        )

    def approve(
        self, confirmation_id: UUID, *, actor: str, actor_group: str
    ) -> ApplicantSubmissionReview:
        if actor_group not in REVIEWER_GROUPS or not actor.strip():
            raise PermissionError("Administrator or trustee authorization is required.")
        review = self._reviews.get(confirmation_id)
        if review is None:
            raise LookupError("The applicant submission is unavailable.")
        if review.status == "APPROVED":
            return review
        approved = replace(
            review,
            status="APPROVED",
            reviewed_by=actor.strip(),
            reviewed_at_utc=datetime.now(UTC),
        )
        self._reviews[confirmation_id] = approved
        return approved

    def queue_document(self, review: ApplicantDocumentReview) -> ApplicantDocumentReview:
        existing = self._document_reviews.get(review.submission_id)
        if existing is None:
            self._document_reviews[review.submission_id] = review
            return review
        return existing

    def pending_documents(self) -> tuple[ApplicantDocumentReview, ...]:
        return tuple(sorted(
            (item for item in self._document_reviews.values() if item.status == "PENDING"),
            key=lambda item: (item.submitted_at_utc, str(item.submission_id)),
        ))

    def accept_document(
        self, submission_id: UUID, *, actor: str, actor_group: str
    ) -> ApplicantDocumentReview:
        return self._review_document(
            submission_id, "ACCEPTED", actor=actor, actor_group=actor_group
        )

    def reject_document(
        self, submission_id: UUID, *, actor: str, actor_group: str, reason: str
    ) -> ApplicantDocumentReview:
        if not reason.strip():
            raise ValueError("A rejection reason is required.")
        return self._review_document(
            submission_id, "REJECTED", actor=actor, actor_group=actor_group,
            reason=reason.strip(),
        )

    def _review_document(
        self, submission_id: UUID, decision: str, *, actor: str,
        actor_group: str, reason: str | None = None,
    ) -> ApplicantDocumentReview:
        if actor_group not in REVIEWER_GROUPS or not actor.strip():
            raise PermissionError("Administrator or trustee authorization is required.")
        review = self._document_reviews.get(submission_id)
        if review is None:
            raise LookupError("The applicant document submission is unavailable.")
        if review.status != "PENDING":
            return review
        reviewed = replace(
            review, status=decision, reviewed_by=actor.strip(),
            reviewed_at_utc=datetime.now(UTC), reason=reason,
        )
        self._document_reviews[submission_id] = reviewed
        return reviewed
