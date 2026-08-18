"""Synthetic-only pilot data that preserves missingness without copying applicant values."""

from __future__ import annotations

from typing import Any


def synthetic_projection(_registered_auth_email: str) -> dict[str, Any]:
    """Return dummy values with the observed absence pattern of the approved pilot source."""
    return {
        "applicant": {
            "fullName": "Synthetic EHF test applicant",
            "preferredName": None,
            "registeredEmail": None,
            "alternativeEmail": None,
            "telephone": None,
            "birthMonth": None,
            "birthYear": None,
            "gender": "Prefer not to say",
            "institute": None,
            "principalInvestigator": None,
            "positionTitle": None,
            "postdoctoralEmploymentStatus": None,
            "employmentStartDate": None,
            "employmentEndDate": None,
            "futureStartDate": None,
            "researchArea": None,
            "clinicalWorkPercent": None,
            "firstAuthorDeclaration": None,
            "degrees": [],
            "firstAuthorPaperCount": 3,
            "lastAuthorPaperCount": 1,
            "totalPaperCount": 8,
            "hIndex": None,
            "applicantReportedCitationTotal": 240,
            "orcid": None,
            "googleScholarProfileUrl": None,
            "hasGoogleScholarProfile": None,
            "publications": [],
            "contributionStatement": None,
            "locked": False,
        },
        "sections": {},
        "documents": (),
    }
