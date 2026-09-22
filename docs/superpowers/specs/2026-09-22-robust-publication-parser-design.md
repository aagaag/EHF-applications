# Robust Applicant Publication Parser Design

## Purpose

Replace the one-off, manually transcribed publication repair process with a reproducible parser that scans every PDF in every EHF applicant folder, detects applicant-authored publication entries across heterogeneous CV and publication-list layouts, extracts bibliographic fields without assuming a fixed field order, and reconciles the result into the existing append-only publication manifest.

The parser is an administrative batch workflow. Applicant PDFs and extracted citation text remain local and outside Git. Only source code, de-identified fixtures, rules, and operator documentation are committed.

## Root Cause

The application has a strict publication-manifest loader and audited database importer, but no maintained upstream PDF publication parser. The previous low-count repair was a private script containing hard-coded `Record(...)` calls. The initial manifest therefore combined several brittle behaviors:

- line/year heuristics failed when a year was rendered in a separate column or with character spacing;
- page text without reliable line breaks caused adjacent citations to merge;
- contact headers, footers, research highlights, and narrative text became false publications;
- CV publication sections embedded in combined applications were missed;
- bibliographic resolution was treated as DOI resolution, and the importer automatically marked only DOI-resolved rows as `PUBLISHED`.

The last behavior explains Andreas Panagopoulos: the source list yielded seventeen candidate rows, but only five DOI-resolved rows were displayed as published. Publication status and identifier resolution are different facts and must be modeled separately.

## Evidence From the 2026 Corpus

The source tree contains 153 PDFs and 596 pages. Four PDFs have no extractable text and one legacy PDF is empty; none of those five is a dedicated publication list. Ninety-eight PDFs mention publication-related words, so keyword-only document selection would generate many false positives. Dedicated publication filenames account for only twenty-one PDFs, so filename-only selection would miss publication sections embedded in CVs and combined applications.

Representative layouts include:

- year in a left column with multi-line citations (Blaž Burja);
- blank-line-separated citations without leading years (Andreas Panagopoulos);
- tightly set CV entries where the year terminates each citation (Daphné Chopard);
- bullet-delimited entries (Shayan Shami Pour);
- numbered lists followed by submitted and in-preparation sections (Carine Roese Mores).

## External Parser Research

The design follows established reference-parsing practice while adapting it to applicant CVs rather than journal-article bibliographies:

- GROBID separates document/reference segmentation from citation field parsing, preserves raw citations, exposes PDF coordinates, and supports parsing isolated reference strings. Its official documentation reports strong citation-field performance and provides a local REST API: <https://grobid.readthedocs.io/en/latest/Introduction/> and <https://grobid.readthedocs.io/en/latest/Grobid-service/>.
- ParsCit models citation parsing as sequence labeling plus heuristic reference-string discovery, which supports the same separation of entry finding and field labeling: <https://clgiles.ist.psu.edu/pubs/LREC2008-ParsCit.pdf>.
- CERMINE preserves layout/zones and parses isolated reference strings, reinforcing the need to retain both raw text and geometric/section evidence: <https://github.com/CeON/CERMINE>.
- AnyStyle exposes separate finder and parser models and supports task-specific retraining: <https://github.com/inukshuk/anystyle>.
- Comparative research found substantially higher recall from machine-learned field parsers than rules alone and consistent gains from task-specific training: <https://arxiv.org/abs/1802.01168> and <https://aclanthology.org/2020.wosp-1.4/>.

No applicant PDF is sent to a public parsing service. GROBID runs locally from a pinned container, and only already-segmented citation strings are sent to its loopback API.

## Architecture

The pipeline has six explicit stages.

1. **Inventory and text extraction.** Hash and inspect every PDF under every applicant folder. Extract both ordinary and layout-preserving text per page with `pypdf`. Prefer layout text when it materially restores line structure; prefer ordinary text when layout extraction collapses word spacing. Record empty, unreadable, and extraction-degraded documents in the audit.
2. **Publication-region detection.** Detect dedicated publication documents and publication-related CV sections. Section headings are normalized independently of whitespace and typography. Research-plan `References`, recommendations, talks, awards, grants, and ordinary narrative sections are excluded.
3. **Entry segmentation.** Join wrapped lines and split entries using an ensemble of bullets/numbers, blank vertical groups, year columns, indentation resets, terminal year/DOI/page evidence, and cross-page continuation. Repeated headers, footers, page numbers, legends, and explanatory prose are excluded before segmentation.
4. **Field parsing.** Send isolated candidate strings to a loopback-only GROBID `/api/processCitation` endpoint and parse TEI into authors, title, journal/proceedings container, volume, issue, pages/article number, year, DOI, URL, and raw citation. A deterministic fallback extracts identifiers, years, and conservative title/author/container spans when GROBID is unavailable or incomplete.
5. **Recognition and status classification.** Score a candidate from independent evidence rather than a fixed field order. Classification is separate from metadata/DOI resolution.
6. **Reconciliation and manifest generation.** Match candidates to existing works by DOI first and then by strict normalized-title, applicant-author, and compatible-year evidence. Preserve manual decisions, append new source occurrences, add genuinely missing works, promote high-confidence pending classifications, and leave ambiguous candidates in `PENDING_REVIEW`. Recompute and validate the complete self-hashed manifest.

## Publication Recognition Rules

A candidate is eligible only when it is inside a publication-bearing document/section and contains the applicant's family-name variant in the apparent author material or a structured parser author field. Truncated author lists using `et al.`, ellipses, or equivalent markers are valid.

The positive evidence set is order-independent:

- applicant authorship;
- a title-like span of at least four lexical tokens;
- a plausible publication year;
- a journal, proceedings, book, repository, or other publication venue;
- pages, article/e-location, volume/issue, DOI, PMID, arXiv identifier, or repository identifier;
- a strong section label such as `Peer-reviewed publications`, `Conference papers`, or `Preprints`.

Title, authors, venue, year, and pagination/article identifier are fields to extract, not mandatory positional slots. Pages are optional for preprints, online-first articles, e-location journals, and conference/workshop papers that legitimately omit them. DOI is corroborating evidence, never a prerequisite for publication status.

The following do not become publication rows on their own:

- headings, contact blocks, footers, legends, and explanatory prose;
- research highlights that contain no paper citation;
- presentations, posters, awards, grants, teaching, employment, and recommendation text;
- theses unless explicitly included by policy (the current policy records them as `NON_PUBLICATION`);
- research-plan bibliography entries that are not part of an applicant publication section.

## Status Rules

- `PUBLISHED`: an applicant-authored paper or chapter in a journal, proceedings, or published book, including records without a DOI when title, authorship, venue, and year are sufficiently evidenced.
- `ACCEPTED_PREPRINT`: explicit preprint/repository records and manuscripts marked accepted, submitted, under review, or in revision that are not evidenced as the final published version.
- `UNDER_PREPARATION`: explicit in-preparation work.
- `NON_PUBLICATION`: confirmed headings/fragments, theses under the present policy, or historical malformed extraction rows.
- `PENDING_REVIEW`: conflicting, incomplete, or low-confidence candidates. This is the only permitted outcome when the evidence cannot support an affirmative classification.

Peer-reviewed conference and workshop papers count as `PUBLISHED` when the source states peer review or supplies a proceedings/conference venue and year. A separate arXiv/bioRxiv/medRxiv/SSRN version is `ACCEPTED_PREPRINT` unless it reconciles to an already published version of the same work.

## Confidence and Fail-Closed Behavior

Every field and final classification carries machine-readable evidence. Automatic `PUBLISHED` requires applicant authorship, title, venue, year, and either a strong section label or identifier/pagination evidence. Automatic `ACCEPTED_PREPRINT` requires applicant authorship, title, year, and an explicit preprint/submission signal. Missing or conflicting evidence becomes pending.

The pipeline never deletes a database publication. Superseded malformed records receive append-only `NON_PUBLICATION` review events. Existing non-null canonical fields remain immutable; conflicts are recorded for review.

## Privacy, Provenance, and Idempotency

- Source PDFs, extraction reports, raw citation manifests, and audit CSV files remain outside the repository.
- Every document audit records a relative locator, SHA-256 hash, page count, extraction method, pages inspected, detected sections, candidate count, and issue codes.
- Every candidate records source hash, page range, line range, raw citation, normalized citation, segmentation evidence, parsed fields, confidence, and status evidence.
- Stable content-derived identifiers make reruns idempotent.
- Public metadata services may receive DOI or title queries, but never full applicant PDFs or unrelated dossier text.

## Validation Contract

Unit tests use synthetic, de-identified layouts for all five representative formats plus cross-page continuations, truncated authors, missing pages, article numbers, preprints, in-preparation works, header/footer false positives, and research-plan references.

Corpus validation must prove:

- all 153 source PDFs are audited;
- every applicant folder is represented;
- empty/unreadable documents are explicitly accounted for;
- all existing source-backed works are either rediscovered or explained;
- no applicant's accepted published/preprint count decreases without explicit supersession evidence;
- every new affirmative row contains the applicant author plus title, venue, and year evidence;
- every unmatched or conflicting candidate is pending, not silently discarded;
- the generated manifest passes the strict loader, relationship, uniqueness, self-hash, and idempotency checks;
- database apply preserves append-only evidence and leaves invitations/mail disabled.

The 2026 corpus audit remains private. Only aggregate counts and non-sensitive failure codes enter deployment documentation.

## Deployment and Rollback

Parser code and importer semantics deploy through the existing atomic application release workflow. GROBID is an operator dependency for extraction, not a new public production service. The generated private manifest is plan-validated before privileged apply. After apply, publication, review-disposition, overview-count, and applicant-detail verification must pass.

Rollback uses the existing application release symlink rollback. Database evidence is append-only: a faulty classification is corrected with a later review event, never destructive deletion. A generated manifest is retained outside Git by content hash so the exact operation can be audited or rerun.
