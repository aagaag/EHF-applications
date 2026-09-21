# Report Legends Implementation Plan

**Goal:** Add complete, compact explanations to every overview and applicant-modal graph while preserving existing graph behavior and layout.

**Architecture:** Render semantic legend markup inside each chart figure. Reuse small helper renderers for repeated H-index and interaction explanations, and style the legends through the existing report/chart CSS. Because the full-page modal view clones each figure, no separate full-page implementation is needed.

## Tasks

1. Add failing unit/browser assertions for the axes, color scales, bubble sizing, callouts, unavailable states, bar meanings, and full-page legend cloning.
2. Add semantic legend helpers to `app/internal_preview.py` and `app/applicant_detail.py` and attach them to all six graph figures.
3. Add compact responsive legend styling to `public/assets/site.css` without changing plot dimensions.
4. Run focused renderer and browser tests, then the full Python and browser suites.
5. Include the changes in the coordinated production deployment and verify every legend on the live overview and modal/full-page views.
