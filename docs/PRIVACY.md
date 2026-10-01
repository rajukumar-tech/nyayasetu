# Privacy, security & ethics

NyayaSetu handles some of the most sensitive personal data there is: identity, criminal allegations, custody, health
and vulnerability of people who are detained and usually unrepresented. Design follows the principles of India's
Digital Personal Data Protection Act, 2023 (purpose limitation, data minimisation, accuracy, storage limitation,
security safeguards, accountability). This document is a design statement, not a legal compliance opinion.

## Purpose limitation
Data is processed only to identify legal routes to release/faster disposal and to prepare filings for legal-aid
lawyers and UTRCs. Analytics exports are aggregate or anonymised. The delay model is used only to order work, never to
decide anything about a person.

## Data minimisation
- Only fields needed for eligibility, identity linking and filings are extracted.
- Religion and caste are never extracted, stored as features, or used by any model. Gender is stored (needed for
  procedural safeguards such as arrest of women at night) and used in the delay model only for fairness evaluation.
- No real prisoner data exists in this repository; all data is synthetic (`data/synthetic/generate.py`).

## Access control (RBAC, enforced server-side)
| Role | Sees |
|---|---|
| legal_aid_lawyer | assigned prisoners only; Defense Insights for them |
| jail_staff | prisoners in their jail; adds prisoners to their jail; eligibility + alerts; **never** Defense Insights |
| dlsa_admin | prisoners in their district; dashboards; prisoner register; adds, approves and deactivates lawyers; assigns lawyers |
| reviewer | review queue items only |
| system_admin | technical work only: staff accounts, password resets, legal data, audit log, monitoring — **no** prisoners (not even the register), lawyer accounts, assignment, documents, Defense Insights or drafts |

Defense Insights are privileged legal strategy, visible only to the assigned lawyer. A lawyer's drafts are visible only
to that lawyer; the superintendent's application drafted by jail staff never includes insight-derived sentences. Only
the assigned lawyer uploads documents. An ID outside a user's scope gets the same "not found" as an ID that does not
exist, and the attempt is audit-logged. Tests 53, 58 and `tests/test_flows.py` cover this.

## Audit
Every view, list, edit, decision, export, merge/un-merge, legal-data verification and denied access is written to the
append-only `audit_log` with user, role, timestamp and before/after values.

## Security
- Documents can be encrypted at rest (Fernet; set `NYAYA_DOCUMENTS_ENCRYPTION_KEY`). Use disk/DB encryption in
  production as well.
- TLS must terminate in front of the API in any deployment.
- Passwords: bcrypt. Sessions: signed JWT (HS256) with expiry. **Before production:** move tokens to httpOnly
  cookies with CSRF protection, add MFA for admins, rotate `NYAYA_JWT_SECRET`.
- Uploads: size limit, type allow-list, SHA-256 de-duplication, password-protected PDFs rejected, name-mismatch warning.

## Retention
Proposed policy: case data retained while the person is an undertrial plus 3 years after final disposal, then deleted
or irreversibly anonymised; audit logs retained 7 years. Deletion jobs are not yet implemented.

## Human in the loop
The system flags, computes and drafts. Lawyers decide what to file; judges decide release. Every result says
"eligible to apply", never "will be released"; every insight and draft carries the not-legal-advice disclaimer.

## Fairness
Entity resolution is tuned for precision because a false merge can make someone appear to be a repeat offender.
Delay-model fairness is reported per district and per defendant-gender field (`ml/reports/delay_model.json`).
