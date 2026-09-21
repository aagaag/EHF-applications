# API-only citation fallback for EHF 2026

## Purpose

Provide usable, fair citation totals for every EHF 2026 applicant after the
OpenAlex cutoff collector was rate-limited. The comparative metric must come
from one complete, explicitly labelled source for the whole cohort. Google
Scholar will not be queried, scraped, or manually reviewed.

## Decision

OpenAlex remains the preferred source. A failed or incomplete OpenAlex run
must leave the currently published metric unavailable rather than fabricate
zeroes or mix sources. The fallback is a complete Semantic Scholar snapshot of
the same verified, `RESOLVED` and `PUBLISHED` publication set. The overview
will label the metric `Semantic Scholar` once that snapshot is activated.

## Data model and activation

Add an append-only cutoff-run record that stores the EHF call, source code,
observation timestamp/cutoff, completed import run, eligible-work count and
the source status. It is activated only after all eligible works have one
`OBSERVED` citation count from the same completed collector/import run. Existing
OpenAlex observations and the current missing-observation guard remain intact.

`GetInternalApplicationMetrics` reads only the active cutoff run. It sums
observed counts for its stated source and returns `NULL` rather than zero when
the active run is absent, incomplete, or has an unmatched eligible work. It never combines OpenAlex, Semantic
Scholar, legacy profile totals, or Google Scholar observations.

## Collection and matching

Extend the existing official-client pipeline with a Semantic Scholar collector:

- DOI-bearing works use the official batch endpoint in bounded batches.
- Works without DOI use paced title search with the applicant family name and
  the existing exact title/year/author match rules.
- A result is `OBSERVED` only after a confident match; an ordinary unmatched
  result is `NOT_FOUND` with its search URL and evidence. API/network/rate-limit
  failure aborts the complete run without producing a snapshot to import. A
  snapshot containing `NOT_FOUND` eligible works may be retained for audit but
  cannot be activated as the comparative metric.
- The snapshot remains outside Git, is validated before database writes, and
  is imported append-only through the existing privileged path.

There is no Google Scholar code path, no CAPTCHA handling, no browser
automation, and no manual queue in this workflow.

## User experience

Until a source run is activated, the overview continues to show citation data
as unavailable. After activation it shows one clearly labelled value, e.g.
`656 (Semantic Scholar)`, for each applicant. Applicant-detail annual citation
charts are shown only for a source that supplies yearly evidence; Semantic
Scholar totals do not invent a year-by-year history.

## Failure handling and audit

Each source run is immutable and records source, timestamp, matching evidence,
and import fingerprint. A failure leaves the prior active cutoff untouched.
An incomplete cohort cannot be activated. Operators can retry a failed source
later without overwriting prior evidence.

## Verification

Tests cover batch and title matching, retries and rate-limit aborts, snapshot
validation, no-mixed-source activation, metric labels and missing-value
behavior. Deployment validates the migration and verifies that the active
cutoff points to a completed run with exactly the eligible-work count before
the overview changes.
