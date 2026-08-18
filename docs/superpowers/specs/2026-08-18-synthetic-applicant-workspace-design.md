# Synthetic Applicant Workspace Design

## Purpose

Provide an administrator-only way to create a clearly synthetic fellowship application and exercise the existing applicant form with production-equivalent validation. The workflow is for interface and data-quality testing only. It must not create or modify Entra identities, send invitations, expose or mutate real applicant records, or allow synthetic values to enter operational reports and approval queues.

## Security boundary

- Only a live member of `EHF-Administrators` may create or open a synthetic workspace.
- Creation accepts no application, applicant, email, Entra object, or record identifiers from the browser. SQL generates all identifiers and inserts the synthetic marker in the same transaction as the applicant, application, baseline, and session.
- `ApplicantSyntheticWorkspace` is the authoritative marker. Names, call settings, application status, and identity-kind strings are never sufficient to classify a record as synthetic.
- The synthetic applicant session is bound to the authenticated administrator's stable Cloudflare identity. Every applicant page and API request revalidates the same live administrator group and exact actor identity.
- Existing applicant sessions remain bound to one enabled Entra identity and application. A synthetic session cannot be used for a real application, and a real applicant session cannot open a synthetic workspace.
- Migration 019 preserves the legacy `GetApplicantSession` result contract and makes it ignore synthetic sessions. The current release uses a versioned session procedure; rollback therefore fails closed for synthetic sessions.

## Data and workflow

The administrator workspace adds one complete-card action, `Create synthetic applicant and open form`. The action calls a same-origin POST endpoint. SQL creates a new application under a dedicated synthetic-only call, stores a neutral empty baseline, creates the administrator-bound synthetic session, and returns the applicant review URL. The response sets the existing secure session and CSRF cookies before navigation.

The applicant form remains the canonical field renderer, validation client, autosave flow, degree editor, DOI lookup/confirmation flow, and section-confirmation flow. A persistent banner identifies `Synthetic test — administrator session`. The session probe exposes only the boolean synthetic state; it never exposes the actor identity or internal identifiers.

Synthetic workspaces may save and confirm the five form sections. They may read the final-review projection for visual inspection, but they may not upload or download applicant documents, submit a final confirmation, enter approval queues, be promoted into authoritative applicant tables, create access requests or Entra mappings, receive invitations, or appear in operational metrics and exports. The interface removes or disables unavailable actions and the server remains authoritative.

## Database contracts

Migration 019 adds:

- `ApplicantSyntheticWorkspace(ApplicationId, CreatedByIdentity, CreatedAtUtc, ClosedAtUtc)` with a one-to-one application foreign key and nonempty actor constraint.
- `ApplicantSession.SyntheticActorIdentity`, with exactly one authentication source among invitation, Entra, and synthetic administrator.
- `CreateSyntheticApplicantWorkspace`, which requires the exact administrator group, generates all identifiers server-side, creates the dedicated synthetic call if needed, inserts the neutral baseline and synthetic session atomically, and records an immutable audit event.
- `GetApplicantSessionV19`, which returns the session's synthetic actor after confirming that the workspace is open and actor-bound. The legacy session procedure excludes synthetic sessions.
- report, preview, approval, and invitation/provisioning procedure guards that use `ApplicantSyntheticWorkspace`, not name or call-code inference.

The runtime receives EXECUTE only on the new bounded procedures and remains denied direct table DML.

## Interface and accessibility

The internal card follows the shared ISAB card-control rule and is omitted for trustees. The applicant banner is textual, visible in every skin, and announced before the page heading. Existing keyboard, focus, responsive, and four-skin behavior is preserved. The form continues to show the exact applicant-viewpoint layout.

## Testing and completion

Tests must prove administrator creation and exact actor binding, neutral trustee/nonmember denial, no browser-selected identifiers, cross-application isolation, rollback fail-closed behavior, blocked documents/final submission, exclusion from reports and approval queues, no Entra/invitation/mail effects, session revocation after workspace closure, and browser accessibility/responsiveness. The production workflow then creates one fantasy applicant and enters every field plus ten independently verified real biomedical DOIs through the in-app browser. Invitation and production-mail flags remain false throughout.
