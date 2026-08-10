# EHF document classification

The importer makes deterministic, review-only suggestions. It does not set document visibility or create an approved classification.

Every imported item starts as `UNREVIEWED`. An administrator must record an explicit classification with their identity and a timezone-aware timestamp before any later workflow may use it. A recommendation signal requires a reason for any non-confidential override.

## Deterministic evidence

The classifier evaluates only normalized filename text and supplied extracted first-page text. It does not use a generative model or a similarity score. Evidence codes identify the matched rule, for example:

- `FILENAME_RECOMMENDATION`, `FILENAME_REFERENCE_LETTER`, or `FILENAME_REFEREE`
- `TEXT_RECOMMENDATION`, `TEXT_REFEREE`, or `TEXT_FORWARDED`
- `CV_SIGNAL`, `PUBLICATION_SIGNAL`, `RESEARCH_PLAN_SIGNAL`, or `COVER_LETTER_SIGNAL`
- `NO_CLASSIFICATION_SIGNAL`

Any recommendation/referee/reference signal takes precedence over ordinary filename signals. This includes a recommendation that was forwarded by an applicant or given an applicant-like filename.

## Confidentiality controls

Suggestions may identify likely `APPLICANT_VISIBLE` or `CONFIDENTIAL_RECOMMENDATION` classifications, but they remain `UNREVIEWED` until human review. A document with a recommendation signal cannot be recorded as `APPLICANT_VISIBLE` by the application classification control. The database document-permissions boundary must independently prohibit `CONFIDENTIAL_RECOMMENDATION` records from applicant projections.

Uncertain material receives an `UNKNOWN` suggestion and no likely visibility class. It remains unavailable to applicants and must be reviewed manually.
