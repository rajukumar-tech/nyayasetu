# How NyayaSetu works — end to end

## 1. The big idea

Many undertrial prisoners in India legally deserve release but stay in jail because nobody checks. Their records are
scattered across FIRs, arrest memos, court orders and jail registers, in English and Kannada, often badly scanned, and
most have no lawyer.

NyayaSetu does that checking automatically and consistently: it reads the records, works out exactly how long the
person has been held, compares that with what the law allows, tells the right person what to do, and drafts the court
application.

**Computers calculate and flag; lawyers and judges decide.** The app never says "will be released" — it says
"eligible to apply", with its reasoning shown.

## 2. The journey of one prisoner's record

```
Upload documents → Read them → Pull out facts → Match the person → Build custody timeline
      → Who caused each delay? → Eligibility decision → Defense insights → Draft application
                                                     ↘ Alerts to the right people
```

1. **Upload** — PDF, photo, Word or text. Oversized, empty, wrong-type and password-protected files are rejected with
   a clear message; duplicate uploads are detected.
2. **Reading (OCR)** — typed files are read directly; scans and photos are cleaned (denoise, straighten, binarise) and
   read in English, Hindi and Kannada. Blank or unclear pages are flagged for a human.
3. **Document type** — keyword rules (AI fallback, then reviewer) decide FIR, arrest memo, remand order, charge sheet,
   order sheet, jail record, etc.
4. **Pulling out facts** — dates in every format (Kannada/Hindi numerals and months, dd/mm vs mm/dd, two-digit years,
   OCR slips), sections like `u/s 379 IPC`, `379 r/w 34`, names with s/o, d/o, w/o. Every fact remembers the exact
   document, page and characters it came from. An AI (if enabled) must quote the document verbatim or its answer is
   discarded. Anything below 80% confidence goes to the reviewer queue.
5. **Same person?** — transliteration, titles removed, aliases (`@`, `urf`), a sounds-like code, and comparison of
   name, father's name, age, address, police station and case number. Different fathers or a 10+ year age gap block a
   match. Nothing is merged without a reviewer; every merge can be undone.
6. **Custody timeline** — police + judicial + hospital custody count; bail and escape periods don't; transfers aren't
   gaps; re-arrest resumes counting; conflicting arrest dates → earliest official date, flagged; days counted
   inclusively; leap years handled.
7. **Who caused each delay?** — accused / prosecution / court / both / other / unknown. Only the accused's own delay is
   subtracted; "not produced by jail" is the prosecution's fault; unknown is never subtracted; unsure → reviewer.
8. **Eligibility decision (no AI, same answer every time):**

   | Check | Result |
   |---|---|
   | Convicted or case closed? | Not applicable (acquitted but still jailed → CRITICAL) |
   | Death/life offence? | Excluded from 479 (default bail still checked) |
   | Detained ≥ maximum sentence? | CRITICAL: must release |
   | More than one case/offence? | REVIEW with both legal readings |
   | Special law (NDPS, POCSO…)? | REVIEW by lawyer |
   | Never convicted before? | Threshold 1/3 of maximum, else 1/2 |
   | Counted detention ≥ threshold? | ELIGIBLE (date, days overdue) or NOT YET (expected date) |
   | Any unsure fact or unverified law? | Downgraded to REVIEW, listing what to check |

   Example — Suresh Kumar, IPC 420 (max 7 years): 991 days in custody − 30 days he asked for = 961 counted; first-time
   offender threshold 853 → **ELIGIBLE: threshold reached 108 days ago.** Ravi Kumar, BNS 303(2) (max 3 years):
   263 − 21 = 242 counted, threshold 366 → **not yet eligible (124 more days).**

   Separate checks: **default bail** (no charge sheet within 60/90 days of first remand — apply before it is filed),
   **bail granted but still jailed** after 7 days (surety not paid → poor-prisoner scheme), **time served** exceeding a
   likely sentence.
9. **Defense Insights (lawyer only)** — arrest-procedure violations, evidence gaps, wrong charge, plea bargaining,
   settlement, probation, speedy trial, and similar judgments retrieved (never invented). Every insight must point to
   evidence in the documents; no win-percentages; nothing unlawful. Lawyer accepts or rejects each.
10. **Drafting** — seven application types in English or Kannada, built sentence by sentence from sources; a checker
    rejects any sentence whose date, section, number, name or citation isn't supported. Edit (versions kept), approve,
    export Word/PDF.
11. **Nightly monitoring** — recomputes everyone; alerts for eligible in 30/7/0 days, overdue, critical, default-bail
    windows, and documents that change a result; never duplicates; escalates unacknowledged alerts to the DLSA.

## 3. How the roles work together

```
Jail staff uploads records ─┐
                            ├─→ System reads, calculates, flags
Lawyer uploads records ─────┘            │
                                         ├─→ Reviewer fixes unsure facts, matches, delays
                                         ├─→ Lawyer: insights → draft → files in court
                                         ├─→ Jail staff: superintendent's application
                                         └─→ DLSA: district overview, assigns lawyers, escalations
Admin: verifies the law, watches the audit log
```

| Role | Job |
|---|---|
| Jail staff | Upload records; see eligible/overdue in their jail; prepare the superintendent's application. Cannot see defence strategy. |
| Lawyer | Only assigned prisoners; checks reasoning, fixes facts, uses Defense Insights, drafts and files. |
| Reviewer | Clears the queue of unsure facts, identity matches and delay causes; each decision triggers a recalculation. |
| DLSA / UTRC | District heatmap, averages, vulnerable counts, lawyer workload; assigns lawyers. |
| Admin | Verifies each legal record against official law; runs monitoring; reads the audit log. |

## 4. Trust — safeguards and current limits

Safeguards: no AI in the decision (fully tested rules); every fact, result and draft sentence traceable to its source;
no invented law or cases; unsure → review (except critical cases, which stay visible); role-based access; everything
audit-logged.

Not ready for real use yet: legal data is **unverified** (demo marks it "DEMO SEED — not a legal check"); all data is
**synthetic**; the judgments collection is a small **test** set; the delay model is trained on synthetic data; Kannada
drafts need a Kannada-speaking lawyer's review; Hindi screens are partly translated.

## 5. Where things live

| Folder | Contents |
|---|---|
| `backend/app/eligibility/` | Decision engine |
| `backend/app/timeline/` | Custody day counting |
| `backend/app/ingestion/`, `extraction/` | OCR, document type, fact extraction |
| `backend/app/resolution/` | Identity matching, merge/undo |
| `backend/app/delays/` | Adjournment attribution |
| `backend/app/defense/` | Defense Insights, judgment search |
| `backend/app/drafting/` | Applications, checker, Word/PDF export |
| `backend/app/monitoring/` | Nightly job and alerts |
| `data/legal/` | The law as data files |
| `frontend/src/` | Everything in the browser |
| `docs/` | Plan, decisions, evaluation, privacy, legal-data status, demo script |
