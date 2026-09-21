# Applicant Review Artifacts Design

## Goal

Give an authorised internal reviewer direct access from the applicant modal to three narrowly scoped PDFs: the fellowship application/proposal, the curriculum vitae, and the publication list. Keep the existing track-record content visible and make its publication citation counts sortable.

## Source and extraction rules

The authoritative legacy source is `C:\Users\aag\Stiftung Foundation ISAB\ISAB - Charles Weissmann Foundation\Fellowships\Call 2026`. Source files are immutable. Existing database documents remain preferred when their type and boundaries already match the requested artifact.

For a combined package, a reviewed extraction manifest identifies one or more ordered page ranges from one or more source PDFs:

- `APPLICATION`: only pages describing the proposed fellowship project, research plan, aims, methods, or work programme. A generic cover letter is not sufficient unless it contains the substantive proposal.
- `CURRICULUM`: pages describing education, training, appointments, employment, or current position.
- `PUBLICATIONS`: pages containing the applicant's publication list.

Recommendation letters, referee reports, internal selection material, and administrative correspondence are always excluded. A category with no defensible source pages is unavailable rather than guessed.

## Storage and provenance

Each reviewed extraction is materialised once as a fresh PDF. Pages are copied into a new PDF graph, active content and source metadata are removed, and neutral EHF metadata is added. The result is scanned, encrypted, and stored through the existing document store.

Dedicated closed, non-applicant-upload slots use stable codes `review-artifact-application`, `review-artifact-curriculum`, and `review-artifact-publications`. Their document types remain `RESEARCH_PLAN`, `CV`, and `PUBLICATION_LIST`. A provenance table records the artifact version, category, source document version, ordered segment, inclusive page bounds, source plaintext hash, reviewer identity, and review time. Provenance is append-only.

The import is idempotent by application, category, ordered source ranges, and resulting plaintext hash. It never commits applicant documents, manifests containing applicant names, or import output to Git.

## Internal access API

An authenticated administrator or trustee may request:

`GET /api/internal/applicants/{application_id}/review-artifacts/{category}/view`

where category is `application`, `curriculum`, or `publications`. The endpoint resolves only the dedicated reviewed artifact, records requested/succeeded/failed access through the existing audit path, and returns an inline PDF with a neutral filename. Missing artifacts return 404. It cannot fall back to the full application package.

## Modal behaviour

The modal opens on the existing track-record content. Its tab strip and embedded PDF are removed. An action row contains three links: **Application**, **Curriculum**, and **Publication list**. Each uses `target="_blank"` and `rel="noopener noreferrer"`, and points to the category endpoint for the selected application. A missing artifact is rendered as disabled/unavailable after a lightweight availability response or a 404-safe state.

The track-record publication list becomes a semantic table with Title, Journal/year, and Citations columns. Citation counts come from the existing `Publication.citation_count` value. The Citations heading provides ascending and descending controls, updates `aria-sort`, sorts numerically, preserves stable order for ties, and keeps missing values after observed values in both directions. Publication rows retain their existing double-click and keyboard link behaviour.

## Verification and rollout

Unit tests cover page-range extraction, unsafe-content removal, category validation, authorization, audit outcomes, HTML escaping, citation rendering, and sorting metadata. Browser tests cover the three new-tab links, removal of modal tabs/embed, numeric citation sorting in both directions, missing counts, and accessibility.

Before import, every artifact is checked for a valid PDF, nonzero pages, correct first and last boundary pages, no recommendation signal, and a matching source hash. Production deployment is atomic and preserves the previous release for rollback. After deployment, a read-only audit verifies category coverage without printing applicant names or document text.
