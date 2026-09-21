# Applicant Publication Journal Scatter Plot

## Purpose

Add a third publication visualization to every internal applicant-detail modal. The chart helps reviewers compare when an applicant published, the current citation impact of the journal, and the current citations received by each paper without changing the existing publication list or its first-/last-author emphasis.

The feature uses OpenAlex `summary_stats.2yr_mean_citedness`, an open, impact-factor-style source metric. The interface must call it **OpenAlex 2-year journal citedness** and must not label it Journal Impact Factor or imply that it is Clarivate Journal Citation Reports data.

## Approved Visualization

Each paper is represented by one SVG bubble:

- x-coordinate: publication year;
- y-coordinate: the latest imported OpenAlex 2-year mean citedness for the paper's journal;
- bubble area: proportional to the paper's latest verified OpenAlex citation count;
- red outline: the applicant is the first, last, or sole author under the existing author-position rules;
- standard accent fill: all other papers.

Bubble area, rather than radius, is proportional to citations so that visual magnitude remains honest. A paper with zero citations receives the minimum visible radius. A paper with an unavailable citation count also receives the minimum visible radius, uses a dashed outline, and is labelled as citation data unavailable.

The plot uses exact publication-year x positions. It does not jitter points, because jitter would imply a false publication date. Larger bubbles are drawn first so smaller coincident bubbles remain visible where possible. Every point remains individually represented in the accessible fallback list even when SVG points overlap exactly.

## Missing Data

A publication with a known year but no journal metric appears in a separated `N/A` lane below the numeric y-axis. It must not be plotted at zero. Its accessible label explains that OpenAlex journal citedness is unavailable.

A publication without a valid publication year cannot receive an x-coordinate. It is excluded from the SVG and listed immediately below the chart as omitted because its publication year is unavailable. The chart reports the number of plotted and omitted papers.

If no publication has a valid year, the chart renders a compact empty state instead of an SVG. Missing journal metrics or citation counts never prevent the modal from opening.

## Data Source and Provenance

The existing reviewed OpenAlex publication-matching pipeline remains authoritative. For each accepted OpenAlex work, collection records:

- the OpenAlex work identifier;
- the primary journal source identifier and display name;
- whether the source type is `journal`;
- `summary_stats.2yr_mean_citedness` from the corresponding OpenAlex Source record;
- the OpenAlex Source `updated_date` when supplied;
- the collection timestamp;
- the existing paper citation count and citation history;
- hashes and URLs required by the existing append-only evidence contract.

Only an accepted work match with a primary source whose type is `journal` can contribute a journal citedness value. Repositories, conferences, book series, preprint servers, missing sources, malformed values, negative values, and non-finite values produce an unavailable metric rather than a guessed match.

The collector deduplicates source identifiers and fetches each journal source once per collection run. It uses the existing protected OpenAlex API client, request limits, retry rules, and production credential path. No browser request calls OpenAlex.

## Persistence and Database Projection

Journal fields are added to the private OpenAlex snapshot format and imported into the existing append-only OpenAlex citation evidence JSON. This keeps paper citations and the journal metric in the same observed snapshot and avoids a second mutable journal-metrics subsystem.

A new forward-only database migration revises the internal applicant-detail projection to return the latest valid values from the latest accepted OpenAlex observation:

- `JournalOpenAlexId`;
- `JournalOpenAlexName`;
- `JournalTwoYearMeanCitedness`;
- `JournalMetricObservedAtUtc`.

The projection uses `TRY_CONVERT` and returns `NULL` for absent or invalid evidence. It does not fabricate values from journal names and does not fall back to applicant-supplied figures. Existing observation rows remain valid and simply return no journal metric until a new snapshot is imported.

## Rendering and Interaction

The applicant-detail data model gains optional journal metric fields. The server renders the SVG so the modal remains dependency-free and follows the current escaped, data-only rendering pattern.

The figure includes:

- title: `Papers by year and journal citedness`;
- x-axis label: `Publication year`;
- y-axis label: `OpenAlex 2-year journal citedness`;
- a compact legend stating `Bubble area represents OpenAlex citations`;
- a visible snapshot date when at least one metric or citation observation supplies it;
- numeric y-axis ticks beginning at zero;
- integer publication-year ticks over the observed span;
- an `N/A` lane only when needed.

Each bubble is keyboard focusable and contains a `<title>` plus an `aria-label` with the title, journal, year, citedness status/value, citation status/value, and author-position status. The figure also contains a visually compact but screen-reader-readable list with one entry per paper, ensuring coincident points remain distinguishable.

The plot is informational; clicking or activating a bubble does not open a publication. The existing publication rows remain the single interaction for opening papers, avoiding nested or competing controls.

## Layout and Approved Styling

The existing modal structure, identity strip, two bar charts, publication table, colours, typography, and spacing remain unchanged except for the minimum grid adjustment needed to add the third figure.

At wide desktop widths, the three figures occupy one row of equal fluid columns. At 800 CSS pixels or less, they stack in one column under the existing responsive rule. SVG dimensions are fluid, labels do not create horizontal scrolling, and the modal retains its current bounded height and internal scrolling.

First-/last-/sole-author bubbles use the same semantic red already approved for corresponding publication rows, but author position is also stated textually in the accessible label. Missing data uses the existing missing-value colour and textual `N/A`; meaning never depends on colour alone.

## Backfill and Operations

The production rollout creates a fresh private OpenAlex snapshot for every reviewed publication in the 2026 call, imports it through the existing root-mediated workflow, and preserves invitations and production mail as disabled.

The import and collector remain idempotent. Re-running with identical evidence creates no duplicate active observation. A future refresh can repeat the same collection/import workflow when OpenAlex updates its source metrics; no live request or recurring scheduler is added by this feature.

Production verification reports:

- total reviewed publications;
- accepted OpenAlex work matches;
- publications with a journal source;
- publications with a valid 2-year citedness value;
- publications in the `N/A` lane;
- publications omitted for missing year;
- invalid or non-journal source counts;
- the latest observation timestamp.

## Security and Privacy

The chart is available only through the existing authorized internal applicant-detail route. It does not change route authorization, applicant visibility, document access, invitation gates, or outbound mail settings.

OpenAlex receives only the identifiers already used by the existing citation collector. The browser receives only the internal projection needed to render the modal. Private snapshots, API credentials, applicant source documents, and import outputs remain outside Git.

## Verification

Implementation follows test-driven development and includes:

- collector tests for deduplicated source lookups, journal-only acceptance, malformed and missing metrics, and evidence timestamps;
- importer tests for the expanded snapshot contract, append-only evidence, idempotency, and invalid-value rejection;
- migration and SQL validator tests for latest-observation projection and null-safe conversion;
- renderer unit tests for coordinates, area scaling, exact-year placement, draw order, `N/A` handling, omitted-year reporting, escaping, author outline, and accessible labels;
- browser tests at 1920×1080, 1366×768, tablet, and phone widths, including keyboard focus, all four skins, no horizontal overflow, and preservation of the existing publication interaction;
- a full repository test run;
- production import, migration, service, authorization, mail/invitation-gate, category-count, and live modal-data verification after deployment.

## Non-Goals

- Clarivate Journal Impact Factor or Journal Citation Reports integration;
- SCImago Journal Rank;
- using a journal-level metric to score or rank applicants;
- a live browser-to-OpenAlex integration;
- automatic recurring refreshes;
- changing publication matching, citation-source precedence, or the existing publication table sorting;
- altering application, curriculum, or publication-list PDF artifacts.
