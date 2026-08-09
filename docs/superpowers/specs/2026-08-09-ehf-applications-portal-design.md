# Ernst Hadorn Foundation Charles Weissmann Fellowships Portal

## Design specification

Date: 9 August 2026  
Status: Approved design consolidated for user review  
Repository: `aagaag/EHF-applications`  
Production hostname: `ehf.isab.science`

## 1. Purpose

The Ernst Hadorn Foundation needs a secure web application that enables the 36 applicants in the 2026 Charles Weissmann Fellowships call to review, correct, complete, and explicitly confirm their application data. The portal must also let each applicant view and download only the documents that the applicant supplied personally, while ensuring that recommendation letters and other confidential material are never disclosed to applicants.

The first release is a remediation and completeness workflow for the closed 2026 call. Its architecture and data model must be reusable for later calls. A future release will accept new applications from the outset and will collect referee details from applicants so that the Foundation, rather than the applicant, initiates each confidential recommendation request.

## 2. Scope

### 2.1 First-release outcomes

The first release shall:

1. Import the 36 existing applicant records and submitted files from the 2026 call materials.
2. Separate applicant-visible documents from confidential recommendations and internal material before any invitation is issued.
3. Give each applicant secure access to one personalized application record.
4. Require the applicant to review and explicitly confirm or correct all applicant-facing data, not merely missing fields.
5. Allow controlled uploads of missing documents and administrator-authorized replacements without overwriting originals.
6. Provide an internal administration portal with the applicant table, completeness management, communications, audit history, exports, and two scatter plots.
7. Support secure internal access for the Foundation president, administrator, and trustees through EHF-specific groups in the ISAB Microsoft Entra tenant.
8. Run on the ISAB01 server, using the existing Microsoft SQL Server and local encrypted document storage.
9. Publish the portal as `ehf.isab.science` through Cloudflare Tunnel and Cloudflare security controls.

### 2.2 Explicit non-goals for the first release

The first release shall not:

- provide selection-committee access;
- create scoring, ranking, voting, or interview-management features;
- implement the future referee-request portal;
- permit applicants to replace closed-call documents freely;
- create Microsoft Entra identities for applicants;
- move application data or documents to cloud application storage.

The Entra group for a future selection committee may be created now, but it shall receive no application assignment or portal authorization.

## 3. Users, identity, and authorization

### 3.1 Applicants

Applicants authenticate using a two-part process:

1. A personalized invitation URL contains a high-entropy opaque token and no name, email address, or other personal data.
2. Before any application data or document is displayed, the applicant must obtain and enter a one-time verification code sent to the registered applicant email address.

Invitation tokens are stored only as hashes, are revocable, and expire at a configured deadline. Verification codes are single-use, short-lived, hashed at rest, rate-limited, and never written to application logs. The verification screen reveals no applicant identity until verification succeeds.

An authenticated applicant may access exactly one application record. Authorization is enforced server-side for every data query and file download; knowledge of another record identifier never grants access.

### 3.2 Internal users

Internal users authenticate through the ISAB Microsoft Entra tenant. External trustees are onboarded as B2B guests and continue using their existing professional or personal identities. Conditional Access shall require multifactor authentication for the EHF application.

The authoritative security groups are:

- `EHF-Applications-Administrators`: Adriano Aguzzi and Margaryta Schaltegger. Members have full operational rights.
- `EHF-Applications-Trustees`: Ricky Weissman and Magda Polymenidou. Members have read-only access to the full administrative table, reports, applicant documents, confidential recommendation letters, and exports.
- `EHF-Applications-Selection-Committee`: reserved for a later phase and granted no first-release access.

The EHF groups are assigned only to the dedicated EHF enterprise application. They are not general ISAB authorization groups. Application roles are derived from group membership on every sign-in and must also be checked on every protected server operation.

### 3.3 Permission matrix

| Capability | Applicant | Administrator | Trustee | Selection committee |
| --- | --- | --- | --- | --- |
| View own applicant-facing data | Yes | Yes | Yes | No |
| Correct and confirm own data | Yes | On behalf of applicant, audited | No | No |
| View applicant-supplied documents | Own record only | Yes | Yes | No |
| View recommendation letters | Never | Yes | Yes | No |
| Upload a requested missing document | When slot is open | Yes | No | No |
| Replace an existing document | Only when administrator opens slot | Yes | No | No |
| Classify documents | No | Yes | No | No |
| Send invitations or reminders | No | Yes | No | No |
| View table, graphs, and exports | No | Yes | Yes | No |
| Alter records or internal notes | No | Yes | No | No |
| Manage internal identities and roles | No | Yes | No | No |

## 4. Hosting and infrastructure

### 4.1 Origin and data location

The application runs on ISAB01. Structured records, authorization mappings, confirmations, file metadata, communications, and audit events are stored in a dedicated Microsoft SQL Server database named `EHFApplications`.

PDF files are stored outside ordinary database rows in a dedicated encrypted local folder on ISAB01. Only the application service identity and designated backup process may access this folder. SQL Server stores each file's opaque storage key, classification, version, content hash, size, media type, provenance, uploader, and timestamps.

The application runs under a dedicated least-privileged service identity. Its SQL login is restricted to the EHF database and to the minimum required stored operations or schema permissions. The public web process has no administrative rights on ISAB01.

### 4.2 Public ingress

The public hostname is `ehf.isab.science`. DNS is proxied through Cloudflare. A Cloudflare Tunnel connector on the ISAB side creates outbound-only connections to Cloudflare; no public inbound web port or directly reachable origin address is required.

Cloudflare shall provide:

- TLS termination with strict encrypted transport to the origin;
- web application firewall protections;
- distributed denial-of-service protections;
- rate limits for authentication, verification-code, download, and upload endpoints;
- bot protection; and
- Cloudflare Turnstile on verification-code requests, repeated failed verification attempts, and suspicious form submissions.

Turnstile tokens are validated by the server. Cloudflare protections supplement application-side authentication, authorization, validation, and rate limiting; they do not replace those controls.

### 4.3 Backups and recovery

The `EHFApplications` database and encrypted document folder are included in coordinated backups and ISAB01 checkpoints. Recovery procedures must preserve the relationship between database file versions and stored PDF objects. A restore test is required before production invitations and at least once before each annual call.

The application shall expose a health endpoint without personal data. Monitoring shall cover service availability, tunnel status, certificate and secret expiry, failed sign-ins, failed email delivery, rejected uploads, storage capacity, database backup status, and repeated authorization failures.

## 5. Information model

### 5.1 Principal records

The data model contains independently versioned entities for:

- fellowship calls;
- applicants and contact details;
- applications and lifecycle status;
- UZH employment and affiliation;
- qualifications and PhD dates;
- bibliometric information;
- eligibility declarations;
- applicant confirmations;
- the scientific-contribution statement;
- document slots, documents, and document versions;
- confidential recommendations;
- invitations, verification challenges, and sessions;
- correction requests and communications;
- internal notes and verification data;
- internal identities, roles, and group mappings; and
- immutable audit events.

Every imported or entered value records its provenance: imported from the 2026 summary, extracted from a named source document, supplied by the applicant, corrected by an administrator, calculated by the system, or independently verified by the Foundation.

### 5.2 Applicant-facing fields

Applicants review and explicitly confirm or correct the following categories.

#### Identity and contact

- full name;
- preferred name, if different;
- registered email address;
- alternative contact email, if supplied;
- telephone number;
- birth month and year only;
- optional self-reported gender, including `Prefer not to say` and a suitable self-description option.

Gender is never inferred from names, photographs, pronouns, or documents. It does not affect eligibility or evaluation.

#### UZH employment and eligibility

- current UZH institute or department;
- current principal investigator;
- current position title;
- current postdoctoral employment status;
- UZH employment start and expected end dates;
- future UZH start date and proof of employment where the position has not yet begun;
- molecular-life-sciences field or research area;
- percentage of time devoted to clinical work, if any;
- confirmation of at least one first-author or co-first-author paper; and
- other call-specific eligibility declarations defined for the 2026 remediation form.

#### Qualifications and academic age

- highest documented degree category: MD, PhD, or MD/PhD;
- exact PhD completion or conferral date;
- explanatory information for career interruptions when the Foundation elects to collect it in a future call.

Anagraphic age is calculated from birth month and year. Academic age is calculated from the exact PhD date. Both calculations use the call deadline as the reference date and are stored as derived values, never as applicant-entered arithmetic.

#### Publications and identifiers

- number of first-author or co-first-author papers;
- number of last-author or senior-author papers;
- total number of papers;
- h-index;
- applicant-reported total citations;
- ORCID identifier;
- Google Scholar profile URL, or an explicit declaration that no public profile exists; and
- applicant-reported Google Scholar citation total as of the confirmation date.

The Foundation may independently verify bibliometric values. The applicant's value and the Foundation-verified value remain separate so provenance is never lost.

#### Scientific contribution

Each applicant must answer:

> What do you consider your most important contribution to scientific advance to date?

The response is plain text, required for completion, limited to 1,000 characters including spaces, and presented with a live character counter. The interface may explain that 1,000 characters is approximately 200 words, but the enforceable limit is characters.

#### Document checklist

The applicant-facing checklist covers the documents required by the call:

- curriculum vitae;
- publication list;
- research plan;
- cover letter including career plan;
- proof of future UZH employment when applicable; and
- any additional non-confidential document specifically requested by an administrator.

Recommendation letters never appear in the applicant-facing checklist as downloadable files. The applicant may be told only that recommendations are administered separately by the Foundation when such a status is appropriate in a future workflow.

### 5.3 Internal-only fields

The following remain invisible to applicants:

- Google Scholar identity certainty;
- Foundation-verified Google Scholar citation total and verification timestamp;
- staff notes and verification comments;
- document-classification reasoning;
- recommendation letters and referee communications;
- internal completeness exceptions;
- security, fraud, and abuse indicators;
- audit events;
- evaluation, scoring, ranking, and selection information; and
- any selection-committee information added in a later phase.

## 6. Document confidentiality and versioning

### 6.1 Classification

Each stored file has one mandatory classification:

1. `Applicant visible`: material supplied by the applicant for the application and approved for disclosure back to that applicant.
2. `Confidential recommendation`: any recommendation letter or referee submission, regardless of whether it arrived directly from a referee or was forwarded or uploaded by the applicant.
3. `Internal administrative`: material produced or retained by the Foundation that is not applicant-visible.

A recommendation letter is always confidential. Applicant upload or possession does not alter this classification.

Before invitations are enabled, an administrator must review every imported document classification. Filename or automated content analysis may suggest a classification but cannot authorize applicant visibility.

### 6.2 Applicant downloads

An applicant can download each approved applicant-visible document and a combined applicant package PDF containing only applicant-visible material. The combined PDF is generated from the current approved applicant-visible versions and must never contain recommendation letters, internal notes, or hidden metadata.

Every download is authorized server-side and logged. Download URLs are short-lived and cannot be reused as permanent public links.

### 6.3 Corrections

Original 2026 documents are immutable. Applicants may upload only when an administrator has opened a specific missing-document or correction slot. A replacement creates a new version and never deletes or overwrites the original. The record identifies the active version while preserving all earlier versions, hashes, timestamps, uploaders, and reasons for replacement.

Administrators may close a slot, reject an upload, restore a prior active version, or request another correction. Trustees can view versions but cannot change them.

### 6.4 Upload controls

Uploads are restricted to PDF. The server validates extension, media type, file signature, file size, page count, encryption status, and malware-scan result. Rejected files are not made available to any user. Uploaded filenames are treated as display metadata only; storage uses short opaque identifiers.

## 7. Applicant workflow

1. An administrator reviews the imported record, classifications, registered email, and missing fields.
2. The administrator previews the personalized invitation and explicitly sends it.
3. The applicant opens the opaque invitation URL. No personal data is shown.
4. After Turnstile and rate-limit checks, the applicant requests and enters a one-time email code.
5. The applicant sees a dashboard of form sections, required confirmations, document status, and overall progress.
6. Each section shows imported values and their source where helpful. The applicant corrects values and explicitly confirms the section.
7. The applicant reviews and downloads applicant-visible documents and supplies only requested missing or replacement documents.
8. The applicant completes the 1,000-character scientific-contribution statement.
9. A final review page lists all data, documents, declarations, and unresolved items.
10. Final submission records the applicant's confirmation timestamp, data version, document-version set, IP-derived security metadata subject to the privacy policy, and audit event.
11. After final submission, the record is locked for applicant editing unless an administrator reopens a specific section or document slot.

Draft data is saved automatically. Concurrent edits use version checks so a stale browser session cannot overwrite a newer change.

## 8. Administration portal

### 8.1 Overview

The primary administrative surface is an online HTML table based on the 2026 Word register. It is generated from live structured data rather than maintained as a separate report.

The table includes the existing metrics:

- applicant;
- degree;
- anagraphic age;
- academic age;
- optional self-reported gender;
- first-author papers;
- last-author papers;
- total papers;
- h-index;
- applicant-reported total citations;
- ORCID;
- Foundation-verified Google Scholar citations; and
- Google Scholar identity certainty.

It also includes operational columns or views for:

- application status;
- applicant confirmation status;
- completeness percentage;
- missing data count;
- missing applicant-document count;
- recommendation status visible only internally;
- invitation and reminder status;
- last applicant activity;
- outstanding correction requests; and
- 1,000-character contribution statement completion.

Administrators and trustees can search, sort, filter, choose visible columns, and export authorized data to CSV or XLSX. Exports are generated on demand, watermarked or otherwise identified with the exporting user and time where appropriate, and recorded in the audit history.

### 8.2 Record navigation

Each applicant row is a complete keyboard-accessible link to the authorized applicant detail page. The detail page separates applicant-facing data, internal verification, applicant-visible documents, confidential recommendations, communications, and audit history. Trustees see read-only controls; administrators see operational controls.

### 8.3 Scatter plots

The portal generates two live scatter plots using the Foundation-verified Google Scholar citation total on the vertical axis:

1. Google Scholar citations versus anagraphic age.
2. Google Scholar citations versus academic age.

Each plotted point represents one applicant and provides an accessible tooltip or adjacent data-table entry containing the applicant name, age value, citation total, and verification date. Records missing either axis value are excluded from the plotted series and listed in a visible `Not plotted because data are incomplete` summary. Filters applied to the table may also be applied to the plots, but the unfiltered call-wide view remains available.

The plots include textual axis labels, legends where needed, keyboard-accessible point information, and a tabular alternative. Meaning never depends on color alone.

### 8.4 Communications

Only administrators can send invitations, verification follow-ups, correction requests, and reminders. Before sending, the portal displays the resolved recipient, sender, subject, HTML body, personalized destination, and attachments. Sending requires an explicit final confirmation and is logged with delivery status.

The application uses a configurable Foundation-approved sender mailbox through a supported API or authenticated mail service. Production sending remains disabled until Adriano Aguzzi approves the exact sender identity and the system has completed a delivery test to an internal address.

Trustees cannot draft, alter, schedule, or send communications.

## 9. User interface and accessibility

Because the application is hosted on `isab.science`, it follows the ISAB shared application shell and accessibility standards while presenting the Ernst Hadorn Foundation and Charles Weissmann Fellowships clearly as the application identity.

The interface shall include:

- the official ISAB logo in the shared shell without alteration;
- application name, `ehf.isab.science`, and a concise purpose statement;
- persistent left navigation on desktop and a labelled drawer at 720 CSS pixels or below;
- accessible native controls, visible focus, keyboard operation, and 44-pixel primary targets;
- Aptos typography unless an authoritative Foundation brand standard specifies otherwise;
- the four required ISAB appearance skins, reduced-motion support, and server-side user preferences;
- readable error, empty, loading, success, and locked states;
- explicit text labels and icons where useful, never color alone;
- no adjacent red and green opposing controls;
- responsive, full-width record layouts with approximately three-percent side margins and no horizontal page overflow; and
- internal authorization pills generated from the same Entra-group inventory used for server authorization.

Long records reflow into labelled card sections at narrow widths. Any rounded record or destination card is one semantic, keyboard-accessible control without a redundant nested `Open` link.

Applicant pages use plain language and show only the steps relevant to that applicant. Internal terminology, hidden-field existence, storage paths, and recommendation filenames are not revealed.

## 10. Security and privacy controls

The application shall implement:

- deny-by-default authorization on every route, query, and file operation;
- secure, HTTP-only, same-site session cookies with rotation, inactivity timeout, and absolute expiry;
- protection against cross-site request forgery, injection, broken object authorization, clickjacking, and unsafe redirects;
- strict input validation and output encoding;
- Content Security Policy and other appropriate security headers;
- per-account, per-token, per-IP, and global rate limits for sensitive endpoints;
- opaque identifiers in public URLs;
- encryption in transit and at rest using the existing ISAB01 security baseline;
- redaction of tokens, codes, personal data, and document contents from logs;
- immutable audit events for authentication, access, changes, classifications, downloads, exports, communications, and administrative actions;
- least-privileged SQL and filesystem access;
- dependency and operating-system patching throughout the year, not only during the call;
- upload quarantine and malware scanning;
- encrypted backups and tested restoration; and
- a privacy notice identifying the Ernst Hadorn Foundation as the application owner/data controller and ISAB as the technical host, subject to the final legal allocation approved by the two foundations.

The first release preserves the 2026 records and does not automatically delete application material. Destruction or anonymization requires a separately approved retention schedule and a logged administrator action; the implementation must support such a policy without requiring schema redesign.

## 11. Import and reconciliation for the 2026 call

The import process is repeatable and idempotent. It shall:

1. Create one application for each of the 36 rows in the approved 2026 register.
2. Match each register row to exactly one applicant folder.
3. Inventory every file recursively, including files stored below synchronized-folder link structures.
4. Calculate a cryptographic hash for each source file.
5. Import structured register values with provenance and preserve `not reported` as missing data, not zero.
6. Suggest document classifications from filenames and content, but require administrator approval before applicant visibility.
7. identify duplicate files by hash without silently discarding them;
8. reconcile applicant names, emails, document counts, and required-document slots;
9. produce an import exception report; and
10. prevent invitation sending until the applicant's registered email and every document classification have been reviewed.

The original SharePoint-synchronized call folder remains an authoritative source artifact and is never modified by import. The portal stores its own controlled copies and source references.

## 12. Error handling

- Invalid, expired, or revoked invitation links produce the same neutral response and reveal no applicant identity.
- Repeated verification failures trigger progressively stricter rate limits and Turnstile challenges without confirming whether an email address exists.
- Email-delivery failures remain visible to administrators with safe retry controls; trustees see status only.
- Database or storage failures do not produce partial confirmations. Transactions preserve record consistency, and document activation occurs only after successful storage, scan, hash, and metadata commit.
- Upload errors preserve the applicant's form draft and state exactly what action the applicant can take.
- If a concurrent change is detected, the later user is shown the current saved value and must reconcile rather than overwrite silently.
- Applicant-facing errors contain no stack traces, internal identifiers, paths, recommendation status, or infrastructure information.

## 13. Verification and acceptance tests

Before production use, the implementation must pass:

1. A 36-record import reconciliation with no unmatched or duplicated application.
2. A complete permission-matrix test for applicants, both administrators, both trustees, and the inactive selection-committee role.
3. Explicit negative tests proving that recommendation letters cannot be listed, inferred, downloaded, or reached by applicants, including guessed URLs and forwarded sessions.
4. Verification that each applicant can reach only their own record and approved files.
5. Tests for expired, reused, revoked, forwarded, and brute-forced invitation and verification tokens.
6. Tests confirming original-document immutability and complete replacement history.
7. Validation of all table calculations, missing-value handling, exports, and both scatter plots against the approved source register.
8. Accessibility testing for keyboard use, screen-reader labels, focus order, contrast, reduced motion, and graph alternatives.
9. Responsive testing at representative desktop, tablet, and phone widths with no horizontal page overflow.
10. Cloudflare Tunnel fail-closed behavior, WAF/rate-limit behavior, and origin-bypass tests.
11. Upload validation, malware-test-file rejection, storage authorization, and download logging.
12. Entra B2B onboarding, group-role mapping, MFA enforcement, removal, and access-revocation tests.
13. Backup and full restore of SQL records plus all document versions into an isolated recovery environment.
14. A pilot using non-production identities and synthetic application documents before any real applicant invitation.
15. Final administrator review of every 2026 email address and every document classification.

## 14. Future-call extension

The architecture shall support a later new-application phase without changing the first-release confidentiality model. For a future call:

1. Applicants create and submit structured applications before the deadline.
2. Applicants provide each referee's name, institution, relationship, and email address.
3. Applicants cannot upload, send, or initiate recommendation letters.
4. An authorized Foundation administrator reviews the referee details and initiates the recommendation request.
5. Each referee receives a separate secure invitation and submits directly to a confidential recommendation record.
6. Applicants never see recommendation contents or filenames, even if they previously possessed or forwarded a letter.
7. The Foundation controls reminders, replacement requests, deadlines, and closure of referee submissions.

Selection-committee access, scoring, and interview workflows require their own design review before activation.

## 15. Delivery sequence

Implementation should proceed in bounded phases:

1. Repository, application skeleton, automated tests, and configuration model.
2. SQL schema, migrations, encrypted document-store adapter, and audit subsystem.
3. ISAB Entra application registration, EHF groups, internal authentication, and role enforcement.
4. Cloudflare hostname, Tunnel, WAF, rate limits, and Turnstile integration.
5. Idempotent 2026 importer, document-classification review, and exception reporting.
6. Administration table, record detail, communications controls, exports, and scatter plots.
7. Applicant invitation, email verification, review form, document downloads, controlled uploads, confirmations, and contribution statement.
8. Security, accessibility, responsive, recovery, and synthetic pilot testing.
9. Administrator review of the 36 production records, followed by explicit approval before invitations are enabled.

No production applicant email is sent automatically by deployment or import.

## 16. Definition of first-release completion

The first release is complete only when:

- all 36 applications are imported and reconciled;
- every document is classified and confidential recommendations are proven inaccessible to applicants;
- the four internal users are securely onboarded with the approved roles;
- the live table and both scatter plots match verified source data;
- applicants can review, correct, complete, download, and confirm their authorized material;
- controlled missing-document and replacement workflows preserve originals;
- audit, export, communication, backup, recovery, and security tests pass;
- `ehf.isab.science` is reachable only through the approved Cloudflare path; and
- Adriano Aguzzi explicitly authorizes production invitation sending after reviewing the final imported records and email template.

## 17. Authoritative sources reviewed

- Ernst Hadorn Foundation fellowship page: <https://ernsthadorn-foundation.org/fellowships/>
- 2026 applicant metrics register: `Call_2026_applicant_metrics.docx`
- 2026 applicant folders under the Foundation's synchronized call directory
- Microsoft Entra B2B collaboration and guest MFA documentation
- Cloudflare Tunnel, origin protection, and Turnstile documentation

