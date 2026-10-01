---
name: add-ui-text
description: Add or change any text shown in the NyayaSetu web app — new labels, buttons, help text, errors — in English, Kannada and Hindi together. Use whenever a frontend change needs words on screen.
---

# Add UI text in all three languages

All screen text comes from `frontend/src/lib/i18n/en.ts`, `kn.ts` and `hi.ts`. `en.ts` defines the `Dict` type, so a
key missing from `kn.ts` or `hi.ts` is a type error, and `scripts/check-i18n.mjs` fails on untranslated values or
hard-coded text in components.

1. Pick a camelCase key near related keys (prefix families: `kind_`, `attr_`, `field_`, `docType_`, `status_`, `rv…`
   for the reviewer). Use `{name}` placeholders for values, never string concatenation.
2. Add the key to **all three** files at the same place. Write real Kannada and Hindi — plain words a jail clerk or
   paralegal understands, not transliterated English. Keep legal identifiers as used in Karnataka courts:
   Section 479 BNSS, IPC, BNS, FIR, CNR, DLSA, PDF, DOCX.
3. In components use the hook: `const { t, tk, fd, fdt } = useI18n();`
   - `t("key", { n })` for a fixed key; `tk("prefix_", code)` for a code-driven label (falls back to the code);
   - `fd(date)` / `fdt(timestamp)` for dates — never print ISO strings.
4. Engine traces and technical titles stay English: wrap them in `lang="en"` and label them as recorded detail.
5. Check: `cd frontend && npx tsc --noEmit && node scripts/check-i18n.mjs` (the PostToolUse hook also runs the checker
   after every edit under `frontend/src/`).
6. If an e2e test finds an element by its English name, keep that name stable or update `frontend/e2e/*.spec.ts`.
