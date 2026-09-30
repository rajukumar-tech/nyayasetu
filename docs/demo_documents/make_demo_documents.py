"""Generate SYNTHETIC sample documents for the "Mahesh Gowda" walk-through (see README.md in this folder).

    python docs/demo_documents/make_demo_documents.py

Everything here is invented for the demo — no real person, case or court record.
"""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).parent
NAME, FATHER = "Mahesh Gowda", "Ramegowda"
FIR, PS, COURT = "58/2026", "Hebbal PS", "Chief Judicial Magistrate, Bengaluru"

FIR_TEXT = f"""FIRST INFORMATION REPORT
Police Station: {PS}   FIR No.: {FIR}
District: Bengaluru Urban
Accused: {NAME} s/o {FATHER}, aged about 32 years
Date and time of occurrence: 08/02/2026 at 21:00 hrs
Date and time of FIR: 08/02/2026 at 23:30 hrs
Sections: u/s 303(2) BNS
Reason for delay in reporting:
Witnesses: CW-1 complainant Suresh (shop owner); CW-2 independent witness Prakash
Brief facts: The accused is alleged to have taken a mobile phone from the counter of a shop in Hebbal.
"""

ARREST_LINES = [
    "ARREST MEMO",
    f"FIR No.: {FIR}   Police Station: {PS}",
    f"Name of arrested person: {NAME} s/o {FATHER}",
    "Gender: male",
    "Date and time of arrest: 10/02/2026 18:00 hrs",
    "Grounds of arrest communicated: Yes",
    "Relative/friend informed: Yes (brother)",
    "Memo attested by witness: Yes",
    "Medical examination: Done at General Hospital",
]

REMAND_TEXT = f"""ORDER ON REMAND
In the Court of {COURT}
Crime No. {FIR} of {PS}
Accused: {NAME} s/o {FATHER}
Accused produced before Magistrate on: 11/02/2026 at 11:00 hrs
Remanded to judicial custody from 11/02/2026
Reasons: Recovery of the phone pending; the accused has no fixed address in the city.
"""

JAIL_TEXT = [
    "JAIL ADMISSION REGISTER EXTRACT",
    "Central Prison Parappana Agrahara",
    "UTP No.: 8812",
    f"Name: {NAME} s/o {FATHER}",
    "Date of admission: 11-02-2026",
]

CHARGE_SHEET_TEXT = f"""FINAL REPORT (CHARGE SHEET) u/s 193 BNSS
FIR No.: {FIR}  Police Station: {PS}
Date of filing: 25/03/2026
Accused: {NAME} s/o {FATHER}
Date of offence: 08/02/2026
Sections: 303(2) BNS
Witnesses cited: CW-1 Suresh, CW-2 Prakash, Investigating Officer
FSL report: Not applicable
Recovery: Mobile phone recovered in the presence of two panch witnesses
Confession: None
Test identification parade: Not applicable
"""


def pdf(path: Path, text: str) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for line in text.splitlines():
        c.drawString(50, y, line)
        y -= 18
    c.save()


def docx(path: Path, lines: list[str]) -> None:
    import docx as d
    doc = d.Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(str(path))


def png(path: Path, lines: list[str]) -> None:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1400, 80 + 60 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    for i, line in enumerate(lines):
        draw.text((40, 40 + 60 * i), line, fill="black", font=font)
    img.save(path)


def main() -> None:
    good = OUT / "1_correct_documents"
    bad = OUT / "2_problem_documents"
    good.mkdir(exist_ok=True)
    bad.mkdir(exist_ok=True)
    # ---- documents that agree with what was entered for Mahesh Gowda
    pdf(good / "01_FIR_Mahesh_Gowda.pdf", FIR_TEXT)
    docx(good / "02_Arrest_Memo_Mahesh_Gowda.docx", ARREST_LINES)
    (good / "03_Remand_Order_Mahesh_Gowda.txt").write_text(REMAND_TEXT, encoding="utf-8")
    docx(good / "04_Jail_Admission_Mahesh_Gowda.docx", JAIL_TEXT)
    pdf(good / "05_Charge_Sheet_Mahesh_Gowda.pdf", CHARGE_SHEET_TEXT)
    png(good / "06_Jail_Admission_scan_Mahesh_Gowda.png", JAIL_TEXT)
    # ---- documents the system must NOT trust blindly
    pdf(bad / "FIR.pdf", "Grocery list for the week\nRice 5 kg, dal 2 kg, onions, tomatoes\nCricket: India 245/6 in 50 overs\n")
    (bad / "fake_FIR.txt").write_text("This is an FIR.\nTrust me, it is official.\n", encoding="utf-8")
    (bad / "Arrest_Memo_WRONG_PERSON.txt").write_text(
        "ARREST MEMO\nFIR No.: 55/2019   Police Station: Lashkar PS\n"
        "Name of arrested person: Mohammed Rafiq s/o Yusuf Khan\nDate and time of arrest: 03/05/2019 10:00 hrs\n"
        "Grounds of arrest communicated: Yes\n", encoding="utf-8")
    (bad / "Remand_Order_WRONG_CASE.txt").write_text(
        f"ORDER ON REMAND\nIn the Court of {COURT}\nCrime No. 999/2031 of Yeshwanthpur PS\nFIR No.: 999/2031\n"
        f"Accused: {NAME} s/o {FATHER}\nRemanded to judicial custody from 01/01/2025\n", encoding="utf-8")
    (bad / "Charge_Sheet_CONFLICTING_DATE.txt").write_text(
        CHARGE_SHEET_TEXT.replace("Date of filing: 25/03/2026", "Date of filing: 15/04/2026"), encoding="utf-8")
    (bad / "Release_Order_NOT_RECORDED.txt").write_text(
        f"RELEASE ORDER\nIn the Court of {COURT}\nCrime No. {FIR} of {PS}\nAccused: {NAME} s/o {FATHER}\n"
        "The accused is set at liberty on executing a personal bond.\nDate of release: 20/09/2026\n", encoding="utf-8")
    (bad / "corrupted.pdf").write_bytes(b"%PDF-1.4\n this file was cut off in the middle of")
    (bad / "not_a_pdf_really.pdf").write_text("Just some notes typed in Notepad and renamed to .pdf\n", encoding="utf-8")
    (bad / "empty.txt").write_bytes(b"")
    (bad / "program.exe").write_bytes(b"MZ\x90\x00 not a document")
    print(f"wrote sample documents to {OUT}")


if __name__ == "__main__":
    main()
