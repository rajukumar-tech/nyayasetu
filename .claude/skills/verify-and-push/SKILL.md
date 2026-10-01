---
name: verify-and-push
description: Run NyayaSetu's full check (backend tests, 1,000-scenario harness, type/lint/i18n, browser tests, build), refresh screenshots and the two-prisoner demo, then commit as rajukumar-tech and push. Use when the user says "run everything", "verify", "push it" or "push with new screenshots".
---

# Verify and push NyayaSetu

Work from the repo root. Python is `.venv/Scripts/python`. Stop and report at the first real failure — never push red.

1. **Frontend static checks** (in `frontend/`): `npx tsc --noEmit`, `npx eslint src e2e`, `node scripts/check-i18n.mjs`.
2. **Backend tests** (in `backend/`, run in the background, ~17 min): `../.venv/Scripts/python -m pytest -q -p no:warnings`.
3. **Scenario harness** (in `backend/`, background, ~18 min): `../.venv/Scripts/python -m app.scenario_check`.
   It rewrites `docs/TEST_REPORT.md`; confirm Passed = Scenarios and Authorization failures = 0.
4. **Browser tests**: make sure the `api` and `web` dev servers are running (restart `api` after backend edits — it
   has no auto-reload), reseed with `../.venv/Scripts/python -m app.seed --reset`, then
   `PW_CHANNEL=chrome npx playwright test flows buttons`. Fix selectors that match two elements by scoping them
   (`page.getByRole("navigation")…`) rather than loosening the test.
5. **Screenshots** (only when the UI changed): reseed, `SCREENSHOTS=1 PW_CHANNEL=chrome npx playwright test screenshots
   --project=desktop`, look at the changed PNGs in `docs/screenshots/`, then reseed again so the demo is clean.
6. **Production build**: `npx next build` in `frontend/`.
7. **Docs**: update README / `docs/DEMO.md` / `docs/PRIVACY.md` if roles or screens changed, and add a `D-0xx` entry to
   `docs/DECISIONS.md` for any behaviour change.
8. **Commit and push**: `git status` (no `.env`, `*.db`, uploads), check `git config user.name` is `rajukumar-tech`,
   commit with a plain message — **no Co-Authored-By or AI attribution lines** — and `git push`.
9. Report: the commit hash, what changed, and each check's actual result (numbers, not "all good"). Mention anything
   skipped or not re-run after the last change.
