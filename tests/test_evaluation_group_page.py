from datetime import UTC, datetime
from uuid import uuid4

from app.calls import CallContext
from app.evaluation_group_page import render_evaluation_group_page
from app.evaluation_groups import EvaluationApplicant, EvaluationGroups


def _call(slug: str = "ehf-2026") -> CallContext:
    return CallContext(
        fellowship_call_id=uuid4(), call_code="EHF-2026", public_slug=slug,
        display_name="Charles Weissmann Fellowship", compact_title="EHF 2026",
        call_status="OPEN", applicant_review_status="OPEN", internal_selection_status="PENDING",
        invitations_enabled=False, analysis_profile_code="default",
        application_deadline_utc=datetime(2026, 1, 1, tzinfo=UTC),
        applicant_review_deadline_utc=None, row_version=b"1",
    )


def _applicant(identifier: str, name: str, number: str, grades: dict[str, str | None], comments=None):
    return EvaluationApplicant(identifier, name, number, grades, comments or {})


def test_page_renders_all_ordered_sections_and_counts():
    groups = EvaluationGroups(
        buckets={
            "AAA": (_applicant("1", "Alice", "E-1", {"r1": "A", "r2": "A", "r3": "A"}),),
            "AAB": (), "ABB": (), "BBB": (), "BBC": (), "BCC": (), "CCC": (),
        }, strong_discrepancy=(), awaiting_reviews=(),
    )
    html = render_evaluation_group_page(
        _call(), groups, (("r1", "Ricky Reviewer"), ("r2", "Magda Reviewer"), ("r3", "Me Reviewer"))
    )
    positions = [html.index(f'aria-labelledby="group-{key}-heading"') for key in ("AAA", "AAB", "ABB", "BBB", "BBC", "BCC", "CCC")]
    assert positions == sorted(positions)
    assert '<h2 id="group-AAA-heading">AAA <span class="section-count">(1)</span></h2>' in html
    assert '<h2 id="group-CCC-heading">CCC <span class="section-count">(0)</span></h2>' in html
    assert "Alice" in html and "E-1" in html


def test_page_renders_discrepancy_partial_and_awaiting_states_with_escaped_text():
    partial = _applicant("1", "<Alice>", 'E-"1"', {"r1": "A"})
    discrepancy = _applicant("2", "Bob", "E-2", {"r1": "A", "r2": "C"})
    groups = EvaluationGroups(
        buckets={key: () for key in ("AAA", "AAB", "ABB", "BBB", "BBC", "BCC", "CCC")},
        strong_discrepancy=(discrepancy,), awaiting_reviews=(partial, discrepancy),
    )
    html = render_evaluation_group_page(
        _call("ehf-2026"), groups, (("r1", "Ricky <Reviewer>"), ("r2", "Magda"), ("r3", "Me"))
    )
    assert "Strong discrepancy" in html and "Awaiting reviews" in html
    assert 'href="/internal/calls/ehf-2026/evaluations.docx"' in html
    assert 'href="/internal/calls/ehf-2026/"' in html
    assert "&lt;Alice&gt;" in html and "E-&quot;1&quot;" in html
    assert "Ricky &lt;Reviewer&gt;" in html
    assert "A" in html and "C" in html and "Awaiting" in html


def test_page_displays_review_comments_as_escaped_text():
    commented = _applicant(
        "1", "Alice", "E-1", {"r1": "A", "r2": "B", "r3": "C"},
        comments={"r2": "Strong fit <script>alert(1)</script>"},
    )
    groups = EvaluationGroups(
        buckets={key: () for key in ("AAA", "AAB", "ABB", "BBB", "BBC", "BCC", "CCC")},
        strong_discrepancy=(), awaiting_reviews=(commented,),
    )

    html = render_evaluation_group_page(
        _call(), groups, (("r1", "Ricky"), ("r2", "Magda"), ("r3", "Adriano"))
    )

    assert "Strong fit &lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_grade_letters_have_distinct_classes_for_color_coding():
    applicant = _applicant("1", "Alice", "E-1", {"r1": "A", "r2": "B", "r3": "C"})
    groups = EvaluationGroups(
        buckets={key: () for key in ("AAA", "AAB", "ABB", "BBB", "BBC", "BCC", "CCC")},
        strong_discrepancy=(), awaiting_reviews=(applicant,),
    )

    html = render_evaluation_group_page(
        _call(), groups, (("r1", "Ricky"), ("r2", "Magda"), ("r3", "Adriano"))
    )

    assert '<strong class="grade-value grade-a">A</strong>' in html
    assert '<strong class="grade-value grade-b">B</strong>' in html
    assert '<strong class="grade-value grade-c">C</strong>' in html
