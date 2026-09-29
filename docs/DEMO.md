# 2-minute demo script

Setup: `docker compose up -d --build && make seed` (or the local steps in README). Open http://localhost:3000.
All accounts use the demo password in the README. All people are synthetic.

**0:00 — The problem (10 s).** "Three in four prisoners in India are undertrials. The law already says many must be
released — but nobody has time to find them. NyayaSetu finds them."

**0:10 — Lawyer dashboard (20 s).** Sign in as `lawyer@nyayasetu.test`. Prisoners are sorted by urgency:
- **Anand Naik — CRITICAL: acquitted but detained.** Acquitted 12 days ago, still in jail.
- **Manjunath S — CRITICAL: beyond maximum.** IPC 379 (max 3 years); detained 3 years 2 months.
- **Basavaraj — URGENT: default bail.** Remanded 75 days ago, no charge sheet, 60-day period over.
- **Syed Imran — REVIEW: multiple cases.** Both legal readings of 479(2) shown side by side.

**0:30 — An eligible first-time offender (30 s).** Open **Ravi Kumar (s/o Ramaiah)**. Status ELIGIBLE: 949 days in
custody − 60 days the accused's own adjournment = 889 counted; threshold 853 (one-third of 7 years, first-time
offender) → 36 days overdue. Scroll "How this was decided": every step cites its rule. Note "demo-verified only" on
the charge — legal data must be verified before real use. **Timeline** tab: custody bar, hearings coloured by who
caused each adjournment.

**1:00 — Defense Insights (30 s).** Open **Defense insights** (privileged; only the assigned lawyer sees this):
- Produced before a magistrate after **53 hours** — click the evidence chip; the arrest memo opens with the exact
  span highlighted.
- Grounds of arrest not recorded; FIR lodged 7 days late with no explanation; FIR and charge sheet give different
  offence dates; confession to police relied on; no independent witnesses; FSL pending.
- "Similar judgments" come only from the retrieval corpus (here a labelled synthetic test corpus) — never generated.
Accept "Produced before Magistrate after 53 hours".

**1:30 — Grounded application (20 s).** **Drafts** → Section 479 application → Create. The verifier reports 100% of
sentences grounded; expand any sentence to see its source (fact, eligibility trace, legal record, insight, judgment).
Switch language to ಕನ್ನಡ and create again; export PDF/DOCX.

**1:50 — Safeguards (10 s).** Sign in as `jail@nyayasetu.test`: same prisoner, eligibility visible, **no Defense
Insights tab**; "Prepare superintendent's application" instead. Every view is in the admin audit log.
