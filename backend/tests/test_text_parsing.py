"""Section 9 checklist, items 34–37 (dates & section strings)."""
from __future__ import annotations

from datetime import date

from hypothesis import given, strategies as st

from app.extraction.dates import extract_dates, resolve_ambiguity
from app.extraction.sections import parse_sections

TODAY = date(2026, 1, 15)


def one(text):
    ds = extract_dates(text, TODAY)
    assert len(ds) == 1, ds
    return ds[0]


def test_34_dmy_vs_mdy_ambiguity_resolution_and_flagging():
    d = one("Remanded on 03/04/2025")
    assert d.value == date(2025, 4, 3) and "AMBIGUOUS_DMY_MDY" in d.flags and d.confidence < 0.8
    assert d.alternatives == [date(2025, 3, 4)]
    # unambiguous day > 12
    d = one("Arrested 25/03/2025")
    assert d.value == date(2025, 3, 25) and not d.flags
    # only month-first is valid → parsed as mm/dd but flagged
    d = one("dated 03/25/2025")
    assert d.value == date(2025, 3, 25) and "PARSED_AS_MDY" in d.flags
    # context resolution: other dates in the record are in early March
    ds = resolve_ambiguity(extract_dates("FIR 01/03/2025 remand 03/04/2025", TODAY), [date(2025, 3, 2)])
    amb = ds[1]
    assert amb.value == date(2025, 3, 4) and "AMBIGUITY_RESOLVED_BY_CONTEXT" in amb.flags


def test_35_kannada_and_hindi_numerals_and_month_names():
    assert one("ಬಂಧನದ ದಿನಾಂಕ: ೧೨/೦೩/೨೦೨೪").value == date(2024, 3, 12)
    assert one("ಅಪರಾಧದ ದಿನಾಂಕ: ೫ ಮಾರ್ಚ್ ೨೦೨೪").value == date(2024, 3, 5)
    assert one("गिरफ्तारी: १२ मार्च २०२४").value == date(2024, 3, 12)
    assert one("on 12th March 2025").value == date(2025, 3, 12)
    assert one("March 12, 2025").value == date(2025, 3, 12)
    d = one("ದಿನಾಂಕ ೧೨/೦೩/೨೦೨೪")
    assert d.text == "೧೨/೦೩/೨೦೨೪" and d.iso == "2024-03-12"  # span points at original script


def test_36_two_digit_partial_impossible_future_dates():
    d = one("admitted 12.03.24")
    assert d.value == date(2024, 3, 12) and "TWO_DIGIT_YEAR" in d.flags
    d = one("born 12.03.64")
    assert d.value == date(1964, 3, 12)
    d = one("sometime in March 2023")
    assert d.value == date(2023, 3, 1) and d.precision == "month" and "PARTIAL_DATE" in d.flags and d.confidence <= 0.5
    d = one("dated 31/02/2024")
    assert d.value is None and "IMPOSSIBLE_DATE" in d.flags
    d = one("next date 12/12/2027")
    assert "FUTURE_DATE" in d.flags and d.confidence <= 0.3
    d = one("on 3O/l2/2024")  # OCR: O for 0, l for 1
    assert d.value == date(2024, 12, 30) and "OCR_DIGIT_CORRECTED" in d.flags


@given(st.dates(min_value=date(1990, 1, 1), max_value=date(2025, 12, 31)))
def test_36b_property_textual_dates_roundtrip(d):
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December"]
    assert one(f"on {d.day} {months[d.month - 1]} {d.year}.").value == d
    kn = f"{d.day:02d}/{d.month:02d}/{d.year}".translate(str.maketrans("0123456789", "೦೧೨೩೪೫೬೭೮೯"))
    got = one(f"ದಿನಾಂಕ {kn}")
    assert got.value == d or (d.day <= 12 and d.month <= 12 and got.alternatives == [d])


def labels(text, default=None):
    return [(c.act, c.section, c.modifier) for c in parse_sections(text, default)]


def test_37_section_strings():
    assert labels("u/s 379 IPC") == [("IPC", "379", None)]
    assert labels("S.379 IPC") == [("IPC", "379", None)]
    assert labels("379 IPC") == [("IPC", "379", None)]
    assert labels("u/s 379/34 IPC") == [("IPC", "379", "common_intention")]
    assert labels("u/s 379 r/w 34 IPC") == [("IPC", "379", "common_intention")]
    assert labels("Sections 323, 324, 504 & 506 IPC") == [("IPC", s, None) for s in ("323", "324", "504", "506")]
    assert labels("u/s 307 r/w 120B IPC") == [("IPC", "307", "conspiracy")]
    assert labels("u/s 380, 511 IPC") == [("IPC", "380", "attempt")]
    assert labels("u/s 303(2) BNS") == [("BNS", "303(2)", None)]
    assert labels("u/s 318(4), 3(5) BNS") == [("BNS", "318(4)", "common_intention")]
    assert labels("Sec. 20(b)(ii)(A) of NDPS Act") == [("NDPS", "20(b)(ii)(A)", None)]
    assert labels("ಕಲಂಗಳು: u/s 305 BNS") == [("BNS", "305", None)]
    got = parse_sections("u/s 3l9 IPC")  # OCR l → 1
    assert got[0].section == "319" and "OCR_CORRECTED" in got[0].flags
    got = parse_sections("u/s 420")  # act missing
    assert got[0].act == "UNKNOWN" and "ACT_NOT_STATED" in got[0].flags and got[0].confidence < 0.8
    assert labels("u/s 420", default="IPC")[0] == ("IPC", "420", None)
    assert parse_sections("Case No 379 of 2024") == []  # bare numbers are not sections
