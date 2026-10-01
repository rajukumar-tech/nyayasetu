# NyayaSetu — notes for Claude Code

Decision support for undertrial prisoners in Karnataka: a deterministic Section 479 BNSS / default-bail engine, document
extraction with source highlights, a review queue, grounded drafts, and dashboards for each role. Synthetic data only.
Read `README.md`, `docs/HOW_IT_WORKS.md` and `docs/DECISIONS.md` (D-001 … D-031) before changing behaviour.

## Layout
- `backend/` — FastAPI + SQLAlchemy (SQLite locally). Engine: `app/eligibility/engine.py`; API: `app/api/routes.py`,
  `app/api/lifecycle.py`; permissions: `app/core/rbac.py`; ingestion: `app/ingestion/`; tests: `backend/tests/`.
- `frontend/` — Next.js 16 App Router (read `frontend/AGENTS.md`: this Next.js differs from older versions), Tailwind 4,
  Playwright e2e in `frontend/e2e/`. UI text lives only in `src/lib/i18n/{en,kn,hi}.ts`.
- `data/synthetic/` — generator and the independent oracle for the 1,000-scenario harness.

## Commands (Python is the repo venv: `.venv/Scripts/python` on Windows)
- Demo data: `cd backend && ../.venv/Scripts/python -m app.seed --reset` (two prisoners; `--full` adds the rest).
- API: `../.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `backend/`); web: `cd frontend && npm run dev`.
- Backend tests: `cd backend && ../.venv/Scripts/python -m pytest -q` (~17 min for all; pick files while iterating).
- Scenario harness: `cd backend && ../.venv/Scripts/python -m app.scenario_check` (writes `docs/TEST_REPORT.md`, ~18 min).
- Frontend: `npx tsc --noEmit`, `npx eslint src e2e`, `node scripts/check-i18n.mjs`, `npx next build`.
- Browser tests (API on :8000, web on :3000, demo seeded): `PW_CHANNEL=chrome npx playwright test flows buttons`.
- Screenshots: `SCREENSHOTS=1 PW_CHANNEL=chrome npx playwright test screenshots --project=desktop`, then reseed.

## Rules
- **Git:** commits are authored only by `rajukumar-tech <rk8852641@gmail.com>`. No Co-Authored-By lines, no
  "Generated with Claude" or other AI attribution. Never commit `.env`, `*.db` or `backend/uploads/`.
  (`.claude/hooks/guard_git.py` enforces this.)
- **Demo data:** the default seed has exactly two prisoners — Ravi Kumar (not eligible) and Suresh Kumar (eligible).
  Do not add more to the demo; reseed after any test that changes the local database.
- **Roles:** jail staff add prisoners (own jail); the reviewer verifies new records and uncertain readings; the DLSA
  adds/approves lawyers and assigns them; only the assigned lawyer sees case details, uploads documents and drafts;
  the system admin does technical work only (accounts, password resets, legal data, audit log, monitoring).
  Enforce every rule in the API, not just the menu. Out-of-scope records answer a uniform 404 and are audit-logged.
- **Evidence:** typed-in dates/sections stay REVIEW until a document confirms them; facts from a held document never
  count until confirmed. The engine decides; AI never decides eligibility. Never claim 100% correctness.
- **Drafts** are edited and exported, never "approved" in the app.
- **Languages:** every UI string goes in all three dictionaries (English, Kannada, Hindi); no hard-coded text.
- **Browser dialogs:** no `window.prompt/confirm/alert` — use `useDialog()` from `components/Dialog.tsx`.
- Record any behaviour change as a new `D-0xx` entry in `docs/DECISIONS.md`, with the test that covers it.
