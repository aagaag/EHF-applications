# Trustee Shortlist Implementation Plan

**Goal:** Add a secure, persisted three-column trustee shortlist to the far right of the internal applicant table.

**Architecture:** Store trustee mappings and selections in SQL Server, expose reads and writes only through audited stored procedures, and enforce column ownership using the authenticated Entra object ID at both the route and database boundaries. Render all selections to authorized viewers while enabling only the authenticated trustee's checkbox.

## Tasks

1. Add failing migration and contract tests for migration 037, the three exact object-ID mappings, least-privilege grants, transactional audited writes, and all migration inventories.
2. Implement migration 037 with trustee mapping and selection tables plus read/write stored procedures; update bootstrap/install/test inventories and the database validator.
3. Add failing repository and HTTP tests for loading selections, exact OID authorization, same-origin writes, boolean payload validation, audit-safe persistence, and the Adriano admin-role case.
4. Implement `app/shortlist.py`, inject it through application construction, load it for the internal report, and add the authenticated mutation endpoint.
5. Add failing renderer/browser tests for the grouped `Shortlist` heading, three subcolumns, identity-specific enablement, responsive labels, save/revert/live announcements, and prevention of row-modal activation.
6. Implement table markup, compact responsive CSS, and browser behavior.
7. Run focused tests, the full Python/browser/database suites, deployment WhatIf checks, and security-sensitive diff review.
8. Commit and push `main`, run the production deployment, validate migration 037, and verify the live UI and Adriano-only enabled state without altering production shortlist data.
