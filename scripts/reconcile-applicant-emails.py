#!/usr/bin/env python3
"""Extract high-confidence applicant email candidates without logging PII."""

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pyodbc
from pypdf import PdfReader

from app.documents.keys import load_keyring
from app.documents.store import (
    EncryptedObjectStore,
    ObjectBinding,
    StoredObjectRecord,
)


EMAIL_RE = re.compile(
    r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+",
    re.IGNORECASE,
)
SAFE_OUTPUT = Path("/root/ehf-applicant-email-candidates.json")


def normalized_name(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_value.lower())


def candidate_is_high_confidence(
    email: str,
    *,
    given_names: str,
    family_name: str,
    document_count: int,
    found_in_cv: bool,
    total_unique_emails: int,
) -> bool:
    local = normalized_name(email.split("@", 1)[0])
    given = normalized_name(given_names)
    family = normalized_name(family_name)
    name_match = (
        (len(family) >= 4 and family in local)
        or (len(given) >= 3 and given in local)
        or bool(given and family and local.startswith(given[0] + family))
    )
    return document_count >= 2 or (found_in_cv and name_match) or (
        name_match and total_unique_emails == 1
    ) or total_unique_emails == 1


def candidate_score(
    email: str, *, given_names: str, family_name: str,
    document_count: int, found_in_cv: bool,
) -> int:
    local = normalized_name(email.split("@", 1)[0])
    given = normalized_name(given_names)
    family = normalized_name(family_name)
    return (
        document_count * 100
        + (40 if found_in_cv else 0)
        + (30 if len(family) >= 4 and family in local else 0)
        + (20 if len(given) >= 3 and given in local else 0)
    )


def _connection(password_path: Path):
    password = password_path.read_text(encoding="utf-8").strip().replace("}", "}}")
    if not password:
        raise RuntimeError("The SQL administrator credential is unavailable.")
    return pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        "SERVER=tcp:127.0.0.1,1433;DATABASE=EHFApplications;UID=sa;"
        f"PWD={{{password}}};Encrypt=yes;TrustServerCertificate=yes;",
        autocommit=True,
    )


def reconcile(password_path: Path, keyring_path: Path, output: Path) -> dict[str, int]:
    if output != SAFE_OUTPUT:
        raise RuntimeError("The protected reconciliation output path is fixed.")
    connection = _connection(password_path)
    try:
        rows = connection.execute(
            "SELECT application_row.ApplicationId, applicant_row.LegalGivenNames, "
            "applicant_row.LegalFamilyName, document_row.DocumentType, "
            "document_row.DocumentId, version_row.DocumentVersionId, "
            "object_row.StoredObjectId, object_row.ObjectKey, object_row.KeyVersion, "
            "object_row.EnvelopeVersion, object_row.AesGcmNonce, "
            "object_row.PlaintextSha256, object_row.CiphertextSha256, "
            "object_row.ByteSize FROM dbo.Application AS application_row "
            "JOIN dbo.Applicant AS applicant_row ON applicant_row.ApplicantId = "
            "application_row.ApplicantId JOIN dbo.DocumentSlot AS slot_row ON "
            "slot_row.ApplicationId = application_row.ApplicationId "
            "JOIN dbo.Document AS document_row ON document_row.DocumentSlotId = "
            "slot_row.DocumentSlotId JOIN dbo.DocumentVersion AS version_row ON "
            "version_row.DocumentVersionId = slot_row.ActiveDocumentVersionId "
            "JOIN dbo.StoredObject AS object_row ON object_row.StoredObjectId = "
            "version_row.StoredObjectId WHERE document_row.DocumentType <> "
            "'RECOMMENDATION_LETTER' ORDER BY application_row.ApplicationId"
        ).fetchall()
    finally:
        connection.close()

    store = EncryptedObjectStore(Path("/var/lib/ehf/documents"), load_keyring(keyring_path))
    applications: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "names": ("", ""),
            "documents": defaultdict(set),
            "types": defaultdict(set),
            "errors": 0,
        }
    )
    for row in rows:
        application_id = str(row[0])
        state = applications[application_id]
        state["names"] = (str(row[1]), str(row[2]))
        try:
            binding = ObjectBinding(
                UUID(application_id), UUID(str(row[4])), UUID(str(row[5])), UUID(str(row[6]))
            )
            record = StoredObjectRecord(
                str(row[7]), int(row[8]), int(row[9]), bytes(row[10]), bytes(row[11]),
                bytes(row[12]), int(row[13]),
            )
            reader = PdfReader(BytesIO(store.decrypt_bytes(record, binding)), strict=False)
            text = "\n".join((page.extract_text() or "") for page in reader.pages[:8])
            for email in {match.group(0).lower() for match in EMAIL_RE.finditer(text)}:
                state["documents"][email].add(str(row[5]))  # type: ignore[index]
                state["types"][email].add(str(row[3]))  # type: ignore[index]
        except Exception:
            state["errors"] = int(state["errors"]) + 1

    results = []
    counts = {"applications": len(applications), "resolved": 0, "ambiguous": 0,
              "unresolved": 0, "decryptErrors": 0}
    for application_id, state in applications.items():
        given, family = state["names"]  # type: ignore[misc]
        documents = state["documents"]  # type: ignore[assignment]
        types = state["types"]  # type: ignore[assignment]
        candidates = [
            email for email, document_ids in documents.items()
            if candidate_is_high_confidence(
                email, given_names=given, family_name=family,
                document_count=len(document_ids), found_in_cv="CV" in types[email],
                total_unique_emails=len(documents),
            )
        ]
        ranked = sorted(
            ((candidate_score(
                email, given_names=given, family_name=family,
                document_count=len(documents[email]), found_in_cv="CV" in types[email],
            ), email) for email in candidates),
            reverse=True,
        )
        email = ranked[0][1] if len(ranked) == 1 or (
            len(ranked) > 1 and ranked[0][0] - ranked[1][0] >= 60
        ) else None
        category = "resolved" if email else "ambiguous" if candidates else "unresolved"
        counts[category] += 1
        counts["decryptErrors"] += int(state["errors"])
        results.append({
            "applicationId": application_id,
            "email": email,
            "uniqueEmailCount": len(documents),
            "candidateCount": len(candidates),
            "emailDocumentTypes": sorted({
                document_type for email_types in types.values()
                for document_type in email_types
            }),
        })

    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(results, handle, separators=(",", ":"))
    os.chmod(output, 0o600)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sql-admin-credential", type=Path, required=True)
    parser.add_argument("--keyring", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=SAFE_OUTPUT)
    arguments = parser.parse_args()
    print(json.dumps(reconcile(
        arguments.sql_admin_credential, arguments.keyring, arguments.output
    ), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
