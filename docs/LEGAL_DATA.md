# Legal data

All legal facts live in `data/legal/*.yaml`; code never hardcodes them. Every record has a `source` and a `verified`
flag. The data version (a hash of all files + verification overlay) is stored with every eligibility result.

| File | Contents |
|---|---|
| `ipc.yaml` | IPC sections (punishment for offences before 1 July 2024) + liability rules (34, 109, 120B, 511) |
| `bns.yaml` | BNS equivalents |
| `special_acts.yaml` | NDPS, POCSO, Arms, UAPA, SC/ST, PMLA samples — `special_law: true` → never auto-decided |
| `ipc_bns_mapping.yaml` | one-to-one / no-equivalent mapping (display & research only) |
| `rules.yaml` | 479 fractions, default-bail periods, surety window, prior-conviction policy, derivation rules (attempt, abetment, conspiracy, common intention), plea-bargaining exclusions, procedural-safeguard references |
| `ingredients.yaml` | crude ingredient keyword screens for charge-level insights |

## Verification status: **everything is unverified**

No record has been checked against the official text. Sources are cited only as "India Code — <Act>"; the
`punishment_summary` fields are paraphrases, not quotations. Values the author was unsure of are `null` (e.g.
bailability/compoundability of IPC 324). Records that most need checking first, because the demo relies on them:

- IPC 379, 380, 323, 324, 406, 411, 420, 302, 326, 354, 392, 506 and BNS 303(2), 305, 318(4)
- `rules.section_479` (fractions, 479(2) wording), `rules.default_bail` (BNSS 187(3) periods and the "10 years" limb)
- `rules.prior_convictions.juvenile_adjudication_counts` (JJ Act s.24)
- `rules.derivations.*` (IPC 511/115/116/120B and BNS equivalents)
- `rules.plea_bargaining` (ceiling and excluded categories)
- Procedural references in `rules.yaml` (BNSS section numbers for arrest safeguards) — these are cited in Defense
  Insights and must be correct before any filing

## How to verify a record
1. Open the official text on India Code or the Gazette.
2. In the admin UI (Legal data), click **Verify** and state exactly what you checked.
3. The verification is stored in `legal_verifications`, audit-logged, and changes the legal-data version, so every
   later eligibility result records which verified data it used.
4. If the YAML value was wrong, correct the YAML in a reviewed pull request and re-verify.
