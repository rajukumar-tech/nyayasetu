# Demo script

Setup: `python -m app.seed --reset` in `backend/` (local) or `make seed` (Docker). This loads exactly **two synthetic
prisoners**. Open http://localhost:3000 — every account uses the demo password `nyaya-demo-2026`.

> Everything here is synthetic. Computers calculate and flag; lawyers and judges decide.

| Prisoner | Result | Why |
|---|---|---|
| **Ravi Kumar** (DEMO A) | **Not yet eligible** | BNS 303(2), max 3 years (1,096 days). First-time offender → threshold ⅓ = 366. Custody 263 days − 21 days of adjournment he asked for = **242 counted** < 366 → eligible in 124 days if still in custody. Charge sheet 56 days after first remand → no default-bail right. |
| **Suresh Kumar** (DEMO B) | **Eligible (Section 479)** | IPC 420 (offence Dec 2023 → IPC), max 7 years (2,557 days). First-time → threshold 853. Custody 991 − 30 = **961 counted** ≥ 853 → threshold reached **108 days ago**. Charge sheet 49 days after remand → no default-bail right. |

## 1. The NOT ELIGIBLE prisoner — Ravi Kumar
Sign in as `lawyer@nyayasetu.test` → **My prisoners** → **Ravi Kumar** (badge *Demo A*).
- *Section 479 BNSS* card: **Not yet eligible**; *How the numbers add up* shows 263 − 21 = 242, threshold ⅓ × 1096 = 366,
  "242 < 366: 124 more days needed".
- *Default bail* card is separate: first remand and charge-sheet dates, "no default-bail right on record".
- **Timeline** tab: custody bar, hearings coloured by who caused each adjournment (one red = the accused's 21 days).
- **Facts & documents**: open the arrest memo / remand order — each extracted date is highlighted at its source.

## 2. The ELIGIBLE prisoner — Suresh Kumar
Open **Suresh Kumar** (badge *Demo B*): **Eligible (479)**, 961 counted ≥ 853, eligible from the date shown,
108 counted days beyond it. **Drafts** → *Section 479 BNSS application* → **Create** → "100% of N sentences grounded;
0 rejected"; expand a sentence to see its source; export PDF/DOCX.

## 3. Kannada and Hindi
Use the language menu (top right): ಕನ್ನಡ, then हिन्दी. Every label, status, the calculation, flags and alerts switch;
names, case/CNR numbers and section numbers stay as they are. The engine's rule-by-rule trace is kept in English and
labelled as the recorded detail.

## 4. New prisoner → review → lawyer
1. Sign in as `jail@nyayasetu.test` (menu: **Prisoners · Add prisoner · Alerts**). **Add prisoner** (into their own
   jail): name, court, section (e.g. BNS 303(2)), arrest and first-remand dates → *Create prisoner*.
   The numbers are computed at once but the result is **REVIEW** — "entered by hand, no supporting document yet" —
   because typed-in data is not evidence. The record is **unassigned** and "waiting for review" on the DLSA's
   **District** page (the lawyer drop-down is locked).
2. Sign in as `reviewer@nyayasetu.test` → **Review queue**. The help box at the top explains the queue in three steps;
   each item shows the prisoner, the document, the computer's confidence, **why it is here**, **what to check** and
   **what each button will do**. Open *New prisoners* → check the details → **verify** (or *Return for correction*).
3. Sign in as `dlsa@nyayasetu.test` → **District** → the prisoner's row → *Assign lawyer*. Only now does that lawyer see the prisoner — and only
   that lawyer can upload the FIR, arrest memo, remand order and jail record. When those documents confirm the typed
   dates and sections, the REVIEW turns into a definite result (e.g. *Not yet eligible*).

## 5. New lawyer
DLSA → **Lawyers** → *Add a lawyer* (tick *Approve now*, or approve later). The new lawyer signs in and sees
**zero prisoners** until the DLSA assigns one on the District page. *Deactivate* blocks sign-in at once and makes their prisoners
unassigned (an alert asks for reassignment); reassign on the District page.

## 6. Lawyer access restriction
As `lawyer@nyayasetu.test` open Suresh Kumar and copy the URL. Sign out, sign in as `lawyer2@nyayasetu.test`: the list is
empty; paste the URL → "Record not found, or not available to your account." The API gives the same answer as for an ID
that does not exist, and logs the attempt.

## 7. Admin audit log
The system admin (`admin@nyayasetu.test`, menu: **Admin** only) does technical work: accounts, password resets,
legal data, monitoring — no prisoners, lawyers or assignment. **Admin → Audit log → All entries**: the sign-ins, the
prisoner the jail added, the DLSA's assignment, the reviewer's verification and the other lawyer's refused attempt (*access denied*, in red) — each with
time, user, role, action, target and outcome.
