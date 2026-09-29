# NyayaSetu web

Next.js (App Router) + TypeScript + Tailwind. All pages are client components that call the FastAPI backend
(`NEXT_PUBLIC_API_URL`, default `http://localhost:8000`) with a bearer token.

```bash
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
npx playwright test          # e2e (desktop + mobile); expects a seeded API on NYAYA_API_URL
SCREENSHOTS=1 npx playwright test screenshots --project=desktop   # refresh docs/screenshots
```

- `src/lib` — API client and types, auth, i18n (English, Kannada; Hindi scaffolded)
- `src/components` — shell, prisoner table, eligibility panel, timeline chart, document viewer with source
  highlighting, Defense Insights, drafts
- `src/app` — `/login`, `/lawyer`, `/prisoners/[id]`, `/jail`, `/dlsa`, `/reviewer`, `/admin`, `/alerts`
