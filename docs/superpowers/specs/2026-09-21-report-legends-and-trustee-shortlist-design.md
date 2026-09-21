# Report Legends and Trustee Shortlist Design

## Scope

This release improves the internal EHF review report in two independent areas: every data graphic receives an explanatory legend, and the applicant overview gains a trustee-specific shortlist control.

## Graph legends

Legends are compact, visible without interaction, responsive, and part of the chart figure so that the full-page chart opened from a modal includes the same explanation.

The three overview charts explain both axes and every visual encoding. The two citation scatterplots identify their equal-sized points, the light-to-deep blue H-index scale with the current minimum and maximum, the red missing-value fallback, and the focus behavior used to read exact values. The age-comparison chart additionally explains that bubble area represents OpenAlex citations and that surname callouts mark the fifteen candidates with the most citations.

The applicant modal charts explain:

- Papers by year: publication year on the x-axis, paper count on the y-axis, and bar height as count.
- Citations by year: citation year on the x-axis, citations received on the y-axis, and bar height as the total received by the candidate's papers.
- Papers by year and journal citedness: publication year on the x-axis, OpenAlex two-year journal citedness on the y-axis, the N/A lane for unavailable journal metrics, bubble area as OpenAlex citations, red for sole/first/last author papers, blue for neither first nor last author papers, and dashed outlines for unavailable citation counts.

The legends do not change plot geometry. Each modal chart remains a mouse- and keyboard-accessible link that opens a full-page copy in a new tab.

## Trustee shortlist

The applicant table ends with a grouped heading named **Shortlist** and three subcolumns named **Ricky**, **Magda**, and **Adriano**. Every authorized internal viewer can see all three selections. Only the trustee represented by a column can change that column.

Authorization is based exclusively on the authenticated Microsoft Entra object ID, not on display name, email, or the canonical admin/trustee role selected by the application:

| Column | Entra object ID |
|---|---|
| Ricky | `7747ffa7-5193-4cc8-9221-08a1dd24b026` |
| Magda | `09d14671-38e1-4763-8d67-512c9787d379` |
| Adriano | `d5c5fb6a-f9c3-456c-97b1-20b450647f8c` |

This identity rule ensures Adriano can always edit his column even when his login resolves to the administrator role. Other administrators, trustees, and collaborators can view selections but cannot edit any column.

Selections are persisted in SQL Server. The browser calls a same-origin authenticated endpoint, and the database stored procedure independently verifies that the supplied Entra object ID is mapped to the requested trustee column. The runtime principal receives procedure execution only, not direct table mutation rights. Each change is transactional and creates an audit event recording the application, trustee column, and before/after state.

Checkbox changes save immediately. A failed save restores the prior value and announces an accessible error. Checkbox interaction never opens the applicant modal. On narrow screens, the cells retain explicit labels such as `Shortlist — Ricky`.

## Verification

Automated coverage includes renderer semantics, keyboard/chart behavior, client save/revert behavior, route authentication and same-origin protection, repository mapping, migration security and audit contracts, and the complete Python/browser/database suites. Production verification confirms the legends, grouped headers, responsive labels, and identity-specific enabled state without changing a trustee's live selection.
