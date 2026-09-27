from uuid import UUID

from app.evaluation_data import SqlEvaluationRepository


CALL_ID = UUID("11111111-1111-1111-1111-111111111111")


class Cursor:
    def __init__(self):
        self.set_index = 0

    def fetchall(self):
        return (
            [("reviewer-a", "Ricky", 1, "ricky"),
             ("reviewer-b", "Magda", 2, "magda"),
             ("reviewer-c", "Adriano", 3, "adriano")]
            if self.set_index == 0
            else [("application-a", "Ada Applicant", "EHF-2026-001", "reviewer-a", "A", None),
                  ("application-a", "Ada Applicant", "EHF-2026-001", "reviewer-b", None, "Strong project fit."),
                  ("application-a", "Ada Applicant", "EHF-2026-001", "reviewer-c", "C", None)]
        )

    def nextset(self):
        self.set_index += 1


class Connection:
    def __init__(self):
        self.args = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query, *args):
        self.args = query, args
        return Cursor()


def test_repository_reads_only_requested_call_and_preserves_partial_discrepancy():
    connection = Connection()
    snapshot = SqlEvaluationRepository(lambda: connection).load(CALL_ID, "EHF-Trustees")
    assert connection.args == (
        "EXEC dbo.GetCallEvaluationOverview @FellowshipCallId=?, @ActorGroup=?",
        (CALL_ID, "EHF-Trustees"),
    )
    assert snapshot.roster == (("reviewer-a", "Ricky"), ("reviewer-b", "Magda"), ("reviewer-c", "Adriano"))
    assert snapshot.legacy_codes == {"reviewer-a": "ricky", "reviewer-b": "magda", "reviewer-c": "adriano"}
    assert len(snapshot.applicants) == 1
    assert snapshot.applicants[0].grades == {"reviewer-a": "A", "reviewer-b": None, "reviewer-c": "C"}
    assert snapshot.applicants[0].comments == {"reviewer-b": "Strong project fit."}
