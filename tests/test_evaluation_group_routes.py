from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.calls import CallContext, InMemoryCallCatalog
from app.config import Settings
from app.evaluation_data import EvaluationSnapshot
from app.evaluation_groups import EvaluationApplicant
from app.internal_preview import PreviewApplicantMetric, render_internal_preview
from app.identity import AuthenticatedIdentity
from app.main import ReadinessChecks, create_app
from app.navigation import INTERNAL_GROUPS
from app.preferences import Identity, InMemoryPreferenceRepository
from app.shortlist import MAGDA_ENTRA_OBJECT_ID, ShortlistState


CALL_A = CallContext(UUID(int=1), "EHF-2026", "ehf-2026", "EHF 2026", "2026",
                     "OPEN", "OPEN", "OPEN", False, "ehf-standard-v1",
                     datetime(2026, 12, 31, tzinfo=UTC), None, b"12345678")
CALL_B = CallContext(UUID(int=2), "EHF-2027", "ehf-2027", "EHF 2027", "2027",
                     "OPEN", "OPEN", "OPEN", False, "ehf-standard-v1",
                     datetime(2027, 12, 31, tzinfo=UTC), None, b"12345678")


class Evaluations:
    def __init__(self):
        self.calls = []
        self.comment_writes = []

    def load(self, call_id, group):
        self.calls.append((call_id, group))
        return EvaluationSnapshot(
            (("r", "Ricky"), ("m", "Magda"), ("a", "Adriano")),
            (EvaluationApplicant(str(call_id), "Applicant 2026" if call_id == CALL_A.fellowship_call_id else "Applicant 2027",
                                 "001", {"r": "A", "m": "A", "a": "A"}),),
        )

    def set_comment(self, call_id, application_id, comment, actor_identity, actor_group, entra_object_id):
        self.comment_writes.append((call_id, application_id, comment, actor_identity, actor_group, entra_object_id))
        return comment


def client(group=INTERNAL_GROUPS.administrators, entra_object_id=None):
    principal = AuthenticatedIdentity(
        Identity("test:a", "a@example.invalid", "A"), frozenset({group}), entra_object_id
    )
    catalog = InMemoryCallCatalog(
        (CALL_A, CALL_B),
        {"ehf-2026": frozenset({INTERNAL_GROUPS.administrators, INTERNAL_GROUPS.trustees}),
         "ehf-2027": frozenset({INTERNAL_GROUPS.administrators})},
    )
    evaluations = Evaluations()
    application = create_app(
        Settings.from_environment({}), call_catalog=catalog,
        evaluation_repository=evaluations, identity_resolver=lambda _request: principal,
        preference_repository=InMemoryPreferenceRepository(),
        readiness_checks=ReadinessChecks(sql_probe=lambda _timeout: None, storage_probe=lambda _timeout: None),
    )
    return TestClient(application, base_url="https://localhost"), evaluations


def test_group_view_and_word_export_are_scoped_to_selected_call():
    browser, evaluations = client()
    overview = browser.get("/internal/calls/ehf-2027/")
    assert 'href="/internal/calls/ehf-2027/evaluations/"' in overview.text
    html = browser.get("/internal/calls/ehf-2027/evaluations/")
    assert html.status_code == 200
    assert "Applicant 2027" in html.text
    assert "Applicant 2026" not in html.text
    docx = browser.get("/internal/calls/ehf-2027/evaluations.docx")
    assert docx.status_code == 200
    assert docx.content.startswith(b"PK")
    assert docx.headers["cache-control"] == "private, no-store"
    assert evaluations.calls == [
        (CALL_B.fellowship_call_id, INTERNAL_GROUPS.administrators),
        (CALL_B.fellowship_call_id, INTERNAL_GROUPS.administrators),
    ]


def test_ungranted_call_cannot_read_evaluation_page_or_document():
    browser, evaluations = client(INTERNAL_GROUPS.trustees)
    assert browser.get("/internal/calls/ehf-2027/evaluations/").status_code == 404
    assert browser.get("/internal/calls/ehf-2027/evaluations.docx").status_code == 404
    assert evaluations.calls == []


def test_reviewer_can_save_an_optional_comment_only_for_their_call():
    browser, evaluations = client(INTERNAL_GROUPS.trustees, MAGDA_ENTRA_OBJECT_ID)
    response = browser.post(
        "/api/internal/calls/ehf-2026/applications/00000000-0000-4000-8000-000000000001/evaluation-comment",
        json={"comment": "Strong project fit."},
        headers={"Origin": "https://localhost"},
    )

    assert response.status_code == 200
    assert response.json() == {"comment": "Strong project fit."}
    assert evaluations.comment_writes == [(
        CALL_A.fellowship_call_id,
        UUID("00000000-0000-4000-8000-000000000001"),
        "Strong project fit.",
        "test:a",
        INTERNAL_GROUPS.trustees,
        MAGDA_ENTRA_OBJECT_ID,
    )]


def test_2026_report_has_an_optional_comment_box_for_the_editable_reviewer():
    principal = AuthenticatedIdentity(
        Identity("test:magda", "magda@example.invalid", "Magda"),
        frozenset({INTERNAL_GROUPS.trustees}), MAGDA_ENTRA_OBJECT_ID,
    )
    application_id = str(UUID("00000000-0000-4000-8000-000000000001"))
    snapshot = EvaluationSnapshot(
        (("r", "Ricky"), ("m", "Magda"), ("a", "Adriano")),
        (EvaluationApplicant(application_id, "Applicant", "001",
                             {"m": "C"}, {"m": "Candidate's strong fit."}),),
        {"r": "ricky", "m": "magda", "a": "adriano"},
    )
    html = render_internal_preview(
        principal,
        records=(PreviewApplicantMetric(applicant="Applicant", application_id=application_id),),
        shortlist=ShortlistState({}, "magda"),
        evaluation_snapshot=snapshot,
        current_call=CALL_A,
    )

    assert 'maxlength="2000"' in html and "data-evaluation-comment" in html
    assert "Candidate&#x27;s strong fit." in html
    assert f"/api/internal/calls/ehf-2026/applications/{application_id}/evaluation-comment" in html
