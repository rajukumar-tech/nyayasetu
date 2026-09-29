# NyayaSetu — Build Plan

NyayaSetu ("bridge to justice") is decision support for legal-aid lawyers, jail
staff, DLSA/UTRC and reviewers. It builds each undertrial prisoner's legal picture
from messy records, computes Section 479 BNSS / default-bail eligibility with a
**deterministic** rule engine, surfaces lawyer-only Defense Insights, and drafts
grounded filings for human review.

Source spec: `NyayaSetu_Claude_Code_Prompt.md`. Decisions/deviations: `docs/DECISIONS.md`.

## Architecture

```
            ┌──────────────── Next.js (App Router, TS, Tailwind, i18n en/kn/hi) ────────────────┐
            │  Lawyer · Jail staff · DLSA · Reviewer · Admin dashboards                          │
            └───────────────────────────────┬─────────────────────────────────────────────────────┘
                                            │ JSON / JWT bearer
┌───────────────────────────────────────────▼─────────────────────────────────────────────────────┐
│ FastAPI  (api/)  ── core/: config, JWT auth, RBAC policy, audit log middleware                 │
│   ingestion/  upload → hash dedupe → preprocess (OpenCV) → OCR (pluggable, Tesseract) → classify│
│   extraction/ regex extractors (dates, sections, names) ⨉ LLM (structured JSON) → cross-check  │
│   resolution/ normalise → phonetic blocking → pairwise scorer → clustering → review queue      │
│   timeline/   custody intervals → merge/gaps/contradictions → counted days + explanation       │
│   delays/     keyword rules → text classifier → LLM fallback → accused-days                    │
│   legal_kb/   versioned YAML (data/legal) with source + verified flags; IPC↔BNS; derivations   │
│   eligibility/ PURE rule engine: 479, ceiling, default bail, surety, time-served               │
│   defense/    rule detectors A–E + hybrid judgment retrieval F + ranking + guardrails          │
│   drafting/   templates → grounded fill → sentence verifier → DOCX/PDF (en/kn)                 │
│   prediction/ survival-style delay model on DDL eCourts (priority score only)                  │
│   monitoring/ nightly idempotent recompute → alerts (in-app; email/SMS/WhatsApp stubs)         │
│   analytics/  dashboard aggregates                                                             │
└───────────────┬────────────────────────────┬───────────────────────────────┬───────────────────┘
        PostgreSQL 16 + pgvector       Redis (Celery broker)            Celery workers
        (SQLite for unit tests)                                         (OCR, extraction, nightly)
```

Key invariant: **LLMs extract/classify/summarise/draft; only `eligibility/` decides.**
The engine is pure Python over plain dataclasses, so it is testable without a DB.

## Data model
Person, Case, Charge, CustodyEvent, Hearing, Conviction, Document (+ pages, spans),
ExtractedFact (value, source doc/page/span, method, confidence, review status),
EligibilityResult, DefenseInsight, Draft, Alert, ReviewItem, MergeEvent, AuditLog, User.
See `backend/app/models/`.

## Phases (checklist)

- [ ] 1. Foundation — repo, Docker, models + Alembic, auth/RBAC, audit, legal KB loader, basic synthetic generator
- [ ] 2. Eligibility core — timeline + rule engine + default bail + tests 1–33
- [ ] 3. Ingestion & extraction — upload, OCR, classify, regex+LLM extraction, review queue, tests 34–37
- [ ] 4. Entity resolution — normalise, block, pairwise, cluster, merge/un-merge, eval, tests 38–44
- [ ] 5. Delay attribution + eligibility integration
- [ ] 6. Defense Insight Engine — detectors A–E, retrieval F, ranking, guardrails, tests 45–53
- [ ] 7. Grounded drafting + verifier + DOCX/PDF + Kannada, tests 54–55
- [ ] 8. Delay prediction model + priority scores
- [ ] 9. Monitoring & alerts + dashboards, tests 56–58
- [ ] 10. Evaluation, docs, demo scenario

Each phase: run `pytest`, update this checklist, summarise.
