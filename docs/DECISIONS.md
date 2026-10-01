# Decisions

Choices made where the spec left room, recorded so they can be challenged.

**D-001 · All legal data ships `verified: false`.** Section numbers, maxima, compoundability and procedural rules were
entered from general knowledge; the official India Code texts could not be fetched while building (HTTP 403). Nothing
is presented as verified until a `system_admin` checks it (`POST /api/legal/records/{key}/verify`, audit-logged, with
a mandatory note of what was checked). Unverified data downgrades ELIGIBLE / NOT_YET / EXCLUDED_479 to REVIEW.

**D-002 · Demo mode simulates verification — visibly.** With `NYAYA_DEMO_MODE=true` the seed marks every record
verified with `verified_by = "DEMO SEED — simulated verification for the demo only; NOT a legal check"`. The UI shows
"demo-verified only" on each charge and a red count on the admin page. Without demo mode the demo scenarios show
REVIEW, which is the correct behaviour for unverified law.

**D-003 · Critical results are never hidden by the confidence gate.** Spec §6.7 step 9 downgrades to REVIEW on low
confidence. We apply that to ELIGIBLE / NOT_YET / EXCLUDED_479 but keep CRITICAL_MUST_RELEASE and
CRITICAL_ACQUITTED_DETAINED visible with a `CRITICAL_NEEDS_VERIFICATION` flag: a false alarm costs a lawyer's check;
a buried true alarm costs someone's liberty.

**D-004 · Day counting is inclusive.** Arrest and release on the same day = 1 day; the release/escape day counts;
explicit exclusion intervals (bail, absconding) remove their days inclusively. Maximum terms are converted with
1 month = 365.25/12 days and thresholds are rounded **up** (`ceil`). Results within ±2 days of a threshold carry a
`BORDERLINE` flag because courts may count differently.

**D-005 · Multiple offences in one case → REVIEW with both readings.** Section 479(2)'s "more than one offence"
bar is contested. The engine shows (a) the case-wise reading on the most serious offence and (b) the bar reading
(only the absolute ceiling applies), and never auto-decides. Multiple pending cases → REVIEW_MULTIPLE_CASES likewise.
The ceiling (detention ≥ maximum) is checked per case first and is CRITICAL regardless (test 11).

**D-006 · Custody in another case: strict count decides, lenient count shown.** Strict = custody tagged to this case or
untagged. Lenient = all custody after this case's offence date. If the two lead to different outcomes → REVIEW.

**D-007 · Conflicting arrest dates → earliest date in a primary document** (arrest memo, remand order, court order).
Secondary-only arrest dates (jail registers) get confidence below the threshold → REVIEW.

**D-008 · Delay attribution is conservative.** Only `accused` days are subtracted, and only the part of the adjournment
that overlaps custody. `both`, `other` and `unknown` are never subtracted. Non-production by the jail is the State's
delay. Accused-attributions below the confidence threshold (e.g. illness, change of counsel) gate the result to REVIEW.

**D-009 · Judgment retrieval runs in-process.** The hybrid index (BM25 + TF-IDF→LSA dense vectors) is built from
`data/judgments/*.jsonl`. Migration 0002 creates the pgvector table for when the public HC corpus is large. The repo
ships only a clearly labelled SYNTHETIC test corpus — we never generate or paraphrase real case law, and every
citation-like string not in the corpus is stripped and logged (`guard_citations`).

**D-010 · LLM is optional and never decisive.** Default provider `none`: deterministic extractors, template drafting.
With `NYAYA_LLM_PROVIDER=anthropic` (default model `claude-opus-5-5`, server-side refusal fallback enabled): structured
JSON extraction whose `evidence_quote` must be found verbatim in the document or the fact is dropped; LLM-only facts
are capped at 0.75 confidence (→ review); drafting "polish" is accepted sentence-by-sentence only if every checkable
token (date, section, number, name, citation) is unchanged.

**D-011 · Entity resolution never auto-merges in the product.** The matcher auto-links at p ≥ 0.92 (for evaluation),
but the API queues even those as `identity_match` review items; merges are human decisions and fully reversible
(`MergeEvent.snapshot`). Hard vetoes: relative's name clearly different, age gap ≥ 10 years.

**D-012 · Transition rule.** Offences before 1 July 2024 → IPC punishment (a BNS-numbered charge is mapped back and
flagged); BNSS 479 thresholds are applied to pending cases (spec item 16). The BNSS savings-clause question for
proceedings pending on commencement is flagged in the trace as a point for the lawyer.

**D-013 · Default-bail period** from first remand: 60 days, or 90 when the maximum is death/life/≥10 years; the right
accrues on remand date + period (remand day counted as day 1). Special-law extensions come from the KB record and are
flagged. A late charge sheet with no prior application → `DEFAULT_BAIL_RIGHT_LOST` recorded.

**D-014 · Urgency order** (dashboards, alerts): acquitted-but-detained > beyond maximum > default bail (the right is lost
forever once a charge sheet is filed) > bail granted but not furnished > eligible > review(multiple) > review > not yet >
excluded > not applicable.

**D-015 · Python 3.12 in Docker, 3.14 locally**; SQLite for tests/local, PostgreSQL 16 + pgvector in Compose. JSON
columns keep the schema portable.

**D-016 · Frontend auth** is a bearer JWT in localStorage (simple for a demo). Production should move to httpOnly
cookies + CSRF protection and short-lived tokens (see PRIVACY.md).

**D-017 · Delay model** is a fixed-horizon (pending > 3 years) LightGBM classifier plus a Cox model for C-index;
censored-before-horizon cases are excluded from the classifier. Trained on a synthetic stand-in until the DDL files
are downloaded (licence: CC BY-NC-SA, non-commercial).

## Audit round (Oct 2026)

**D-018 · Roles do their own work only.** The system admin adds prisoners, manages accounts and lawyers, assigns
lawyers, keeps the legal data and reads the audit log — it sees a *register* (name, jail, status, review state,
lawyer) but never case details, documents, Defense Insights or drafts. Only the assigned lawyer sees Defense Insights
and uploads documents. Jail staff record custody (new prisoner, transfer, release, case outcome); the DLSA assigns
within its district; the reviewer checks.

**D-019 · Intake review before assignment.** Every new prisoner (added by the admin or jail staff) goes to the review
queue as `new_prisoner`; a lawyer can be assigned only after the reviewer verifies the entered details. A returned
record cannot be assigned. Seeded demo prisoners count as verified.

**D-020 · One "not found" for out-of-scope and missing records.** An ID outside the caller's scope returns exactly the
same 404 body as an ID that does not exist (prisoners, documents, drafts, facts, insights, alerts), so IDs cannot be
probed; the attempt is audit-logged as `access_denied`. Role-level refusals (e.g. a reviewer calling a prisoner
endpoint) stay 403 because they reveal nothing about a record.

**D-021 · Eligibility date walks the real custody days.** The date the threshold (or maximum) was reached is the
N-th counted custody day — correct across bail periods, gaps and accused-caused adjournments. `days_overdue` stays the
number of counted days beyond the threshold. Accused-delay days are a set, so duplicate or overlapping adjournment
records can never subtract a day twice.

**D-022 · Default bail distinguishes the facts instead of "charge sheet filed = lost".** REVIEW when the application
and the late charge sheet share a date, when an application came before the right accrued, when the charge sheet
predates the first remand, when the remand date is missing during investigation, and when a maximum of exactly
10 years makes the 60- vs 90-day period decide the answer. A late charge sheet with no application *on record* says
the right may survive if an application was made.

**D-023 · Documents never decide by filename.** The type comes from the text; the real format from the file's bytes
(an extension that disagrees is flagged). A document whose content does not carry the fields its type needs, that
names another person, or that cites another case's FIR/CNR is held for review and its facts are capped below the
confidence threshold. Document facts never change a calculation directly: a usable fact that contradicts a date the
calculation depends on routes the case to REVIEW (`DOCUMENT_RECORD_CONFLICT`); a rejected fact is ignored.

**D-024 · Results are never stale.** A stored result carries the date it is valid for (`as_of`) and its legal-data
version; list and detail views recompute first when either is out of date. Alerts whose condition no longer holds are
closed automatically (and reopen if it returns).

**D-025 · Sessions.** Logout revokes the token (JWT id stored in `revoked_tokens`); a deactivated account's tokens stop
working on the next request; five failed sign-ins in 15 minutes lock the account for 15 minutes; all are audited.

**D-026 · Localization.** Every UI string exists in English, Kannada and Hindi (`frontend/src/lib/i18n/*.ts`, enforced by
TypeScript and `npm run check:i18n`). The rule engine's step-by-step trace and the recorded detail of flags and
documents are kept exactly as recorded (English) and labelled so; everything the user acts on — statuses, the
calculation, flags, findings, alerts, buttons — is localized.

**D-027 · Typed-in data is not evidence.** A prisoner added through the form has a custody start, first remand and
charges that nobody has proved yet. Until a document supports each of them — the FIR or charge sheet for the charges,
the arrest memo / remand order / jail admission record for custody — the case is REVIEW (`UNVERIFIED_MANUAL_ENTRY`)
and the numbers are shown only as provisional. Support means the document's own day-first reading equals the typed
value; facts from documents held as unverified (another person, another case, content not matching its type) never
count, and rejected facts are ignored.

**D-028 · The same prisoner cannot be added twice.** "Add prisoner" is refused (409) when the CNR matches an existing
case (any spacing/case), when the FIR number matches at the same police station, or when the name AND father's name
(spelling-tolerant: capitals, joined words, Gowda/Gouda) AND date of birth all match. A look-alike — same name with a
different father, or without a date of birth to compare — is allowed and goes to the reviewer as an identity match,
because different people share names. Jail staff of the jail holding the record are told which record matched; staff of another jail are
only told that one exists. Blocked attempts are audit-logged (`duplicate_blocked`).

**D-029 · No browser pop-ups; downloads that always work.** `window.prompt/confirm` are blocked in many browsers and
embedded views (it broke *Reset password*), so every question — reset password, correct a fact, verify legal data,
return an intake, deactivate an account — uses the app's own translated dialog (`components/Dialog.tsx`) with input
checks. Draft exports are sent `inline` and saved by the page (a fetched `attachment` response is diverted by Chrome's
download handling and never reaches the page). An admin password reset ends every session opened before it
(`password_changed_at`). `e2e/buttons.spec.ts` presses the buttons on every screen for every role and fails on any
uncaught page error.

**D-030 · The system admin does technical work only.** Each office does its own job: **jail staff add prisoners** (into
their own jail), the **DLSA adds, approves, deactivates and assigns lawyers** and sees its district's prisoner register,
the reviewer verifies new records, and only the assigned lawyer uploads documents. The system admin keeps staff
accounts, password resets, legal-data verification, the audit log and monitoring — and sees no prisoner at all, not
even the register. The API enforces it (403), not only the menu: `/api/persons` (create), `/api/register`,
`/api/lawyers` and `/assign` refuse the admin, and `/api/admin/users` refuses to create or convert a lawyer account,
so there is no back door around the DLSA. Tests: `test_admin_does_technical_work_only`, `e2e/flows.spec.ts`.

**D-031 · No "approve" on drafts; a reviewer screen that explains itself.** The app never approves a court
application — a qualified lawyer reads it, signs it and files it — so the lawyer's *Approve* button is gone and the API
refuses `status: approved` (422); drafts are edited and exported only. The review queue was hard to follow for anyone
who did not build it (technical titles such as `offence_datetime = '2026-01-09T19:30'`, signal names such as
`name_jw_phonetic`). Each item now carries plain context from the API (`context`: prisoner, jail, document, field,
value, exact source text, hearing dates, the two records of an identity pair), and the screen shows, in all three
languages: a three-step help box, the computer's confidence and what it means, *why is this here?*, the reading problem
in plain words (e.g. "the date can be read two ways; read day-first"), *what to check*, and beside every button what it
will do (including that closing a document warning does not release held facts, and that only "accused" delay reduces
the count). The technical title stays available under *Technical detail*. Test: `test_review_items_explain_themselves`.
