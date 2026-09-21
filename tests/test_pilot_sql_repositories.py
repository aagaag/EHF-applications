from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.applicant.sql_pilot import (
    ApplicantSqlSessionScope,
    SqlApplicantApprovalService,
    SqlApplicantDocumentRepository,
    SqlApplicantFinalizationService,
    SqlSectionConfirmationService,
    SqlSyntheticDraftRepository,
    SqlSyntheticProjectionRepository,
)
from app.applicant.approval import ApplicantApprovalBlocked
from app.documents.store import DocumentStoreError
from app.applicant.confirmations import SectionConfirmation, _canonical_hash
from app.applicant.drafts import (
    CorrectionRequired,
    DraftConflict,
    DraftLocked,
    DraftSnapshot,
)
from app.applicant.finalize import (
    FinalizationBlocked,
    FinalizationSessionUnavailable,
    REQUIRED_SECTIONS,
)
import pyodbc


APPLICATION_A = UUID("91000000-0000-4000-8000-000000000001")
APPLICATION_B = UUID("91000000-0000-4000-8000-000000000002")
SESSION_HASH = b"s" * 32


class Cursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, *parameters: object):
        self.calls.append((sql, parameters))
        return self

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows


class Connection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.cursor = Cursor(rows)
        self.commits = 0

    def execute(self, sql: str, *parameters: object):
        return self.cursor.execute(sql, *parameters)

    def commit(self) -> None:
        self.commits += 1


class MultiResultCursor:
    def __init__(self, result_sets: list[list[tuple[object, ...]]]) -> None:
        self.result_sets = result_sets
        self.index = 0
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, *parameters: object):
        self.calls.append((sql, parameters))
        return self

    def fetchone(self):
        rows = self.result_sets[self.index]
        return rows[0] if rows else None

    def fetchall(self):
        return list(self.result_sets[self.index])

    def nextset(self):
        self.index += 1
        return self.index < len(self.result_sets)


class MultiResultConnection:
    def __init__(self, result_sets: list[list[tuple[object, ...]]]) -> None:
        self.cursor = MultiResultCursor(result_sets)
        self.commits = 0

    def execute(self, sql: str, *parameters: object):
        return self.cursor.execute(sql, *parameters)

    def commit(self) -> None:
        self.commits += 1


class ErrorConnection(Connection):
    def __init__(self, message: str) -> None:
        super().__init__([])
        self.message = message

    def execute(self, sql: str, *parameters: object):
        raise pyodbc.Error(self.message)


def factory(connection: Connection):
    @contextmanager
    def connect():
        yield connection

    return connect


def test_projection_uses_the_authenticated_session_and_rejects_a_mismatched_row() -> None:
    """Break caught: a caller-supplied application ID could select another applicant record."""
    scope = ApplicantSqlSessionScope()
    scope.bind(SESSION_HASH)
    connection = Connection(
        [
            (
                str(APPLICATION_A),
                '{"applicant":{"fullName":"Synthetic A"},"sections":{},"documents":[]}',
            ),
            (
                str(APPLICATION_A),
                '{"applicant":{"fullName":"Synthetic A"},"sections":{},"documents":[]}',
            ),
        ]
    )
    repository = SqlSyntheticProjectionRepository(factory(connection), scope)

    own = repository.load(APPLICATION_A)
    other = repository.load(APPLICATION_B)

    assert own is not None
    assert own.applicant["fullName"] == "Synthetic A"
    assert other is None
    assert all(parameters == (SESSION_HASH,) for _sql, parameters in connection.cursor.calls)
    assert all(str(APPLICATION_A) not in sql for sql, _parameters in connection.cursor.calls)
    assert all(str(APPLICATION_B) not in sql for sql, _parameters in connection.cursor.calls)


def test_draft_save_derives_scope_from_session_not_the_requested_application_id() -> None:
    """Break caught: draft writes could trust a browser-selected application identifier."""
    scope = ApplicantSqlSessionScope()
    scope.bind(SESSION_HASH)
    row_version = (7).to_bytes(8, "big")
    connection = Connection(
        [(
            "93000000-0000-4000-8000-000000000001",
            str(APPLICATION_A),
            "identity",
            '{"fullName":"Changed"}',
            row_version,
        )]
    )
    repository = SqlSyntheticDraftRepository(factory(connection), scope)

    saved = repository.save(
        APPLICATION_A,
        "identity",
        {"fullName": "Changed"},
        None,
        "APPLICANT",
    )

    sql, parameters = connection.cursor.calls[0]
    assert "SaveApplicantSectionDraft" in sql
    assert parameters[0] == SESSION_HASH
    assert APPLICATION_A not in parameters
    assert saved.application_id == APPLICATION_A
    assert saved.row_version == 7
    assert connection.commits == 1


def test_draft_load_exposes_only_the_current_applicants_open_correction_reason() -> None:
    scope = ApplicantSqlSessionScope()
    scope.bind(SESSION_HASH)
    returned_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    connection = Connection(
        [(
            str(APPLICATION_A),
            "employment",
            '{"postdoctoralEmploymentStatus":null}',
            (9).to_bytes(8, "big"),
            "Please answer the clarified employment question.",
            returned_at,
        )]
    )
    repository = SqlSyntheticDraftRepository(factory(connection), scope)

    snapshot = repository.load(APPLICATION_A, "employment")

    assert snapshot is not None
    assert snapshot.return_reason == "Please answer the clarified employment question."
    assert snapshot.returned_at_utc == returned_at
    assert connection.cursor.calls[0][1] == (SESSION_HASH, "employment")
    assert "GetApplicantSectionDraftV17" in connection.cursor.calls[0][0]


def test_session_scope_is_request_local_and_expires_closed() -> None:
    """Break caught: one applicant session could leak into another request or worker task."""
    scope = ApplicantSqlSessionScope()
    assert scope.current() is None
    scope.bind(SESSION_HASH)
    assert scope.current() == SESSION_HASH
    scope.clear()
    assert scope.current() is None


def test_document_slot_lookup_is_session_scoped_and_excludes_other_records() -> None:
    """Break caught: a supplied slot or application ID could cross the Entra session boundary."""
    scope = ApplicantSqlSessionScope()
    scope.bind(SESSION_HASH)
    slot_id = UUID("92000000-0000-4000-8000-000000000001")
    connection = Connection(
        [
            (
                str(slot_id),
                "CV",
                "Curriculum vitae",
                True,
                "MISSING",
                (4).to_bytes(8, "big"),
                None,
                None,
                "CV",
            )
        ]
    )
    repository = SqlApplicantDocumentRepository(factory(connection), scope)

    slots = repository.applicant_slots(
        type("Session", (), {"application_id": APPLICATION_A})()
    )

    assert len(slots) == 1
    assert slots[0].application_id == APPLICATION_A
    assert slots[0].slot_id == slot_id
    sql, parameters = connection.cursor.calls[0]
    assert "GetApplicantDocumentSlots" in sql
    assert parameters == (SESSION_HASH,)
    assert APPLICATION_A not in parameters


def test_draft_sql_conflict_and_lock_are_translated_to_workflow_exceptions() -> None:
    scope = ApplicantSqlSessionScope()
    scope.bind(SESSION_HASH)
    for message, expected in [
        ("[52026] The applicant draft changed before save.", DraftConflict),
        ("[52025] The applicant draft is locked.", DraftLocked),
    ]:
        repository = SqlSyntheticDraftRepository(factory(ErrorConnection(message)), scope)
        try:
            repository.save(APPLICATION_A, "identity", {"fullName": "A"}, 1, "APPLICANT")
        except Exception as error:
            assert isinstance(error, expected)
        else:
            raise AssertionError("The SQL workflow exception was not translated.")


def test_finalization_preview_includes_sql_document_completion_issues() -> None:
    snapshots = {
        section: DraftSnapshot(APPLICATION_A, section, {"ok": True}, index + 1)
        for index, section in enumerate(REQUIRED_SECTIONS)
    }

    class Drafts:
        def load(self, application_id, section):
            assert application_id == APPLICATION_A
            return snapshots[section]

    class Confirmations:
        def current(self, application_id, section):
            snapshot = snapshots[section]
            return SectionConfirmation(application_id, section, snapshot.row_version, "a" * 64)

        def is_current(self, application_id, section, snapshot):
            return True

    class Documents:
        def completion_issues(self):
            return ("document:CV",)

        def final_documents(self):
            return ()

    scope = ApplicantSqlSessionScope()
    service = SqlApplicantFinalizationService(
        factory(Connection([])), scope, Drafts(), Confirmations(), Documents()
    )
    session = type("Session", (), {"application_id": APPLICATION_A})()

    preview = service.preview(session)

    assert preview["ready"] is False
    assert preview["unresolved"] == ("document:CV",)


def test_finalization_sql_races_are_translated_to_stable_workflow_errors() -> None:
    snapshots = {
        section: DraftSnapshot(APPLICATION_A, section, {"ok": True}, index + 1)
        for index, section in enumerate(REQUIRED_SECTIONS)
    }

    class Drafts:
        def load(self, _application_id, section):
            return snapshots[section]

    class Confirmations:
        def current(self, _application_id, section):
            snapshot = snapshots[section]
            return SectionConfirmation(APPLICATION_A, section, snapshot.row_version, "a" * 64)

        def is_current(self, _application_id, _section, _snapshot):
            return True

    class Documents:
        def completion_issues(self):
            return ()

        def final_documents(self):
            return ()

    session = type("Session", (), {"application_id": APPLICATION_A})()
    for message, expected in [
        ("[52133] The applicant session is unavailable.", FinalizationSessionUnavailable),
        ("[52135] Every applicant section must be represented once.", FinalizationBlocked),
        ("[52136] An applicant section is missing or stale.", FinalizationBlocked),
    ]:
        scope = ApplicantSqlSessionScope()
        scope.bind(SESSION_HASH)
        service = SqlApplicantFinalizationService(
            factory(ErrorConnection(message)), scope, Drafts(), Confirmations(), Documents()
        )
        try:
            service.submit(session)
        except Exception as error:
            assert isinstance(error, expected)
        else:
            raise AssertionError("The finalization SQL error was not translated.")


def test_unclassifiable_legacy_employment_answer_is_an_actionable_approval_block() -> None:
    service = SqlApplicantApprovalService(
        factory(ErrorConnection("[52646] The approved postdoctoral employment status requires review."))
    )

    with pytest.raises(ApplicantApprovalBlocked) as blocked:
        service.approve(
            UUID("81000000-0000-4000-8000-000000000001"),
            actor="cloudflare:reviewer",
            actor_group="EHF-Administrators",
        )

    assert blocked.value.section == "employment"


def test_administrator_preview_repository_lists_and_loads_saved_applicant_form() -> None:
    summary_connection = Connection(
        [(str(APPLICATION_A), "Synthetic Applicant", "IMPORTED")]
    )
    service = SqlApplicantApprovalService(factory(summary_connection))

    summaries = service.previews("EHF-Administrators")

    assert summaries[0].application_id == APPLICATION_A
    assert summaries[0].applicant_name == "Synthetic Applicant"
    assert summary_connection.cursor.calls[0][1] == ("EHF-Administrators",)
    assert "ListApplicantPreviews" in summary_connection.cursor.calls[0][0]

    detail_connection = MultiResultConnection(
        [
            [
                (
                    str(APPLICATION_A),
                    "Synthetic Applicant",
                    "IMPORTED",
                    '{"applicant":{"fullName":"Synthetic Applicant"}}',
                )
            ],
            [("identity", '{"telephone":"+41 71 111 11 11"}')],
            [
                (
                    "a1000000-0000-4000-8000-000000000001",
                    "Ada Author; Ben Biologist; Cara Chemist",
                    "A publication title",
                    "Journal of Synthetic Results",
                    "12",
                    "101-109",
                    2025,
                    37,
                    "OBSERVED",
                    "10.1000/example",
                    39,
                    "OBSERVED",
                    35,
                    "OBSERVED",
                )
            ],
        ]
    )
    detail_service = SqlApplicantApprovalService(factory(detail_connection))

    preview = detail_service.preview(
        APPLICATION_A,
        actor="cloudflare:administrator",
        actor_group="EHF-Administrators",
    )

    assert preview.baseline["applicant"]["fullName"] == "Synthetic Applicant"
    assert preview.drafts["identity"]["telephone"] == "+41 71 111 11 11"
    assert len(preview.publication_records) == 1
    publication = preview.publication_records[0]
    assert publication.authors_text == "Ada Author; Ben Biologist; Cara Chemist"
    assert publication.title == "A publication title"
    assert publication.journal_text == "Journal of Synthetic Results"
    assert publication.volume_text == "12"
    assert publication.pages_text == "101-109"
    assert publication.publication_year == 2025
    assert publication.citation_count == 37
    assert publication.citation_status == "OBSERVED"
    assert publication.openalex_citation_count == 39
    assert publication.openalex_citation_status == "OBSERVED"
    assert publication.semantic_scholar_citation_count == 35
    assert publication.semantic_scholar_citation_status == "OBSERVED"
    assert publication.google_scholar_url == (
        "https://scholar.google.com/scholar?q=10.1000%2Fexample"
    )
    assert detail_connection.cursor.calls[0][1] == (
        APPLICATION_A,
        "cloudflare:administrator",
        "EHF-Administrators",
    )
    assert "GetApplicantPreview" in detail_connection.cursor.calls[0][0]
    assert "@EmitPublications = 1" in detail_connection.cursor.calls[0][0]
    assert detail_connection.commits == 1


def test_applicant_preview_repository_is_administrator_only() -> None:
    service = SqlApplicantApprovalService(factory(Connection([])))

    with pytest.raises(PermissionError):
        service.previews("EHF-Trustees")
    with pytest.raises(PermissionError):
        service.preview(
            APPLICATION_A,
            actor="cloudflare:trustee",
            actor_group="EHF-Trustees",
        )


def test_unknown_sql_applicant_preview_is_translated_to_a_neutral_lookup_error() -> None:
    service = SqlApplicantApprovalService(
        factory(ErrorConnection("[52811] The applicant preview is unavailable."))
    )

    with pytest.raises(LookupError):
        service.preview(
            APPLICATION_A,
            actor="cloudflare:administrator",
            actor_group="EHF-Administrators",
        )


def test_access_request_review_maps_procedure_state_errors() -> None:
    """Break caught: deciding an already-decided access request answered 500."""
    from app.applicant.sql_pilot import SqlApplicantAccessRepository

    for message, expected in [
        ("[52612] The access request is unavailable.", LookupError),
        ("[52611] A valid access-request review is required.", ValueError),
    ]:
        repository = SqlApplicantAccessRepository(factory(ErrorConnection(message)))

        with pytest.raises(expected):
            repository.review(
                APPLICATION_A,
                "REJECTED",
                actor="cloudflare:administrator",
                actor_group="EHF-Administrators",
            )


def test_return_for_correction_sql_races_are_translated_to_route_errors() -> None:
    for message, expected in [
        ("[52642] The applicant submission is unavailable.", LookupError),
        ("[52643] A valid section and correction reason are required.", ValueError),
    ]:
        service = SqlApplicantApprovalService(factory(ErrorConnection(message)))
        with pytest.raises(expected):
            service.return_for_correction(
                UUID("81000000-0000-4000-8000-000000000001"),
                section="employment",
                reason="Clarify the answer.",
                actor="cloudflare:reviewer",
                actor_group="EHF-Administrators",
            )


def test_approval_of_a_superseded_confirmation_is_a_neutral_lookup_error() -> None:
    """Break caught: a stale review-queue entry could answer 500 instead of 404."""
    service = SqlApplicantApprovalService(
        factory(ErrorConnection("[52642] The applicant submission is unavailable."))
    )

    with pytest.raises(LookupError):
        service.approve(
            UUID("81000000-0000-4000-8000-000000000001"),
            actor="cloudflare:administrator",
            actor_group="EHF-Administrators",
        )


def test_synthetic_workspace_submission_is_not_approvable() -> None:
    """Break caught: a synthetic workspace could enter the approval queue."""
    service = SqlApplicantApprovalService(
        factory(ErrorConnection("[52912] Synthetic workspaces cannot enter approval."))
    )

    with pytest.raises(LookupError):
        service.approve(
            UUID("81000000-0000-4000-8000-000000000001"),
            actor="cloudflare:administrator",
            actor_group="EHF-Administrators",
        )


def test_sql_section_confirmation_stays_current_after_an_identical_save() -> None:
    """Break caught: a re-saved but unchanged section could never be confirmed again.

    GetApplicantSectionConfirmation returns the confirmation stored for the canonical
    content hash, whose draft row version is historical; a later save of the same
    content must still count as confirmed for the current draft.
    """
    scope = ApplicantSqlSessionScope()
    scope.bind(SESSION_HASH)
    stored_hash = _canonical_hash({"preferredName": "Same"}, 7)
    stored_row = (
        APPLICATION_A,
        "identity",
        bytes.fromhex(stored_hash),
        (7).to_bytes(8, "big"),
    )
    # The fake cursor pops one row per call, and each check reads the confirmation once.
    connection = Connection([stored_row, stored_row, stored_row])
    service = SqlSectionConfirmationService(factory(connection), scope)
    resaved = DraftSnapshot(APPLICATION_A, "identity", {"preferredName": "Same"}, 21)

    assert service.current(APPLICATION_A, "identity") is not None
    assert service.is_current(APPLICATION_A, "identity", resaved) is True

    changed = DraftSnapshot(APPLICATION_A, "identity", {"preferredName": "Other"}, 22)
    assert service.is_current(APPLICATION_A, "identity", changed) is False


def test_returned_section_must_be_saved_before_sql_reconfirmation() -> None:
    scope = ApplicantSqlSessionScope()
    scope.bind(SESSION_HASH)
    service = SqlSectionConfirmationService(
        factory(ErrorConnection("[52143] Save the returned section before confirming it again.")),
        scope,
    )
    snapshot = DraftSnapshot(
        APPLICATION_A, "employment", {"postdoctoralEmploymentStatus": True}, 9
    )

    with pytest.raises(CorrectionRequired, match="Save the returned section"):
        service.confirm(APPLICATION_A, "employment", snapshot)

    unchanged = SqlSectionConfirmationService(
        factory(ErrorConnection("[52144] Make the requested correction before confirming this section.")),
        scope,
    )
    with pytest.raises(CorrectionRequired):
        unchanged.confirm(APPLICATION_A, "employment", snapshot)


APPLICATION_PREVIEW_DOCUMENT = UUID("91000000-0000-4000-8000-000000000031")
APPLICATION_PREVIEW_DOCUMENT_ID = UUID("91000000-0000-4000-8000-000000000032")
APPLICATION_PREVIEW_OBJECT = UUID("91000000-0000-4000-8000-000000000033")
APPLICATION_PREVIEW_OBJECT_KEY = "0123456789abcdef0123456789abcdef"


class FakeObjectStore:
    """Object store double that records the exact envelope and binding it was asked for."""

    def __init__(self, content: bytes = b"%PDF-1.7 synthetic proposal") -> None:
        self.content = content
        self.calls: list[tuple[object, object]] = []

    def decrypt_bytes(self, record: object, binding: object) -> bytes:
        self.calls.append((record, binding))
        return self.content


def test_applicant_review_cards_map_the_release_25_metrics() -> None:
    """Break caught: a card could show the wrong applicant's citation or academic-age source."""
    connection = Connection(
        [
            (
                str(APPLICATION_A),
                "Synthetic Applicant",
                "IMPORTED",
                Decimal("4.50"),
                12,
                734,
                "OPENALEX",
                "https://openalex.org/A123",
                "Synthetic neurodegeneration",
                2,
            )
        ]
    )
    service = SqlApplicantApprovalService(factory(connection))

    summaries = service.previews("EHF-Administrators")

    card = summaries[0]
    assert card.application_id == APPLICATION_A
    assert card.academic_age_years == 4.5
    assert card.h_index == 12
    assert card.citation_count == 734
    assert card.citation_source == "OPENALEX"
    assert card.citation_profile_url == "https://openalex.org/A123"
    assert card.research_area == "Synthetic neurodegeneration"
    assert card.document_count == 2
    assert "ListApplicantPreviews" in connection.cursor.calls[0][0]
    assert connection.cursor.calls[0][1] == ("EHF-Administrators",)


def test_applicant_review_card_survives_a_database_without_the_metric_columns() -> None:
    """Break caught: a release ahead of its migration could break the whole review page."""
    connection = Connection([(str(APPLICATION_A), "Synthetic Applicant", "IMPORTED")])
    service = SqlApplicantApprovalService(factory(connection))

    card = service.previews("EHF-Administrators")[0]

    assert card.applicant_name == "Synthetic Applicant"
    assert card.academic_age_years is None
    assert card.document_count == 0


def test_applicant_preview_documents_are_administrator_only_and_exact() -> None:
    """Break caught: a trustee request or missing actor could list a dossier's documents."""
    connection = MultiResultConnection(
        [
            [(str(APPLICATION_A), "Synthetic Applicant", "IMPORTED")],
            [
                (
                    str(APPLICATION_PREVIEW_DOCUMENT),
                    "import-3c5d91b88145",
                    "Research plan",
                    "RESEARCH_PLAN",
                    "UNREVIEWED",
                    19,
                    1115189,
                    "application/pdf",
                )
            ],
        ]
    )
    service = SqlApplicantApprovalService(factory(connection))

    bundle = service.preview_documents(
        APPLICATION_A, actor="cloudflare:administrator", actor_group="EHF-Administrators"
    )

    assert bundle.application_id == APPLICATION_A
    assert bundle.applicant_name == "Synthetic Applicant"
    assert bundle.application_status == "IMPORTED"
    document = bundle.documents[0]
    assert document.document_version_id == APPLICATION_PREVIEW_DOCUMENT
    assert document.document_type == "RESEARCH_PLAN"
    assert document.page_count == 19
    assert document.byte_size == 1115189
    assert document.classification == "UNREVIEWED"
    assert connection.cursor.calls[0][1] == (
        APPLICATION_A,
        "cloudflare:administrator",
        "EHF-Administrators",
    )
    assert "ListApplicantPreviewDocuments" in connection.cursor.calls[0][0]
    assert connection.commits == 1

    with pytest.raises(PermissionError):
        service.preview_documents(
            APPLICATION_A, actor="cloudflare:trustee", actor_group="EHF-Trustees"
        )
    with pytest.raises(PermissionError):
        service.preview_documents(
            APPLICATION_A, actor="   ", actor_group="EHF-Administrators"
        )


def test_unknown_sql_applicant_documents_are_a_neutral_lookup_error() -> None:
    """Break caught: a guessed application ID could report a distinguishable SQL error."""
    service = SqlApplicantApprovalService(
        factory(ErrorConnection("[52921] The applicant documents are unavailable."))
    )

    with pytest.raises(LookupError):
        service.preview_documents(
            APPLICATION_A, actor="cloudflare:administrator", actor_group="EHF-Administrators"
        )


def test_applicant_preview_document_decrypts_only_the_authorized_envelope() -> None:
    """Break caught: the wrong dossier PDF, or an unbound one, could be decrypted and served."""
    store = FakeObjectStore()
    connection = Connection(
        [
            (
                str(APPLICATION_A),
                str(APPLICATION_PREVIEW_DOCUMENT_ID),
                str(APPLICATION_PREVIEW_DOCUMENT),
                str(APPLICATION_PREVIEW_OBJECT),
                APPLICATION_PREVIEW_OBJECT_KEY,
                1,
                1,
                b"n" * 12,
                b"p" * 32,
                b"c" * 32,
                1024,
                "application/pdf",
                3,
                "import-3c5d91b88145",
                "RESEARCH_PLAN",
            )
        ]
    )
    service = SqlApplicantApprovalService(factory(connection), store)  # type: ignore[arg-type]

    payload = service.preview_document(
        APPLICATION_PREVIEW_DOCUMENT,
        actor="cloudflare:administrator",
        actor_group="EHF-Administrators",
    )

    assert payload.content == b"%PDF-1.7 synthetic proposal"
    assert payload.media_type == "application/pdf"
    assert payload.display_name == "research-plan-3c5d91b88145.pdf"
    record, binding = store.calls[0]
    assert record.object_key == APPLICATION_PREVIEW_OBJECT_KEY  # type: ignore[attr-defined]
    assert record.byte_size == 1024  # type: ignore[attr-defined]
    assert binding.application_id == APPLICATION_A  # type: ignore[attr-defined]
    assert binding.version_id == APPLICATION_PREVIEW_DOCUMENT  # type: ignore[attr-defined]
    assert "GetApplicantPreviewDocument" in connection.cursor.calls[0][0]
    assert connection.cursor.calls[0][1] == (
        APPLICATION_PREVIEW_DOCUMENT,
        "cloudflare:administrator",
        "EHF-Administrators",
    )

    with pytest.raises(PermissionError):
        service.preview_document(
            APPLICATION_PREVIEW_DOCUMENT,
            actor="cloudflare:trustee",
            actor_group="EHF-Trustees",
        )


def test_applicant_preview_document_requires_a_store_and_rejects_a_failed_envelope() -> None:
    """Break caught: an unwired or corrupt object store could surface an internal failure."""
    storeless = SqlApplicantApprovalService(
        factory(ErrorConnection("an unwired store must fail before the database is read"))
    )

    with pytest.raises(LookupError):
        storeless.preview_document(
            APPLICATION_PREVIEW_DOCUMENT,
            actor="cloudflare:administrator",
            actor_group="EHF-Administrators",
        )

    connection = Connection(
        [
            (
                str(APPLICATION_A),
                str(APPLICATION_PREVIEW_DOCUMENT_ID),
                str(APPLICATION_PREVIEW_DOCUMENT),
                str(APPLICATION_PREVIEW_OBJECT),
                APPLICATION_PREVIEW_OBJECT_KEY,
                1,
                1,
                b"n" * 12,
                b"p" * 32,
                b"c" * 32,
                1024,
                "application/pdf",
                3,
                "import-3c5d91b88145",
                "RESEARCH_PLAN",
            )
        ]
    )

    class FailingStore:
        def decrypt_bytes(self, record: object, binding: object) -> bytes:
            raise DocumentStoreError(
                "The encrypted document object failed integrity validation."
            )

    failing = SqlApplicantApprovalService(factory(connection), FailingStore())  # type: ignore[arg-type]
    with pytest.raises(LookupError):
        failing.preview_document(
            APPLICATION_PREVIEW_DOCUMENT,
            actor="cloudflare:administrator",
            actor_group="EHF-Administrators",
        )


def test_unknown_sql_applicant_preview_document_is_a_neutral_lookup_error() -> None:
    """Break caught: a stale or foreign document version could report a SQL error."""
    service = SqlApplicantApprovalService(
        factory(ErrorConnection("[52921] The applicant document is unavailable.")),
        FakeObjectStore(),  # type: ignore[arg-type]
    )

    with pytest.raises(LookupError):
        service.preview_document(
            APPLICATION_PREVIEW_DOCUMENT,
            actor="cloudflare:administrator",
            actor_group="EHF-Administrators",
        )
