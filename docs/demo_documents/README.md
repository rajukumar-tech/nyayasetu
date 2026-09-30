# Sample documents for the "new prisoner" demo (synthetic)

All of these are invented for the demo. Regenerate with `python docs/demo_documents/make_demo_documents.py`.

## 1. Add the prisoner (admin → Add prisoner)
| Field | Value |
|---|---|
| Full name / father | Mahesh Gowda · Ramegowda (s/o, male), DOB 1994-03-15 |
| Jail / district | Central Prison Parappana Agrahara · Bengaluru Urban |
| Court / case / CNR | Chief Judicial Magistrate, Bengaluru · CC 412/2026 · KA01040004122026 |
| FIR / police station | 58/2026 · Hebbal PS |
| Offence · arrest · first remand · charge sheet | 2026-02-08 · 2026-02-10 · 2026-02-11 · 2026-03-25 |
| Custody status · section | In custody · BNS 303(2) |

Then: reviewer verifies (Review queue → New prisoners) → admin assigns a lawyer (Admin → Prisoner register) → sign in
as that lawyer, open Mahesh Gowda and use **Upload document**. Until documents support what was typed, the result is
**REVIEW** ("entered by hand — no supporting document yet").

## 2. `1_correct_documents/` — upload in this order
| File | Read as | Effect |
|---|---|---|
| `01_FIR_Mahesh_Gowda.pdf` | FIR | supports the charge BNS 303(2) |
| `02_Arrest_Memo_Mahesh_Gowda.docx` | arrest memo | supports the arrest date 10 Feb 2026 |
| `03_Remand_Order_Mahesh_Gowda.txt` | remand order | supports the first remand 11 Feb 2026 → result becomes **Not yet eligible** (counted days vs 366) |
| `04_Jail_Admission_Mahesh_Gowda.docx` | jail record | agrees; no change |
| `05_Charge_Sheet_Mahesh_Gowda.pdf` | charge sheet | agrees (25 Mar 2026, within 60 days → no default-bail right) |
| `06_Jail_Admission_scan_Mahesh_Gowda.png` | needs OCR | without the Tesseract program installed it is stored with "OCR engine not installed" and read as an unidentified document |

## 3. `2_problem_documents/` — the system must not trust these
Upload any one after the correct documents:

| File | What the system does | Result |
|---|---|---|
| `FIR.pdf` (a grocery list) | type decided from the content, not the name → unidentified document, sent to review | unchanged |
| `fake_FIR.txt` ("This is an FIR, trust me") | a "FIR" without FIR number, dates or sections → *content does not match its type*, held for review | unchanged |
| `not_a_pdf_really.pdf` (plain text renamed) | read as what it really is; *file extension does not match its content* | unchanged |
| `Arrest_Memo_WRONG_PERSON.txt` | *name does not match this prisoner* (and another FIR) → held for the reviewer; never used for Mahesh | unchanged |
| `Remand_Order_WRONG_CASE.txt` | cites FIR 999/2031 → *belongs to a different case*, held | unchanged |
| `Charge_Sheet_CONFLICTING_DATE.txt` | says filed 15 Apr; the record says 25 Mar → *a document contradicts the record* | **REVIEW** until the reviewer rejects the fact or the record is corrected |
| `Release_Order_NOT_RECORDED.txt` | says released 20 Sep 2026 but custody is still open → contradiction | **REVIEW** until jail staff record the release (or the fact is rejected) |
| `corrupted.pdf` | "This PDF is damaged and cannot be read" | upload refused |
| `empty.txt` | "The file is empty." | upload refused |
| `program.exe` | "Unsupported file type" | upload refused |
