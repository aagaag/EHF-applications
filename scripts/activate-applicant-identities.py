#!/usr/bin/env python3
"""Link verified Entra guests and create the fixed synthetic applicant pilot."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pyodbc

from app.applicant.pilot import synthetic_projection


PILOT_CALL_ID = UUID("71000000-0000-4000-8000-000000000001")
PILOT_APPLICANT_ID = UUID("71000000-0000-4000-8000-000000000002")
PILOT_APPLICATION_ID = UUID("71000000-0000-4000-8000-000000000003")
PILOT_SLOT_ID = UUID("71000000-0000-4000-8000-000000000004")


def _connect(password_path: Path):
    password = password_path.read_text(encoding="utf-8").strip().replace("}", "}}")
    if not password:
        raise RuntimeError("The SQL administrator credential is unavailable.")
    return pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};SERVER=tcp:127.0.0.1,1433;"
        "DATABASE=EHFApplications;UID=sa;"
        f"PWD={{{password}}};Encrypt=yes;TrustServerCertificate=yes;",
        autocommit=False,
    )


def activate(password_path: Path, provisioning_path: Path, pilot_entra_id: UUID) -> dict[str, int]:
    rows = json.loads(provisioning_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("The verified applicant provisioning record is unavailable.")
    mappings = [(UUID(row["applicationId"]), UUID(row["entraObjectId"])) for row in rows]
    if len(set(mappings)) != len(mappings):
        raise RuntimeError("The verified applicant provisioning record contains duplicates.")
    connection = _connect(password_path)
    try:
        cursor = connection.cursor()
        for application_id, entra_id in mappings:
            existing = cursor.execute(
                "SELECT ApplicationId, EntraObjectId FROM dbo.ApplicantEntraIdentity "
                "WHERE ApplicationId=? OR EntraObjectId=?", application_id, entra_id,
            ).fetchall()
            if existing and any(
                UUID(str(row[0])) != application_id or UUID(str(row[1])) != entra_id
                for row in existing
            ):
                raise RuntimeError("An existing applicant identity mapping conflicts.")
            if not existing:
                cursor.execute(
                    "INSERT dbo.ApplicantEntraIdentity "
                    "(ApplicationId, EntraObjectId, IdentityKind, Enabled, LinkedByIdentity) "
                    "VALUES (?, ?, 'LEGACY_APPLICANT', 1, N'AUTONOMOUS_ROLLOUT_2026')",
                    application_id, entra_id,
                )

        if cursor.execute(
            "SELECT COUNT_BIG(*) FROM dbo.FellowshipCall WHERE FellowshipCallId=?",
            PILOT_CALL_ID,
        ).fetchval() == 0:
            cursor.execute(
                "INSERT dbo.FellowshipCall "
                "(FellowshipCallId, CallCode, DisplayName, CallStatus, "
                "ApplicationDeadlineUtc, ApplicantReviewDeadlineUtc, SettingsJson) "
                "VALUES (?, N'EHF-PILOT', N'EHF synthetic applicant pilot', 'OPEN', "
                "?, ?, N'{\"syntheticOnly\":true}')",
                PILOT_CALL_ID,
                datetime(2099, 12, 30, tzinfo=UTC),
                datetime(2099, 12, 31, tzinfo=UTC),
            )
        if cursor.execute(
            "SELECT COUNT_BIG(*) FROM dbo.Applicant WHERE ApplicantId=?", PILOT_APPLICANT_ID
        ).fetchval() == 0:
            cursor.execute(
                "INSERT dbo.Applicant "
                "(ApplicantId, LegalGivenNames, LegalFamilyName, SelfReportedGender) "
                "VALUES (?, N'Synthetic EHF', N'Test Applicant', N'Prefer not to say')",
                PILOT_APPLICANT_ID,
            )
        if cursor.execute(
            "SELECT COUNT_BIG(*) FROM dbo.Application WHERE ApplicationId=?",
            PILOT_APPLICATION_ID,
        ).fetchval() == 0:
            cursor.execute(
                "INSERT dbo.Application "
                "(ApplicationId, FellowshipCallId, ApplicantId, ApplicationStatus) "
                "VALUES (?, ?, ?, 'IMPORTED')",
                PILOT_APPLICATION_ID, PILOT_CALL_ID, PILOT_APPLICANT_ID,
            )
        projection = json.dumps(
            synthetic_projection("synthetic-pilot@example.invalid"),
            sort_keys=True, separators=(",", ":"),
        )
        cursor.execute(
            "IF EXISTS (SELECT 1 FROM dbo.ApplicantPortalBaseline WHERE ApplicationId=?) "
            "UPDATE dbo.ApplicantPortalBaseline SET ProjectionJson=?, "
            "CreatedByIdentity=N'SYNTHETIC_PILOT' WHERE ApplicationId=? ELSE "
            "INSERT dbo.ApplicantPortalBaseline "
            "(ApplicationId, ProjectionJson, CreatedByIdentity) VALUES (?, ?, N'SYNTHETIC_PILOT')",
            PILOT_APPLICATION_ID, projection, PILOT_APPLICATION_ID,
            PILOT_APPLICATION_ID, projection,
        )
        cursor.execute(
            "IF NOT EXISTS (SELECT 1 FROM dbo.DocumentSlot WHERE DocumentSlotId=?) "
            "INSERT dbo.DocumentSlot "
            "(DocumentSlotId, ApplicationId, SlotCode, CreatedByIdentity, "
            "ApplicantUploadMode, ApplicantVisible, SlotLabel, RequiredForCompletion, "
            "UploadReason, OpenedByIdentity, OpenedAtUtc) "
            "VALUES (?, ?, 'ADDITIONAL_DOCUMENT', N'SYNTHETIC_PILOT', 'MISSING', 1, "
            "N'Additional document', 0, N'Optional synthetic pilot upload', "
            "N'SYNTHETIC_PILOT', SYSUTCDATETIME())",
            PILOT_SLOT_ID, PILOT_SLOT_ID, PILOT_APPLICATION_ID,
        )
        existing_pilot = cursor.execute(
            "SELECT ApplicationId, EntraObjectId FROM dbo.ApplicantEntraIdentity "
            "WHERE ApplicationId=? OR EntraObjectId=?",
            PILOT_APPLICATION_ID, pilot_entra_id,
        ).fetchall()
        if existing_pilot and any(
            UUID(str(row[0])) != PILOT_APPLICATION_ID or UUID(str(row[1])) != pilot_entra_id
            for row in existing_pilot
        ):
            raise RuntimeError("The synthetic applicant identity mapping conflicts.")
        if not existing_pilot:
            cursor.execute(
                "INSERT dbo.ApplicantEntraIdentity "
                "(ApplicationId, EntraObjectId, IdentityKind, Enabled, LinkedByIdentity) "
                "VALUES (?, ?, 'SYNTHETIC_TEST', 1, N'SYNTHETIC_PILOT')",
                PILOT_APPLICATION_ID, pilot_entra_id,
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {"verifiedApplicantsLinked": len(mappings), "syntheticApplicantsLinked": 1}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sql-admin-credential", type=Path, required=True)
    parser.add_argument("--provisioning-record", type=Path, required=True)
    parser.add_argument("--pilot-entra-object-id", type=UUID, required=True)
    arguments = parser.parse_args()
    print(json.dumps(activate(
        arguments.sql_admin_credential,
        arguments.provisioning_record,
        arguments.pilot_entra_object_id,
    ), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
