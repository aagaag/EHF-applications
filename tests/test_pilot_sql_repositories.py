from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
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
from app.applicant.confirmations import SectionConfirmation
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
    assert detail_connection.cursor.calls[0][1] == (
        APPLICATION_A,
        "cloudflare:administrator",
        "EHF-Administrators",
    )
    assert "GetApplicantPreview" in detail_connection.cursor.calls[0][0]
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
