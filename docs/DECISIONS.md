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
