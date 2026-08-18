from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.applicant.confirmations import SectionConfirmationService
from app.applicant.fields import upgrade_legacy_section
from app.applicant.drafts import InMemoryDraftRepository
from app.applicant.publications import PublicationLookupReceipts
from app.applicant.review import ApplicantReviewService
from app.auth.applicant import ApplicantSessionContext


APPLICATION = UUID("73000000-0000-4000-8000-000000000001")


def _session() -> ApplicantSessionContext:
    return ApplicantSessionContext(
        APPLICATION,
        bytes(32),
        datetime.now(UTC) + timedelta(minutes=30),
        datetime.now(UTC) + timedelta(hours=24),
    )


def _service() -> tuple[
    ApplicantReviewService, InMemoryDraftRepository, SectionConfirmationService
]:
    drafts = InMemoryDraftRepository()
    confirmations = SectionConfirmationService()
    review = ApplicantReviewService(
        drafts,
        confirmations,
        PublicationLookupReceipts(
            b"synthetic-publication-receipt-secret-at-least-32-bytes"
        ),
    )
    return review, drafts, confirmations


def test_legacy_signed_draft_is_presented_in_new_schema_without_rewriting_hash() -> None:
    review, drafts, confirmations = _service()
    raw = drafts.save(
        APPLICATION,
        "qualifications",
        {"degreeCategory": "MD_PHD", "phdDate": "2020-06-30"},
        None,
        "APPLICANT",
    )
    confirmations.confirm(APPLICATION, "qualifications", raw)

    presented = review.load(_session(), "qualifications")

    assert presented is not None
    assert presented.values == {
        "degrees": [
            {"degreeType": "MD", "conferralDate": None},
            {"degreeType": "PhD", "conferralDate": "2020-06-30"},
        ]
    }
    assert presented.row_version == raw.row_version
    assert review.is_current(_session(), "qualifications", presented) is True
    assert drafts.load(APPLICATION, "qualifications") == raw


def test_new_save_keeps_legacy_keys_for_rolling_rollback_but_never_exposes_them() -> None:
    review, drafts, _confirmations = _service()
    raw = drafts.save(
        APPLICATION,
        "qualifications",
        {"degreeCategory": "PHD", "phdDate": "2018-06-30"},
        None,
        "APPLICANT",
    )

    saved = review.save(
        _session(),
        "qualifications",
        {
            "degrees": [
                {"degreeType": "BSc", "conferralDate": "2012-06-30"},
                {"degreeType": "PhD", "conferralDate": "2019-06-30"},
            ]
        },
        raw.row_version,
    )

    assert saved.values == {
        "degrees": [
            {"degreeType": "BSc", "conferralDate": datetime(2012, 6, 30).date()},
            {"degreeType": "PhD", "conferralDate": datetime(2019, 6, 30).date()},
        ]
    }
    persisted = drafts.load(APPLICATION, "qualifications")
    assert persisted is not None
    assert persisted.values["degreeCategory"] == "PHD"
    assert persisted.values["phdDate"] == datetime(2019, 6, 30).date()
    assert persisted.values["degrees"] == saved.values["degrees"]

    confirmation = review.confirm(_session(), "qualifications", saved.row_version)
    assert confirmation.row_version == saved.row_version
    assert review.is_current(_session(), "qualifications", saved) is True


def test_legacy_future_postdoctoral_status_maps_to_no_and_unknown_requires_review() -> None:
    assert upgrade_legacy_section(
        "employment", {"postdoctoralEmploymentStatus": "future"}
    )["postdoctoralEmploymentStatus"] is False
    assert upgrade_legacy_section(
        "employment", {"postdoctoralEmploymentStatus": "unclassified legacy wording"}
    )["postdoctoralEmploymentStatus"] is None
