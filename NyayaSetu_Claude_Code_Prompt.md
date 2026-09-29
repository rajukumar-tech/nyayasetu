# Build NyayaSetu — Full Project Prompt for Claude Code

You are building **NyayaSetu** ("bridge to justice"), a full-stack, AI-assisted legal decision-support platform for India's criminal justice system. Read this entire document before writing any code. Then produce a written plan (architecture, repo layout, phase breakdown), and build phase by phase, running tests at the end of each phase.

---

## 0. How you should work

1. **Plan first.** Before coding, write `docs/PLAN.md` with the architecture, data model, module list, and phase checklist. Keep it updated as you go.
2. **Build in phases** (Section 12). Finish, test, and commit each phase before starting the next.
3. **Tests are mandatory.** Every rule, calculation and edge case in Sections 6–9 must have a unit test. The eligibility engine must have 100% branch coverage.
4. **Never hardcode legal facts in logic.** All legal data (sections, maximum punishments, exclusions, time limits, IPC→BNS mappings) lives in versioned data files under `data/legal/` with a `source` field and a `verified: true|false` flag. Section numbers in this prompt are my best understanding and **must be treated as unverified** until checked against official texts (India Code / Gazette). Surface `verified: false` items in the UI as "needs legal verification".
5. **Deterministic decisions, AI for reading and writing.** LLMs may extract, classify, summarise and draft. LLMs must **never** make the final eligibility decision. That is done only by the rule engine.
6. **Never fabricate.** No invented facts, dates, case citations, or statute text. Every generated claim must link to a source document span or a verified legal data record.
7. **Ask me** only if something blocks you; otherwise make a reasonable choice, record it in `docs/DECISIONS.md`, and continue.

---

## 1. Problem statement

- About 75% of people in Indian prisons are undertrials (not convicted).
- **Section 479 BNSS** (earlier Section 436A CrPC): an undertrial accused of an offence **not** punishable with death or life imprisonment, who has been detained for **one-half** of the maximum sentence, shall be released on bail; a **first-time offender** (never convicted before) shall be released on bond after **one-third**. No undertrial may be detained beyond the **maximum** sentence for the offence. Where investigation/inquiry/trial for **more than one offence or multiple cases** is pending, release under this section is barred (479(2)) — interpretation is contested. The jail superintendent must apply to the court when the threshold is reached. The court may, after hearing the prosecutor and recording reasons, order continued detention. Delay caused by the accused is excluded from the computation.
- In practice only ~1% of long-duration undertrials are identified as eligible, because identification is manual, records are scattered and messy, and most prisoners have no lawyer.

**NyayaSetu** builds each prisoner's complete, verified legal picture from messy multilingual records, computes eligibility exactly, monitors every prisoner continuously, identifies every legal route to release or acquittal, and drafts filings for legal aid lawyers to review.

---

## 2. Users and roles (RBAC)

| Role | Can do |
|---|---|
| `legal_aid_lawyer` | See assigned prisoners, eligibility, **Defense Insights**, drafts; edit/approve drafts; correct extracted facts |
| `jail_staff` | See prisoners in their jail, eligibility status and alerts; upload documents; cannot see Defense Insights |
| `dlsa_admin` (District Legal Services Authority / UTRC) | District dashboards, assignment of lawyers, analytics; read-only case view |
| `reviewer` (law student / verifier) | Review queue: confirm or correct extractions, entity matches, delay attributions |
| `system_admin` | Users, legal data versions, audit logs |

The prisoner is the beneficiary, not a user. **Defense Insights are privileged legal strategy: visible only to the assigned lawyer (and admins with an audit trail).**

---

## 3. Tech stack

- **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic
- **DB:** PostgreSQL 16 + pgvector; Redis for queues/cache
- **Jobs:** Celery (or RQ) for OCR, extraction, nightly monitoring, alerts
- **OCR:** pluggable interface; default Tesseract with `eng`, `hin`, `kan` language packs; image preprocessing with OpenCV (deskew, denoise, binarise)
- **LLM:** provider-agnostic interface (default: Anthropic Claude API) using **structured JSON outputs** validated by Pydantic; all prompts versioned in `prompts/`
- **Transliteration / Indic text:** `indic-transliteration`, Unicode normalisation (NFC), script detection
- **Entity resolution:** `rapidfuzz`, phonetic keys adapted for Indian names, blocking + a trained pairwise classifier + clustering
- **ML:** scikit-learn / LightGBM for delay prediction; MLflow (or simple local tracking) for experiments
- **Retrieval:** pgvector embeddings over judgments + BM25 hybrid search
- **Frontend:** Next.js (App Router) + TypeScript + Tailwind; i18n for English and Kannada (and Hindi scaffolded)
- **Infra:** Docker Compose for local; `.env.example`; seed scripts
- **Testing:** pytest (+ hypothesis for property-based date tests), Playwright for key UI flows

---

## 4. Repository layout (suggested)

```
nyayasetu/
  backend/
    app/
      api/            # FastAPI routers
      core/           # config, security, RBAC, audit
      models/         # SQLAlchemy models
      schemas/        # Pydantic schemas
      ingestion/      # upload, OCR, preprocessing
      extraction/     # LLM + rule-based fact extraction
      resolution/     # entity resolution (person & case linking)
      timeline/       # custody timeline reconstruction
      delays/         # delay attribution classifier
      legal_kb/       # legal knowledge base loaders & queries
      eligibility/    # deterministic rule engine (Section 479 + default bail etc.)
      defense/        # Defense Insight Engine
      drafting/       # grounded document drafting + verifier
      prediction/     # case-delay ML model
      monitoring/     # nightly jobs, alerts
      analytics/      # dashboards data
    tests/
  frontend/
  data/
    legal/            # YAML legal data with sources + verified flags
    synthetic/        # generated test prisoners/cases
    external/         # DDL eCourts data, HC judgments (download scripts only)
  prompts/
  ml/                 # notebooks/scripts for training & evaluation
  docs/
  docker-compose.yml
```

---

## 5. Data model (core entities)

- **Person** (canonical identity): id, canonical_name, name_variants[], father/husband name variants, gender, DOB (+ uncertainty), age_at_offence, addresses, identifiers (prisoner numbers, CNRs), `is_juvenile_at_offence` flag, `is_foreign_national` flag, vulnerability flags (woman, elderly, disabled, serious illness).
- **Case**: CNR number, court, district, state, case number(s) (a case may get a new number on transfer), FIR number + police station + year, status (investigation / charge sheet filed / trial / convicted / acquitted / disposed), linked_person_ids.
- **Charge**: case_id, law (IPC / BNS / special act), section, sub-section, is_attempt / abetment / conspiracy, date added, date dropped, `max_punishment` (resolved from legal KB), `is_death_or_life`, confidence.
- **CustodyEvent**: person_id, case_id (nullable), type (arrest, police_custody, judicial_custody, bail_granted, released, re-arrest, transfer, hospitalised_in_custody, escaped/absconded, surrendered), start, end, jail, source_document_span, confidence.
- **Hearing**: case_id, date, outcome text, adjournment reason, `delay_attribution` (accused / prosecution / court / other / unknown), confidence, reviewer_verified.
- **Conviction**: person_id, case_id, date, offence, status (final / under appeal / set aside / juvenile), source.
- **Document**: file, type (FIR, arrest memo, remand order, charge sheet, court order, judgment, bail order, jail record, medical record), language, OCR text, page images, extraction runs.
- **EligibilityResult**: person_id, rule_version, legal_data_version, status, eligible_from_date, days_overdue, reasoning_trace[], flags[], confidence, computed_at.
- **DefenseInsight**: person_id, case_id, type, severity, explanation, evidence_spans[], legal_basis (legal KB refs), supporting_judgments[] (retrieved only), status (new / accepted / rejected by lawyer).
- **Draft**: type (479 application, default bail application, regular bail, plea bargaining application, discharge application, speedy-trial petition), language, content, grounding_map (sentence → source), verifier_report, status.
- **AuditLog**: every view/edit/decision with user, timestamp, before/after.

Every extracted fact stores: value, source document + page + text span, extraction method, confidence, reviewer status.

---

## 6. Module specifications

### 6.1 Ingestion & OCR
- Accept PDF, JPG/PNG, DOCX, TXT; multi-page; mixed scripts on one page.
- Preprocess images (deskew, denoise, contrast); detect orientation and script.
- Store per-page OCR text with bounding boxes for later citation highlighting.
- Classify document type (rules + LLM fallback).
- **Edge cases:** blank/unreadable pages, handwriting (mark low confidence, route to review), stamps and signatures overlapping text, duplicate uploads (hash), password-protected PDFs (reject with message), huge files (size limit + chunking), wrong document uploaded to wrong prisoner (detect name mismatch → warn).

### 6.2 Fact extraction
- LLM with strict JSON schema → names, relations (s/o, d/o, w/o), age/DOB, addresses, FIR details, sections charged, arrest date/time, remand dates, charge-sheet filing date, hearing entries, bail orders, convictions.
- Cross-check LLM output with regex/rule extractors for dates and section numbers; disagreement → lower confidence.
- **Edge cases:** dates in dd/mm/yyyy vs mm/dd/yyyy vs "12th March 2025" vs Kannada/Hindi numerals and month names; two-digit years; partial dates ("March 2023"); impossible dates (31/02); future dates; sections written as "379 IPC", "u/s 379", "S.379", "379/34", "379 r/w 34", ranges ("323, 324, 504 & 506"); old IPC sections in new-era documents and vice versa; charges added or dropped later; OCR errors (O vs 0, l vs 1).

### 6.3 Entity resolution (core technical challenge)
Link all records belonging to the same real person across courts, districts, jails and languages, **without merging different people**.
- Normalise: transliterate Kannada/Hindi to Latin, lowercase, strip honorifics (Sri, Shri, Smt, Mr), expand initials where possible, handle "s/o", "urf", "alias", "@".
- Blocking on phonetic keys + district + approximate age.
- Pairwise classifier features: name similarity (multiple metrics), father's name similarity, age/DOB difference, address overlap, police station overlap, co-accused overlap, case timeline plausibility.
- Clustering with thresholds; **uncertain matches go to the reviewer queue**, never auto-merged.
- **Edge cases:** very common names (e.g., many "Ravi Kumar"s in one district); same name + same father name in one village; aliases; single-name persons; name order swaps; spelling variants; married women's name changes; missing father's name; DOB vs stated age conflicts; a case transferred between courts appearing twice; a person wrongly merged (support un-merge with audit trail).
- Report precision/recall on a labelled synthetic set; **false merges are worse than missed merges** (a false merge can wrongly mark someone as a repeat offender) — tune for high precision and show this trade-off in docs.

### 6.4 Custody timeline reconstruction
- Build a timeline per person per case from all CustodyEvents; merge overlaps; detect gaps and contradictions.
- Compute: total detention counted for each case, with a per-interval explanation.
- **Edge cases:** police custody + judicial custody both count; time on bail does not count; bail granted but person not released (couldn't furnish surety) → still in custody, count it and flag for the poor-prisoner support scheme; re-arrest in the same case; custody in a different case during the same period (whether it counts for this case is legally uncertain → compute both ways, flag for review); transfer between jails (no gap); hospitalisation while in custody (counts); escape/abscondence (exclude the period outside custody); missing end date for current custody (use today); conflicting arrest dates across documents (show both, pick the earliest supported by a primary document, flag); inclusive vs exclusive day counting (document the convention and test it); leap years; converted to convict (stops being undertrial on conviction date; if the conviction is set aside on appeal, reassess).

### 6.5 Delay attribution
- Classify each hearing/adjournment reason as caused by accused / prosecution / court / other / unknown.
- Hybrid: keyword rules for clear cases ("at the request of the accused", "accused absent", "PP sought time", "PO on leave", "witness absent") + a trained text classifier + LLM fallback; low confidence → review.
- Compute days attributable to the accused, to be excluded under the Explanation to Section 479.
- **Edge cases:** adjournment requested by *both* sides; accused absent due to not being produced by the jail (not the accused's fault); counsel changed; illness of the accused; strikes / lawyers' boycott; court vacations; COVID-period suspensions; missing adjournment reasons (unknown → do not subtract, flag).

### 6.6 Legal knowledge base
- YAML/JSON files with: act, section, title, punishment text, `max_imprisonment` (years/months, or `life`, `death`), `min_imprisonment`, fine-only flag, cognizable, bailable, compoundable (with/without court permission, who can compound), triable by, special bail restrictions, plea-bargaining exclusions, source URL, effective dates, `verified` flag.
- IPC ↔ BNS mapping table: one-to-one, one-to-many, many-to-one, and "no equivalent", with notes. **Offences committed before 1 July 2024 remain governed by the IPC for punishment**; the mapping is used for display and research, not to change the applicable punishment.
- Derived punishments: attempt, abetment, criminal conspiracy, common intention (r/w 34 IPC / corresponding BNS) — compute the effective maximum per the governing rule and store the derivation.
- Special laws (NDPS, UAPA, PMLA, POCSO, SC/ST Act, Arms Act, etc.): mark sections with special bail conditions; Section 479 interplay → always flag for lawyer review, do not auto-decide.
- Version every change; every EligibilityResult records the legal data version used.

### 6.7 Eligibility rule engine (deterministic)
Pure Python, no LLM, fully unit-tested, produces a step-by-step reasoning trace.

Evaluation order (per person, per case, then overall):
1. **Not an undertrial?** (convicted and not set aside, or acquitted/disposed) → `NOT_APPLICABLE` (if acquitted but still detained → `CRITICAL: acquitted but detained`).
2. **Any charge punishable with death or life imprisonment?** → `EXCLUDED_479` (still run default-bail and other checks).
3. **Absolute ceiling:** counted detention ≥ maximum punishment of the offence → `CRITICAL_MUST_RELEASE` (applies even when multiple cases are pending).
4. **Multiple offences / multiple cases pending?** → `REVIEW_MULTIPLE_CASES` with calculations shown for each case and both legal interpretations.
5. **First-time offender?** No prior conviction (acquittals, discharges, pending cases, and convictions set aside do not count; juvenile adjudications → flag, likely do not count; conviction under appeal → counts as conviction but flag). Threshold = 1/3; otherwise 1/2.
6. **Counted detention** = custody days − days attributable to the accused.
7. Compare → `ELIGIBLE` (with eligible_from_date, days_overdue) / `NOT_YET` (with projected date) / `REVIEW` (missing or low-confidence inputs).
8. Always note: the court may order continued detention for recorded reasons — result means "eligible to apply", never "will be released".
9. **Confidence gating:** if any input fact below the threshold or unverified legal data → downgrade to `REVIEW` and list exactly which facts need checking.

Also implement, as separate rules:
- **Default bail (statutory bail):** charge sheet not filed within the statutory period from first remand (commonly 60 days, or 90 days for offences punishable with death, life, or imprisonment of 10 years or more — verify under BNSS Section 187) → right accrues if applied **before** the charge sheet is filed → `URGENT_DEFAULT_BAIL`. Special laws may extend periods → flag.
- **Time served vs likely sentence:** counted detention already exceeds the minimum or typical sentence → suggest plea bargaining / early disposal route.
- **Bail granted but not released** (surety not furnished) for > 7 days → flag for the poor-prisoner support scheme and bail-condition modification.

### 6.8 Defense Insight Engine (NEW — lawyer-only)
Goal: for each case, list every legally available route to acquittal, discharge, bail, or faster disposal, **grounded in the record**, so the legal aid lawyer can build the strongest defence. It suggests; the lawyer decides.

Insight categories (each with severity, explanation, evidence spans, legal basis ref, and "what to do next"):

**A. Procedural / arrest safeguards** (verify exact BNSS section numbers in the legal KB)
- Grounds of arrest not communicated / not recorded
- Not produced before a magistrate within 24 hours (compute from arrest time and first production)
- Arrest memo missing, not attested, or relative not informed
- Woman arrested after sunset / before sunrise without the required permission, or without a woman officer
- Medical examination not done
- Remand orders missing or mechanical; remand beyond permitted police-custody period
- Search/seizure without independent witnesses; no seizure memo; video recording requirements not followed where applicable

**B. Investigation and evidence gaps**
- Unexplained delay in registering the FIR
- Contradictions between FIR, witness statements and charge sheet (dates, times, places, weapons, number of accused)
- No independent witnesses; all witnesses are police or interested parties
- Forensic / FSL report pending or missing; chain of custody gaps for seized items
- Identification parade not held where identity is disputed
- Key witnesses repeatedly absent; prosecution witnesses turning hostile (from hearing records)
- Recovery not linked to the accused; confession to police (generally inadmissible) relied upon

**C. Charge-level arguments**
- Facts in the record do not support an ingredient of the charged section → candidate for discharge or a lesser section
- Section mismatch (a more serious section applied than facts support)
- IPC/BNS transition errors (new section applied to an offence committed before 1 July 2024, or vice versa)

**D. Faster exits**
- **Plea bargaining** eligibility (check statutory exclusions: punishment ceiling, offences against women/children, socio-economic offences; verify in legal KB)
- **Compoundable offence** → possibility of settlement with the victim (note who may compound and whether court permission is needed)
- **Probation** for first-time offenders / young offenders (Probation of Offenders Act and BNSS provisions)
- **Lok Adalat** suitability
- **Time already served ≥ likely sentence**

**E. Delay and fundamental rights**
- Speedy trial (Article 21): when the timeline shows extreme, unexplained delay not attributable to the accused → generate the timeline exhibit and argument outline

**F. Similar judgments (retrieval, never generated)**
- Hybrid search over High Court judgments (public HC judgments dataset) using the case facts + sections
- Show top matches with citation, court, date, link, and the matching passage
- **Hard rule:** a judgment may be shown only if it exists in the retrieved corpus; the UI must display the source link; the LLM may summarise only retrieved text. Any citation not found in the corpus is stripped and logged.

**Ranking:** order insights by (a) strength of record support, (b) impact on liberty (immediate release routes first), (c) urgency (e.g., default bail before charge sheet filing).

**Guardrails for this module:**
- No "win probability" presented as a promise. If you show a model-based estimate anywhere, label it as a rough historical pattern, not a prediction for this case.
- Only lawful strategies grounded in the record; never suggest contacting, influencing or pressuring witnesses or victims, fabricating evidence, or evading court.
- Every insight must cite record spans; insights with no supporting evidence are not shown.
- Access restricted to the assigned lawyer; every view is audit-logged.
- Visible disclaimer: "Decision support for a qualified lawyer. Not legal advice. Verify all sections and citations."

### 6.9 Grounded drafting
- Templates: Section 479 application, default bail application, regular bail application, plea bargaining application, discharge application, speedy-trial petition, bail-condition modification (surety relief).
- LLM fills templates **only** from verified facts, eligibility trace, accepted defense insights, and retrieved judgments.
- **Verifier pass:** every sentence mapped to a source (fact id, legal KB record, or judgment span). Sentences with unsupported names, dates, sections or citations → rejected and regenerated or flagged.
- Output: English and Kannada; export DOCX and PDF; lawyer edits tracked.

### 6.10 Case-delay prediction (ML)
- Train on the Development Data Lab public eCourts dataset (district courts, 2010–2018; ~10M criminal cases; CC BY-NC-SA — respect licence, non-commercial).
- Target: case duration (filing → decision) or probability of pending > N years; handle censoring for undisposed cases (survival analysis, e.g., Cox or LightGBM with survival objective — document the choice).
- Features: act/section groups, court, district, state, filing year, case type, number of accused if available.
- Temporal split (train on earlier years, test on later) to avoid leakage; report MAE / C-index / calibration; fairness check across districts and gender fields present in the data.
- Use: priority score for lawyers, never an input to eligibility.

### 6.11 Monitoring & alerts
- Nightly job recomputes eligibility for all active prisoners.
- Alerts: becomes eligible in 30 / 7 / 0 days; overdue; CRITICAL (beyond max / acquitted but detained / bail granted but not released); URGENT default bail window; new document uploaded changes a result.
- Channels: in-app; email/SMS/WhatsApp as pluggable stubs.
- Idempotent jobs; no duplicate alerts; escalate if not acknowledged in N days.

### 6.12 Dashboards
- **Lawyer:** my prisoners sorted by urgency; each case page shows timeline, facts with source highlights, eligibility trace, defense insights, drafts.
- **Jail staff:** eligible/overdue lists for their jail; one-click "prepare superintendent's application".
- **DLSA:** district heatmap of overdue undertrials, average detention, lawyer workload, vulnerable-prisoner counts.
- **Reviewer:** queue of low-confidence extractions, uncertain identity matches, delay attributions.

---

## 7. Security, privacy & ethics
- Treat all personal data as highly sensitive: encryption at rest for documents, TLS, strict RBAC, full audit logging, data minimisation, retention policy, and anonymised exports for analytics.
- Align design with India's Digital Personal Data Protection Act principles (purpose limitation, access control); document this in `docs/PRIVACY.md`.
- No real prisoner data in the repo. Use synthetic data + public anonymised datasets only.
- Bias check: ensure no protected attributes (religion, caste) are used as model features; document fairness evaluation.
- Human-in-the-loop everywhere: the system flags and drafts; lawyers and judges decide.

---

## 8. Synthetic data generator
Build `data/synthetic/generate.py` that creates realistic prisoners, cases and documents (including noisy OCR-like text in English and Kannada) with **known ground truth**, covering every edge case in Section 9. Include: name variants and transliterations of the same person across cases, look-alike different people, conflicting dates, multiple cases, prior convictions (final, under appeal, set aside, juvenile), bail-not-released, default-bail windows, special-law charges, IPC-era and BNS-era cases, and procedural violations for the Defense Insight Engine.

---

## 9. Edge-case test checklist (each must be a named test)

**Eligibility**
1. First-time offender past 1/3 → ELIGIBLE with correct days overdue
2. First-time offender before 1/3 → NOT_YET with correct projected date
3. Prior conviction → uses 1/2
4. Prior arrest but acquitted → still first-time
5. Prior conviction set aside on appeal → first-time
6. Prior conviction under appeal (not set aside) → counts as conviction, flagged
7. Juvenile adjudication in past → flagged, treated per legal KB rule
8. Offence punishable with death or life → EXCLUDED_479
9. Life imprisonment as an alternative punishment → EXCLUDED_479
10. Fine-only offence → handled (no imprisonment → flag unusual detention)
11. Detention ≥ maximum → CRITICAL_MUST_RELEASE even with multiple cases
12. Multiple cases pending → REVIEW_MULTIPLE_CASES with both interpretations
13. Multiple charges in one case with different maxima → REVIEW with per-charge calculations
14. Attempt / abetment / conspiracy → derived maximum used
15. Special-law charge (e.g., NDPS) → flagged for review, not auto-decided
16. Offence before 1 July 2024 → IPC punishment applies; BNS 479 thresholds applied to pending case
17. Delay attributable to accused subtracted correctly
18. Unknown delay attribution → not subtracted, flagged
19. Low-confidence arrest date → downgraded to REVIEW
20. Unverified legal data record → downgraded to REVIEW
21. Convicted during pendency → NOT_APPLICABLE from conviction date
22. Acquitted but still detained → CRITICAL
23. Bail granted, surety not furnished → still counted + poor-prisoner flag
24. Default bail: charge sheet not filed within statutory period → URGENT_DEFAULT_BAIL; filed on time → no flag; filed late but before application → right lost, recorded

**Custody timeline**
25. Police + judicial custody both counted
26. Time on bail excluded; re-arrest resumes counting
27. Overlapping custody records merged, no double counting
28. Jail transfer with no gap
29. Escape/abscondence period excluded
30. Custody in another case during the same period → both computations shown
31. Current custody with no end date uses today
32. Leap-year spanning periods; inclusive/exclusive counting convention
33. Conflicting arrest dates across documents → earliest primary-source date + flag

**Dates & text**
34. dd/mm vs mm/dd ambiguity resolution and flagging
35. Kannada and Hindi numerals and month names
36. Two-digit years; partial dates; impossible dates; future dates
37. Section strings: "u/s 379", "379/34", "379 r/w 34", lists and ranges

**Entity resolution**
38. Same person, different spellings/scripts → linked
39. Different people, same name, different fathers → not linked
40. Same name + same father + different age by 20 years → not linked
41. Alias ("urf", "@") → linked
42. Uncertain pair → sent to review, not auto-merged
43. Un-merge restores prior state with audit entry
44. Transferred case with two case numbers, same CNR → one case

**Defense insights**
45. Production before magistrate after 24 hours → insight shown with evidence spans
46. Grounds of arrest not recorded → insight
47. FIR delay with no explanation → insight
48. Contradiction between FIR and charge sheet dates → insight with both spans
49. Compoundable offence → settlement route suggested
50. Plea-bargaining exclusion (e.g., offence against a child) → route NOT suggested
51. Insight with no evidence in record → not shown
52. Judgment citation not in corpus → stripped and logged
53. Jail staff role cannot access insights (403)

**Drafting**
54. Draft contains only verified facts; injected fake date → verifier rejects
55. Kannada draft generated and exported

**System**
56. Nightly job idempotent; no duplicate alerts
57. New document changes eligibility → alert fired
58. RBAC: each role sees only permitted data; all views audited

---

## 10. Evaluation (put results in `docs/EVALUATION.md`)
- Extraction: field-level precision/recall on synthetic + manually labelled samples
- Entity resolution: pairwise precision/recall, cluster purity; false-merge rate highlighted
- Delay attribution: accuracy, confusion matrix
- Eligibility: agreement with hand-verified cases (target: law-student-reviewed set of 50–100 cases)
- Defense insights: precision of insights judged by reviewers; zero fabricated citations
- Delay model: MAE / C-index / calibration on temporal holdout
- Drafting: % sentences fully grounded; reviewer edit distance
- Time saved: manual vs system time to prepare an application (simulated study)

---

## 11. Non-functional requirements
- Every decision explainable in plain language (English + Kannada) with source highlights
- p95 page load < 2s on seeded data; background jobs for heavy work
- Structured logging; health checks; error handling with user-friendly messages
- Accessibility (WCAG AA), mobile-friendly for lawyers in the field
- One-command local setup: `docker compose up` + `make seed`

---

## 12. Build phases

1. **Foundation:** repo, Docker, DB models + migrations, auth/RBAC, audit log, legal KB loader with sample verified/unverified records, synthetic data generator (basic).
2. **Eligibility core:** custody timeline + deterministic rule engine + default-bail rule + full unit tests (Section 9, items 1–33).
3. **Ingestion & extraction:** upload, OCR, document classification, LLM + regex extraction with confidence and source spans; reviewer queue.
4. **Entity resolution:** normalisation, blocking, pairwise model, clustering, merge/un-merge, evaluation.
5. **Delay attribution** + integration into eligibility.
6. **Defense Insight Engine:** rule-based detectors (A–E), judgment retrieval (F), ranking, guardrails, tests 45–53.
7. **Grounded drafting** + verifier + DOCX/PDF export + Kannada.
8. **Delay prediction model** on DDL data + priority scores.
9. **Monitoring & alerts** + dashboards for all roles.
10. **Evaluation, docs, demo:** EVALUATION.md, README with architecture diagram, seeded demo scenario showing: a CRITICAL case, an ELIGIBLE first-time offender, a REVIEW multiple-case prisoner, an URGENT default-bail case, and a lawyer using Defense Insights to generate an application.

At the end of each phase: run all tests, update `docs/PLAN.md`, and summarise what was built and what's next.

---

## 13. Final deliverables
- Working app (`docker compose up`), seeded demo data, all tests passing
- `README.md`: problem, solution, architecture diagram, screenshots, how to run
- `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/EVALUATION.md`, `docs/PRIVACY.md`, `docs/LEGAL_DATA.md` (sources + which records are still unverified)
- A 2-minute demo script in `docs/DEMO.md`

Start now by reading this document fully and writing `docs/PLAN.md`.
