from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest


def test_catalog_resolves_only_an_authorized_exact_lowercase_slug() -> None:
    """Break caught: an internal user could silently fall back to the wrong call."""
    from app.calls import CallContext, InMemoryCallCatalog

    context = CallContext(
        fellowship_call_id=UUID("00000000-0000-4000-8000-000000000001"),
        call_code="EHF-2027",
        public_slug="ehf-2027",
        display_name="EHF 2027 Fellowship",
        compact_title="EHF 2027",
        call_status="OPEN",
        applicant_review_status="OPEN",
        internal_selection_status="OPEN",
        invitations_enabled=False,
        analysis_profile_code="ehf-standard-v1",
        application_deadline_utc=datetime(2027, 1, 31, tzinfo=UTC),
        applicant_review_deadline_utc=None,
        row_version=b"12345678",
    )
    catalog = InMemoryCallCatalog(
        (context,), {"ehf-2027": frozenset({"EHF-Administrators"})}
    )

    assert catalog.resolve("ehf-2027", "EHF-Administrators", "READ") == context
    with pytest.raises(LookupError):
        catalog.resolve("ehf-2028", "EHF-Administrators", "READ")
    with pytest.raises(LookupError):
        catalog.resolve("ehf-2027", "EHF-Trustees", "READ")
    with pytest.raises(ValueError):
        catalog.resolve("EHF-2027", "EHF-Administrators", "READ")


def test_public_call_projection_does_not_disclose_internal_call_identifiers() -> None:
    """Break caught: a public call lookup could disclose a private row identifier."""
    from app.calls import CallContext, InMemoryCallCatalog, PublicCallContext

    context = CallContext(
        fellowship_call_id=UUID("00000000-0000-4000-8000-000000000001"),
        call_code="EHF-2027",
        public_slug="ehf-2027",
        display_name="EHF 2027 Fellowship",
        compact_title="EHF 2027",
        call_status="OPEN",
        applicant_review_status="OPEN",
        internal_selection_status="OPEN",
        invitations_enabled=False,
        analysis_profile_code="ehf-standard-v1",
        application_deadline_utc=datetime(2027, 1, 31, tzinfo=UTC),
        applicant_review_deadline_utc=None,
        row_version=b"12345678",
    )

    projected = InMemoryCallCatalog((context,), {}).resolve_public("ehf-2027")

    assert projected == PublicCallContext(
        public_slug="ehf-2027",
        call_code="EHF-2027",
        display_name="EHF 2027 Fellowship",
        application_deadline_utc=datetime(2027, 1, 31, tzinfo=UTC),
        applicant_review_deadline_utc=None,
        applicant_review_status="OPEN",
    )
    assert not hasattr(projected, "fellowship_call_id")


def test_application_construction_accepts_an_injected_call_catalog() -> None:
    """Break caught: internal routes could bypass the call authorization boundary."""
    from app.calls import InMemoryCallCatalog
    from app.config import Settings
    from app.main import ReadinessChecks, create_app

    application = create_app(
        Settings.from_environment({}),
        call_catalog=InMemoryCallCatalog(),
        readiness_checks=ReadinessChecks(sql_probe=lambda _timeout: None, storage_probe=lambda _timeout: None),
    )

    assert application.state.call_catalog.__class__ is InMemoryCallCatalog
