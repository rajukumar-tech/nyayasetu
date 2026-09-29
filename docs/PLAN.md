# NyayaSetu — Build Plan

Source spec: `NyayaSetu_Claude_Code_Prompt.md`. Decisions/deviations: [DECISIONS.md](DECISIONS.md).

## Architecture

See the diagram in the [README](../README.md#architecture). Key invariant: **LLMs extract/classify/summarise/draft;
only `backend/app/eligibility/` decides.** The engine is pure Python over plain dataclasses (`app/domain.py`) so it is
testable without a database. ORM rows are mapped into it by `app/services/mapping.py`.

## Data model
Person, Case (+ person link), Charge, CustodyEvent, Hearing, Conviction, Document (pages, boxes), ExtractionRun,
ExtractedFact (value, source doc/page/span, method, confidence, review status), ReviewItem, MergeEvent,
EligibilityResult (rule + legal-data version, input hash), DefenseInsight, Draft (grounding map, verifier report,
tracked versions), Alert (dedupe key), AuditLog, LegalVerification, User. See `backend/app/models/`.

## Phases

- [x] 1. Foundation — repo, Docker Compose, models + Alembic (0001, 0002 pgvector), JWT auth, RBAC, audit log,
      legal KB loader with verified/unverified records, synthetic generator
- [x] 2. Eligibility core — timeline + rule engine + default bail; tests 1–33; engine at 100% branch coverage
- [x] 3. Ingestion & extraction — upload, OCR (pluggable Tesseract + OpenCV), classification, regex ⨉ LLM extraction
      with spans and confidence, reviewer queue; tests 34–37
- [x] 4. Entity resolution — normalisation, blocking, trained pairwise model, clustering, merge/un-merge, evaluation;
      tests 38–44
- [x] 5. Delay attribution (rules → classifier → LLM) integrated into counted detention
- [x] 6. Defense Insight Engine — detectors A–E, hybrid retrieval F, ranking, guardrails; tests 45–53
- [x] 7. Grounded drafting + verifier + DOCX/PDF + Kannada; tests 54–55
- [x] 8. Delay prediction model (LightGBM fixed-horizon + Cox) + priority score
- [x] 9. Monitoring & alerts (idempotent, escalation, channel stubs, Celery beat) + dashboards for all roles; tests 56–58
- [x] 10. Evaluation (`python -m app.evaluation`), docs, seeded demo scenario, Playwright e2e, screenshots

## Status at hand-off
- Backend: 88 pytest tests passing; Playwright: 10 passing (desktop + mobile).
- Not done / next: real legal-data verification; public HC judgment corpus + pgvector-backed retrieval; DDL data
  download and retraining; Hindi UI strings; retention/deletion jobs; httpOnly-cookie sessions; a timed user study.
