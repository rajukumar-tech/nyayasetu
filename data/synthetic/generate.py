"""Synthetic data generator for NyayaSetu — NO real prisoner data.

Produces, with known ground truth:
  * demo prisoners covering every edge case in spec Section 9 (hand-specified scenarios)
  * a random population of prisoners with multiple cases, prior convictions, bail, transfers
  * source documents (FIR, arrest memo, remand order, charge sheet, order sheets, jail records)
    in English and Kannada (some with Hindi dates), with OCR-like noise
  * entity-resolution records: the same person across courts/jails/scripts + look-alikes
  * labelled adjournment reasons for the delay-attribution classifier

All dates are relative to --today so the demo stays current.

    python data/synthetic/generate.py --today 2026-09-29 --seed 7 --out data/synthetic/out
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

KN_DIGITS = str.maketrans("0123456789", "೦೧೨೩೪೫೬೭೮೯")
HI_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")
KN_MONTHS = ["ಜನವರಿ", "ಫೆಬ್ರವರಿ", "ಮಾರ್ಚ್", "ಏಪ್ರಿಲ್", "ಮೇ", "ಜೂನ್", "ಜುಲೈ", "ಆಗಸ್ಟ್", "ಸೆಪ್ಟೆಂಬರ್", "ಅಕ್ಟೋಬರ್", "ನವೆಂಬರ್", "ಡಿಸೆಂಬರ್"]
HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]

DISTRICTS = {
    "Bengaluru Urban": {"jails": ["Central Prison Parappana Agrahara"], "stations": ["Jayanagar PS", "Shivajinagar PS", "Yeshwanthpur PS"],
                        "court": "Chief Judicial Magistrate, Bengaluru"},
    "Mysuru": {"jails": ["Central Prison Mysuru"], "stations": ["Lashkar PS", "Nazarbad PS"],
               "court": "Principal Civil Judge & JMFC, Mysuru"},
    "Kalaburagi": {"jails": ["Central Prison Kalaburagi"], "stations": ["Station Bazar PS", "Brahmpur PS"],
                   "court": "Chief Judicial Magistrate, Kalaburagi"},
}

# name → variants (Latin spellings, aliases, Kannada script). Used for ER ground truth.
NAME_VARIANTS = {
    "Ravi Kumar": ["RAVI KUMAR", "Ravikumar", "Ravi Kumaar", "R. Kumar", "ರವಿ ಕುಮಾರ್"],
    "Manjunath S": ["Manjunatha S", "MANJUNATH", "Manjunath @ Manja", "ಮಂಜುನಾಥ ಎಸ್"],
    "Syed Imran": ["Sayed Imran", "Imran @ Sheru", "Syed Imraan", "ಸೈಯದ್ ಇಮ್ರಾನ್"],
    "Basavaraj": ["Basavaraju", "Basavraj", "BASAVARAJ", "ಬಸವರಾಜ"],
    "Lakshmi Devi": ["Laxmi Devi", "Lakshmamma", "Smt. Lakshmi", "ಲಕ್ಷ್ಮಿ ದೇವಿ"],
    "Mohammed Rafiq": ["Md. Rafeeq", "Mohd Rafik", "Mohammad Rafiq", "ಮೊಹಮ್ಮದ್ ರಫೀಕ್"],
    "Suresh Gowda": ["Suresh Gouda", "Gowda Suresh", "Sri Suresh Gowda", "ಸುರೇಶ್ ಗೌಡ"],
    "Venkatesh": ["Venkatesha", "Venkatesh @ Venki", "Venkatesh urf Venki", "ವೆಂಕಟೇಶ್"],
    "Shivanna": ["Shivanna", "SHIVANNA", "Shivana", "ಶಿವಣ್ಣ"],
    "Anand Naik": ["Anand Nayak", "Ananda Naik", "A. Naik", "ಆನಂದ ನಾಯ್ಕ"],
    "Kavya R": ["Kavya", "Kavyashree R", "Smt Kavya", "ಕಾವ್ಯ ಆರ್"],
    "Prakash Rao": ["Prakash Rao", "Prakasha Rao", "Prakash R", "ಪ್ರಕಾಶ್ ರಾವ್"],
    "Nagesh": ["Nagesha", "Nagesh @ Kari", "Nagesh", "ನಾಗೇಶ್"],
    "Harish Shetty": ["Harisha Shetty", "Harish Shetti", "H. Shetty", "ಹರೀಶ್ ಶೆಟ್ಟಿ"],
    "Imtiyaz Khan": ["Imtiaz Khan", "Imtiyaz Kaan", "Imtiyaz @ Pappu", "ಇಮ್ತಿಯಾಜ್ ಖಾನ್"],
    "Girish": ["Girisha", "Girish", "GIRISH", "ಗಿರೀಶ್"],
}
FATHERS = ["Ramaiah", "Krishnappa", "Hanumanthappa", "Abdul Rahim", "Siddappa", "Nagaraj", "Channabasappa",
           "Mallesh", "Govindappa", "Venkataramanappa", "Shivalingaiah", "Yusuf Khan"]
FATHER_VARIANTS = {"Ramaiah": ["Ramaiah", "Ramayya", "Ramaih", "ರಾಮಯ್ಯ"], "Krishnappa": ["Krishnappa", "Krishnapa", "ಕೃಷ್ಣಪ್ಪ"],
                   "Hanumanthappa": ["Hanumanthappa", "Hanumantappa", "Hanumanthapa"], "Abdul Rahim": ["Abdul Rahim", "Abdul Raheem", "A. Rahim"],
                   "Siddappa": ["Siddappa", "Siddapa", "ಸಿದ್ದಪ್ಪ"], "Nagaraj": ["Nagaraj", "Nagaraja", "ನಾಗರಾಜ್"],
                   "Channabasappa": ["Channabasappa", "Chennabasappa"], "Mallesh": ["Mallesh", "Mallesha"],
                   "Govindappa": ["Govindappa", "Govindapa"], "Venkataramanappa": ["Venkataramanappa", "Venkataramanapa"],
                   "Shivalingaiah": ["Shivalingaiah", "Shivalingayya"], "Yusuf Khan": ["Yusuf Khan", "Yousuf Khan"]}

ADJOURNMENT_REASONS = [
    ("Adjourned at the request of the accused counsel.", "accused"),
    ("Accused absent. Exemption petition filed. Adjourned.", "accused"),
    ("Accused sought time to engage counsel.", "accused"),
    ("Counsel for accused not present; adjourned at accused's request.", "accused"),
    ("Accused counsel on leave, time sought by defence.", "accused"),
    ("PP sought time to secure witnesses.", "prosecution"),
    ("Prosecution witness absent. Summons to be re-issued.", "prosecution"),
    ("IO not present. Case diary not produced.", "prosecution"),
    ("FSL report awaited by prosecution.", "prosecution"),
    ("Witness CW-2 absent despite service. Issue NBW.", "prosecution"),
    ("Presiding Officer on leave.", "court"),
    ("PO on leave. Adjourned.", "court"),
    ("Court busy with part-heard matter.", "court"),
    ("Time over. Adjourned.", "court"),
    ("Court vacation.", "court"),
    ("Accused not produced by jail authorities. Escort not available.", "prosecution"),
    ("Accused not produced from jail; video link not working.", "prosecution"),
    ("Lawyers' boycott; no work.", "other"),
    ("Advocates abstained from work as per Bar resolution.", "other"),
    ("Proceedings suspended in view of COVID-19 directions.", "other"),
    ("Both sides sought time.", "both"),
    ("Adjourned at the request of both counsel for settlement talks.", "both"),
    ("Adjourned.", "unknown"),
    ("", "unknown"),
    ("ಆರೋಪಿಯ ಪರ ವಕೀಲರ ಕೋರಿಕೆಯ ಮೇರೆಗೆ ಮುಂದೂಡಲಾಗಿದೆ.", "accused"),
    ("ಸಾಕ್ಷಿ ಗೈರುಹಾಜರಿ. ಸರ್ಕಾರಿ ಅಭಿಯೋಜಕರು ಸಮಯ ಕೋರಿದರು.", "prosecution"),
    ("ನ್ಯಾಯಾಧೀಶರು ರಜೆಯಲ್ಲಿದ್ದಾರೆ.", "court"),
    ("Accused ill, admitted to hospital; medical certificate filed.", "accused"),
    ("New counsel for accused filed vakalat; sought time.", "accused"),
    ("Prosecution to file additional charge sheet; time granted.", "prosecution"),
]


def fmt_date(d: date, style: str) -> str:
    if style == "dmy":
        return d.strftime("%d/%m/%Y")
    if style == "dmy_dash":
        return d.strftime("%d-%m-%Y")
    if style == "long":
        suffix = "th" if 11 <= d.day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d.day % 10, "th")
        return f"{d.day}{suffix} {EN_MONTHS[d.month - 1]} {d.year}"
    if style == "kn":
        return f"{d.day:02d}/{d.month:02d}/{d.year}".translate(KN_DIGITS)
    if style == "kn_month":
        return f"{str(d.day).translate(KN_DIGITS)} {KN_MONTHS[d.month - 1]} {str(d.year).translate(KN_DIGITS)}"
    if style == "hi_month":
        return f"{str(d.day).translate(HI_DIGITS)} {HI_MONTHS[d.month - 1]} {str(d.year).translate(HI_DIGITS)}"
    if style == "yy":
        return d.strftime("%d.%m.%y")
    raise ValueError(style)


def ocr_noise(text: str, rng: random.Random, rate: float) -> str:
    """Light OCR-like corruption that keeps labels readable: O↔0, l↔1, dropped chars."""
    if rate <= 0:
        return text
    swaps = {"0": "O", "O": "0", "1": "l", "l": "1", "5": "S", "S": "5"}
    out = []
    for ch in text:
        r = rng.random()
        if ch in swaps and r < rate:
            out.append(swaps[ch])
        elif ch.isalpha() and r < rate / 4:
            continue
        else:
            out.append(ch)
    return "".join(out)


@dataclass
class Doc:
    doc_type: str
    language: str
    text: str
    case_ref: str | None
    is_primary: bool = True
    noisy: bool = False


@dataclass
class SynthPerson:
    truth_id: str
    scenario: str
    canonical_name: str
    relative_name: str
    relation: str
    gender: str
    dob: str
    district: str
    jail: str
    vulnerability: list[str]
    expected_status: str | None
    cases: list[dict] = field(default_factory=list)
    custody_events: list[dict] = field(default_factory=list)
    convictions: list[dict] = field(default_factory=list)
    documents: list[dict] = field(default_factory=list)
    facts_summary: str = ""


class Builder:
    def __init__(self, today: date, rng: random.Random):
        self.today = today
        self.rng = rng
        self.people: list[SynthPerson] = []
        self._case_no = 100

    def ago(self, n: int) -> date:
        return self.today - timedelta(days=n)

    def next_case(self, district: str) -> tuple[str, str, str]:
        self._case_no += 1
        cnr = f"KA{list(DISTRICTS).index(district) + 1:02d}0{self.rng.randint(1, 9)}{self._case_no:06d}{self.today.year - 1}"
        return f"CC {self._case_no}/{self.today.year - 1}", cnr, f"{self._case_no % 300}/{self.today.year - 2}"

    # ------------------------------------------------------------------ documents
    def fir_doc(self, p: SynthPerson, case: dict, *, offence_dt: datetime, fir_dt: datetime, delay_expl: str | None,
                witnesses: str, lang: str = "en", noise: float = 0.0) -> dict:
        sections = ", ".join(f"{c['section']} {c['act']}" for c in case["charges"])
        style = "dmy" if lang == "en" else "kn"
        if lang == "kn":
            text = (f"ಪ್ರಥಮ ಮಾಹಿತಿ ವರದಿ (FIR)\nಪೊಲೀಸ್ ಠಾಣೆ: {case['police_station']}  FIR ಸಂಖ್ಯೆ: {case['fir_number']}\n"
                    f"ಆರೋಪಿ: {p.canonical_name} ತಂದೆ {p.relative_name}\n"
                    f"ಅಪರಾಧದ ದಿನಾಂಕ: {fmt_date(offence_dt.date(), 'kn_month')}\n"
                    f"FIR ದಿನಾಂಕ: {fmt_date(fir_dt.date(), style)} ಸಮಯ {fir_dt.strftime('%H:%M')}\n"
                    f"ಕಲಂಗಳು: u/s {sections}\n")
        else:
            text = (f"FIRST INFORMATION REPORT\nPolice Station: {case['police_station']}   FIR No.: {case['fir_number']}\n"
                    f"District: {p.district}\n"
                    f"Accused: {p.canonical_name} {p.relation} {p.relative_name}, aged about {age(p, offence_dt.date())} years\n"
                    f"Date and time of occurrence: {fmt_date(offence_dt.date(), 'dmy')} at {offence_dt.strftime('%H:%M')} hrs\n"
                    f"Date and time of FIR: {fmt_date(fir_dt.date(), 'dmy')} at {fir_dt.strftime('%H:%M')} hrs\n"
                    f"Sections: u/s {sections}\n"
                    f"Reason for delay in reporting: {delay_expl or ''}\n"
                    f"Witnesses: {witnesses}\n"
                    f"Brief facts: {case.get('facts', '')}\n")
        return asdict(Doc("fir", lang, ocr_noise(text, self.rng, noise), case["ref"], True, noise > 0))

    def arrest_memo(self, p: SynthPerson, case: dict, *, arrest_dt: datetime, grounds: str, relative_informed: str,
                    attested: str, medical: str, woman_officer: str = "", night_permission: str = "",
                    noise: float = 0.0) -> dict:
        text = (f"ARREST MEMO\nFIR No.: {case['fir_number']}   Police Station: {case['police_station']}\n"
                f"Name of arrested person: {p.canonical_name} {p.relation} {p.relative_name}\n"
                f"Gender: {p.gender}\n"
                f"Date and time of arrest: {fmt_date(arrest_dt.date(), 'dmy')} {arrest_dt.strftime('%H:%M')} hrs\n"
                f"Grounds of arrest communicated: {grounds}\n"
                f"Relative/friend informed: {relative_informed}\n"
                f"Memo attested by witness: {attested}\n"
                f"Medical examination: {medical}\n"
                + (f"Woman police officer present: {woman_officer}\n" if p.gender == "female" else "")
                + (f"Prior permission of Magistrate (arrest after sunset): {night_permission}\n" if night_permission else ""))
        return asdict(Doc("arrest_memo", "en", ocr_noise(text, self.rng, noise), case["ref"], True, noise > 0))

    def remand_order(self, p: SynthPerson, case: dict, *, produced_dt: datetime, remand_date: date, custody: str,
                     reasons: str, lang: str = "en") -> dict:
        if lang == "kn":
            text = (f"ರಿಮಾಂಡ್ ಆದೇಶ\nನ್ಯಾಯಾಲಯ: {case['court']}\nಆರೋಪಿ: {p.canonical_name}\n"
                    f"ಹಾಜರುಪಡಿಸಿದ ದಿನಾಂಕ: {fmt_date(produced_dt.date(), 'kn')} ಸಮಯ {produced_dt.strftime('%H:%M')}\n"
                    f"ನ್ಯಾಯಾಂಗ ಬಂಧನಕ್ಕೆ ರಿಮಾಂಡ್ ದಿನಾಂಕ: {fmt_date(remand_date, 'kn')}\n")
        else:
            text = (f"ORDER ON REMAND\nIn the Court of {case['court']}\nCrime No. {case['fir_number']} of {case['police_station']}\n"
                    f"Accused: {p.canonical_name} {p.relation} {p.relative_name}\n"
                    f"Accused produced before Magistrate on: {fmt_date(produced_dt.date(), 'dmy')} at {produced_dt.strftime('%H:%M')} hrs\n"
                    f"Remanded to {custody} custody from {fmt_date(remand_date, 'dmy')}\n"
                    f"Reasons: {reasons}\n")
        return asdict(Doc("remand_order", lang, text, case["ref"]))

    def charge_sheet(self, p: SynthPerson, case: dict, *, filed: date, offence_date: date, witnesses: str,
                     fsl: str, recovery: str, confession: str, tip: str, weapon: str = "") -> dict:
        sections = ", ".join(f"{c['section']} {c['act']}" for c in case["charges"])
        text = (f"FINAL REPORT (CHARGE SHEET) u/s 193 BNSS\nFIR No.: {case['fir_number']}  Police Station: {case['police_station']}\n"
                f"Date of filing: {fmt_date(filed, 'long')}\n"
                f"Accused: {p.canonical_name} {p.relation} {p.relative_name}\n"
                f"Date of offence: {fmt_date(offence_date, 'dmy')}\n"
                f"Sections: {sections}\n"
                f"Witnesses cited: {witnesses}\n"
                f"FSL report: {fsl}\n"
                f"Recovery: {recovery}\n"
                f"Confession: {confession}\n"
                f"Test identification parade: {tip}\n"
                + (f"Weapon: {weapon}\n" if weapon else ""))
        return asdict(Doc("charge_sheet", "en", text, case["ref"]))

    def order_sheet(self, case: dict, hearings: list[dict]) -> dict:
        lines = [f"ORDER SHEET\n{case['court']}\n{case['case_number']}  (CNR {case['cnr']})"]
        for h in hearings:
            nd = f" Call on {fmt_date(date.fromisoformat(h['next_date']), 'dmy')}." if h.get("next_date") else ""
            lines.append(f"{fmt_date(date.fromisoformat(h['date']), 'dmy')}: {h['reason_text']}{nd}")
        return asdict(Doc("court_order", "en", "\n".join(lines) + "\n", case["ref"]))

    def jail_record(self, p: SynthPerson, case: dict | None, *, admitted: date, prisoner_no: str, lang: str = "en",
                    stated_arrest: date | None = None) -> dict:
        if lang == "kn":
            text = (f"ಕಾರಾಗೃಹ ದಾಖಲೆ\n{p.jail}\nಕೈದಿ ಸಂಖ್ಯೆ: {prisoner_no}\nಹೆಸರು: {p.canonical_name}\n"
                    f"ದಾಖಲಾದ ದಿನಾಂಕ: {fmt_date(admitted, 'kn')}\n")
        else:
            text = (f"JAIL ADMISSION REGISTER EXTRACT\n{p.jail}\nUTP No.: {prisoner_no}\nName: {p.canonical_name} "
                    f"{p.relation} {p.relative_name}\nDate of admission: {fmt_date(admitted, 'dmy_dash')}\n"
                    + (f"Date of arrest (as stated): {fmt_date(stated_arrest, 'dmy_dash')}\n" if stated_arrest else ""))
        return asdict(Doc("jail_record", lang, text, case["ref"] if case else None, is_primary=False))

    # ------------------------------------------------------------------ helpers
    def person(self, truth_id: str, scenario: str, name: str, *, gender: str = "male", age_years: int = 30,
               district: str = "Bengaluru Urban", expected: str | None = None, vulnerability: list[str] | None = None,
               father: str | None = None) -> SynthPerson:
        father = father or self.rng.choice(FATHERS)
        relation = "s/o" if gender == "male" else self.rng.choice(["d/o", "w/o"])
        dob = self.today - timedelta(days=int(age_years * 365.25) + self.rng.randint(0, 300))
        p = SynthPerson(truth_id, scenario, name, father, relation, gender, dob.isoformat(), district,
                        DISTRICTS[district]["jails"][0], vulnerability or [], expected)
        self.people.append(p)
        return p

    def case(self, p: SynthPerson, ref: str, charges: list[tuple[str, str] | tuple[str, str, str]], *, status: str = "trial",
             offence_ago: int, **dates: int | None) -> dict:
        cn, cnr, fir = self.next_case(p.district)
        offence = self.ago(offence_ago)
        c = {"ref": ref, "case_number": cn, "cnr": cnr, "fir_number": fir, "court": DISTRICTS[p.district]["court"],
             "district": p.district, "state": "Karnataka",
             "police_station": self.rng.choice(DISTRICTS[p.district]["stations"]), "status": status,
             "offence_date": offence.isoformat(),
             "charges": [{"act": ch[0], "section": ch[1], "modifier": ch[2] if len(ch) > 2 else None,
                          "offence_date": offence.isoformat()} for ch in charges],
             "hearings": []}
        for k, v in dates.items():
            c[k] = self.ago(v).isoformat() if v is not None else None
        p.cases.append(c)
        return c

    def custody(self, p: SynthPerson, type_: str, start_ago: int, end_ago: int | None = None, case: dict | None = None,
                **kw) -> None:
        p.custody_events.append({"type": type_, "start": self.ago(start_ago).isoformat(),
                                 "end": self.ago(end_ago).isoformat() if end_ago is not None else None,
                                 "case_ref": case["ref"] if case else None, "jail": kw.get("jail", p.jail),
                                 "confidence": kw.get("confidence", 0.95), "is_primary_source": kw.get("primary", True),
                                 "doc_type": kw.get("doc_type", "remand_order")})

    def hearings(self, case: dict, start_ago: int, n: int, reasons: list[tuple[str, str]] | None = None, gap: int = 30) -> None:
        d = start_ago
        for i in range(n):
            text, label = reasons[i] if reasons and i < len(reasons) else self.rng.choice(ADJOURNMENT_REASONS)
            nd = max(d - gap, 0)
            if nd == d:
                break
            case["hearings"].append({"date": self.ago(d).isoformat(), "next_date": self.ago(nd).isoformat() if nd > 0 else None,
                                     "reason_text": text, "true_attribution": label})
            d = nd


def age(p: SynthPerson, on: date) -> int:
    return int((on - date.fromisoformat(p.dob)).days / 365.25)


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm)


# ---------------------------------------------------------------------- demo scenarios

def build_demo(b: Builder) -> None:
    # 1. CRITICAL — detained beyond maximum (IPC 379, 3 years) — FIR + arrest memo + remand
    p = b.person("T-CRIT", "critical_beyond_max", "Manjunath S", age_years=34, expected="CRITICAL_MUST_RELEASE",
                 father="Siddappa")
    c = b.case(p, "c1", [("IPC", "379")], offence_ago=1175, fir_date=1174, first_remand_date=1170, charge_sheet_date=1100)
    c["facts"] = "Accused alleged to have stolen a two-wheeler parked near the bus stand."
    b.custody(p, "arrest", 1171, case=c, doc_type="arrest_memo")
    b.custody(p, "police_custody", 1171, 1170, case=c)
    b.custody(p, "judicial_custody", 1169, None, case=c)
    b.hearings(c, 1050, 20, [("PP sought time to secure witnesses.", "prosecution"), ("PO on leave. Adjourned.", "court"),
                             ("Prosecution witness absent. Summons to be re-issued.", "prosecution"),
                             ("Court busy with part-heard matter.", "court")] * 5, gap=50)
    p.documents += [
        b.fir_doc(p, c, offence_dt=at(b.ago(1175), 21), fir_dt=at(b.ago(1174), 10), delay_expl="",
                  witnesses="CW-1 complainant; CW-2 independent witness Ramesh"),
        b.arrest_memo(p, c, arrest_dt=at(b.ago(1171), 18), grounds="Yes", relative_informed="Yes (brother)",
                      attested="Yes", medical="Done at General Hospital"),
        b.remand_order(p, c, produced_dt=at(b.ago(1170), 11), remand_date=b.ago(1169), custody="judicial",
                       reasons="Investigation pending; accused may abscond."),
        b.jail_record(p, c, admitted=b.ago(1169), prisoner_no="UTP 4411"),
        b.order_sheet(c, c["hearings"]),
    ]

    # 2. ELIGIBLE first-time offender + Defense Insights showcase (IPC 380; arrested ~2y5m ago)
    p = b.person("T-ELIG", "eligible_first_time", "Ravi Kumar", age_years=24, expected="ELIGIBLE", father="Ramaiah")
    c = b.case(p, "c1", [("IPC", "380")], offence_ago=960, fir_date=953, first_remand_date=946, charge_sheet_date=880)
    c["facts"] = ("Theft of gold ornaments and cash from a dwelling house at night; recovery of a gold chain "
                  "allegedly at the instance of the accused.")
    b.custody(p, "arrest", 948, case=c, doc_type="arrest_memo")
    b.custody(p, "police_custody", 948, 947, case=c)
    b.custody(p, "judicial_custody", 946, None, case=c)
    reasons = [("PP sought time to secure witnesses.", "prosecution"), ("Presiding Officer on leave.", "court"),
               ("Prosecution witness absent. Summons to be re-issued.", "prosecution"),
               ("Adjourned at the request of the accused counsel.", "accused"),
               ("Accused not produced by jail authorities. Escort not available.", "prosecution"),
               ("Witness CW-2 absent despite service. Issue NBW.", "prosecution"),
               ("FSL report awaited by prosecution.", "prosecution"), ("Adjourned.", "unknown"),
               ("PW-3 turned hostile; permission to cross-examine granted.", "prosecution"),
               ("Prosecution witness absent. Summons to be re-issued.", "prosecution")]
    b.hearings(c, 860, 10, reasons, gap=60)
    p.documents += [
        b.fir_doc(p, c, offence_dt=at(b.ago(960), 23, 30), fir_dt=at(b.ago(953), 16), delay_expl="",
                  witnesses="CW-1 complainant; CW-2 HC 1123 (police); CW-3 PC 2231 (police)"),
        b.arrest_memo(p, c, arrest_dt=at(b.ago(948), 9, 15), grounds="Not recorded", relative_informed="No",
                      attested="No", medical="Not done"),
        b.remand_order(p, c, produced_dt=at(b.ago(946), 14), remand_date=b.ago(946), custody="judicial",
                       reasons="Remanded."),
        b.charge_sheet(p, c, filed=b.ago(880), offence_date=b.ago(957), witnesses="HC 1123, PC 2231, complainant",
                       fsl="Pending", recovery="Gold chain recovered at the instance of the accused; no independent panch witness",
                       confession="Accused confessed before the Investigating Officer", tip="Not held"),
        b.jail_record(p, c, admitted=b.ago(946), prisoner_no="UTP 5120", lang="kn"),
        b.order_sheet(c, c["hearings"]),
    ]

    # 3. REVIEW — multiple cases pending (379 + 411), alias "@"
    p = b.person("T-MULTI", "multiple_cases", "Syed Imran", age_years=29, expected="REVIEW_MULTIPLE_CASES",
                 father="Abdul Rahim")
    c1 = b.case(p, "c1", [("IPC", "379")], offence_ago=700, fir_date=699, first_remand_date=690, charge_sheet_date=640)
    c2 = b.case(p, "c2", [("IPC", "411")], offence_ago=720, fir_date=718, first_remand_date=680, charge_sheet_date=630)
    b.custody(p, "judicial_custody", 690, None, case=None)
    b.hearings(c1, 600, 8, gap=60)
    b.hearings(c2, 590, 8, gap=60)
    p.documents += [b.remand_order(p, c1, produced_dt=at(b.ago(690), 12), remand_date=b.ago(690), custody="judicial",
                                   reasons="Accused involved in another case of receiving stolen property."),
                    b.order_sheet(c1, c1["hearings"]), b.order_sheet(c2, c2["hearings"])]

    # 4. URGENT default bail — BNS 305 (7 years → 60 days), remand 75 days ago, no charge sheet
    p = b.person("T-DEFBAIL", "urgent_default_bail", "Basavaraj", age_years=41, district="Kalaburagi",
                 expected="URGENT_DEFAULT_BAIL", father="Channabasappa")
    c = b.case(p, "c1", [("BNS", "305")], status="investigation", offence_ago=80, fir_date=79, first_remand_date=75)
    c["facts"] = "Alleged theft from a temple hundi."
    b.custody(p, "arrest", 76, case=c, doc_type="arrest_memo")
    b.custody(p, "judicial_custody", 76, None, case=c)
    p.documents += [
        b.fir_doc(p, c, offence_dt=at(b.ago(80), 2), fir_dt=at(b.ago(79), 9), delay_expl="",
                  witnesses="CW-1 temple priest; CW-2 independent witness", lang="kn"),
        b.arrest_memo(p, c, arrest_dt=at(b.ago(76), 22), grounds="Yes", relative_informed="Yes", attested="Yes",
                      medical="Done"),
        b.remand_order(p, c, produced_dt=at(b.ago(74), 12), remand_date=b.ago(75), custody="judicial",
                       reasons="Investigation incomplete."),
    ]

    # 5. Acquitted but still detained
    p = b.person("T-ACQ", "acquitted_detained", "Anand Naik", age_years=45, district="Mysuru",
                 expected="CRITICAL_ACQUITTED_DETAINED", father="Govindappa")
    c = b.case(p, "c1", [("IPC", "324")], status="acquitted", offence_ago=500, fir_date=499, first_remand_date=495,
               charge_sheet_date=450, acquittal_date=12)
    b.custody(p, "judicial_custody", 495, None, case=c)

    # 6. Bail granted, surety not furnished (woman, BNS 318(4) — 7 years), not yet eligible
    p = b.person("T-SURETY", "bail_not_furnished", "Lakshmi Devi", gender="female", age_years=52, district="Mysuru",
                 expected="CRITICAL_BAIL_NOT_FURNISHED", vulnerability=["woman", "elderly"], father="Krishnappa")
    c = b.case(p, "c1", [("BNS", "318(4)")], offence_ago=300, fir_date=298, first_remand_date=290, charge_sheet_date=250,
               bail_granted_date=120)
    b.custody(p, "judicial_custody", 290, None, case=c)
    p.documents += [b.arrest_memo(p, c, arrest_dt=at(b.ago(291), 20, 30), grounds="Yes", relative_informed="Yes",
                                  attested="Yes", medical="Done", woman_officer="No", night_permission="Not obtained")]

    # 7. Excluded — IPC 302
    p = b.person("T-302", "excluded_life", "Suresh Gowda", age_years=38, expected="EXCLUDED_479", father="Nagaraj")
    c = b.case(p, "c1", [("IPC", "302")], offence_ago=1400, fir_date=1400, first_remand_date=1395, charge_sheet_date=1320)
    b.custody(p, "judicial_custody", 1396, None, case=c)
    b.hearings(c, 1300, 25, gap=50)

    # 8. Special law — NDPS small quantity
    p = b.person("T-NDPS", "special_law", "Mohammed Rafiq", age_years=22, expected="REVIEW", father="Yusuf Khan")
    c = b.case(p, "c1", [("NDPS", "20(b)(ii)(B)")], offence_ago=400, fir_date=400, first_remand_date=399,
               charge_sheet_date=300)
    b.custody(p, "judicial_custody", 399, None, case=c)

    # 9. Prior conviction (final) → 1/2 threshold; not yet
    p = b.person("T-PRIOR", "prior_conviction", "Venkatesh", age_years=33, expected="NOT_YET", father="Mallesh")
    c = b.case(p, "c1", [("IPC", "379")], offence_ago=450, fir_date=449, first_remand_date=445, charge_sheet_date=400)
    b.custody(p, "judicial_custody", 446, None, case=c)
    p.convictions.append({"case_ref": "old-1", "date": b.ago(2500).isoformat(), "status": "final", "offence": "IPC 379"})

    # 10. Conflicting arrest dates + accused-caused delay, first-time, eligible
    p = b.person("T-CONFLICT", "conflicting_arrest", "Harish Shetty", age_years=27, expected="ELIGIBLE", father="Shivalingaiah")
    c = b.case(p, "c1", [("IPC", "406")], offence_ago=900, fir_date=899, first_remand_date=505, charge_sheet_date=450)
    b.custody(p, "arrest", 510, case=c, primary=False, doc_type="jail_record")
    b.custody(p, "arrest", 506, case=c, doc_type="arrest_memo")
    b.custody(p, "judicial_custody", 505, None, case=c)
    b.hearings(c, 440, 6, [("Adjourned at the request of the accused counsel.", "accused")] * 2
               + [("PP sought time to secure witnesses.", "prosecution"), ("PO on leave. Adjourned.", "court")] * 2, gap=30)
    p.documents += [b.jail_record(p, c, admitted=b.ago(505), prisoner_no="UTP 6621", stated_arrest=b.ago(510))]


def build_population(b: Builder, n: int) -> None:
    rng = b.rng
    names = list(NAME_VARIANTS)
    for i in range(n):
        name = rng.choice(names)
        district = rng.choice(list(DISTRICTS))
        gender = "female" if name in ("Lakshmi Devi", "Kavya R") else "male"
        p = b.person(f"T-{i:03d}", "random", name, gender=gender, age_years=rng.randint(19, 62), district=district,
                     vulnerability=(["woman"] if gender == "female" else []) + (["serious_illness"] if rng.random() < 0.05 else []))
        n_cases = 1 if rng.random() < 0.8 else 2
        for k in range(n_cases):
            section = rng.choice([("IPC", "379"), ("IPC", "380"), ("IPC", "420"), ("IPC", "324"), ("IPC", "323"),
                                  ("IPC", "392"), ("IPC", "506"), ("BNS", "303(2)"), ("BNS", "318(4)"), ("IPC", "302"),
                                  ("IPC", "307"), ("IPC", "498A")])
            post_bns = section[0] == "BNS"
            off = rng.randint(40, 450) if post_bns else rng.randint(820, 1300)
            remand = off - rng.randint(1, 20)
            cs = remand - rng.randint(40, 120) if rng.random() < 0.8 else None
            c = b.case(p, f"c{k + 1}", [section], offence_ago=off, fir_date=off - rng.randint(0, 3), first_remand_date=remand,
                       charge_sheet_date=cs if cs and cs > 0 else None)
            if k == 0:
                if rng.random() < 0.15:
                    rel = rng.randint(30, max(31, remand - 10))
                    b.custody(p, "judicial_custody", remand, rel, case=c)
                    b.custody(p, "released", rel, case=c)
                    if rng.random() < 0.5:
                        b.custody(p, "re_arrest", rng.randint(5, rel - 1) if rel > 6 else 1, case=c)
                else:
                    split = rng.randint(1, remand - 1) if remand > 2 and rng.random() < 0.2 else None
                    if split:
                        b.custody(p, "judicial_custody", remand, split, case=c)
                        other_jail = rng.choice([j for d in DISTRICTS.values() for j in d["jails"]])
                        b.custody(p, "judicial_custody", split, None, case=c, jail=other_jail)
                    else:
                        b.custody(p, "judicial_custody", remand, None, case=c)
            b.hearings(c, max(remand - 60, 1), rng.randint(0, 12), gap=rng.choice([21, 30, 45, 60]))
        if rng.random() < 0.12:
            p.convictions.append({"case_ref": f"old-{i}", "date": b.ago(rng.randint(1500, 4000)).isoformat(),
                                  "status": rng.choice(["final", "final", "under_appeal", "set_aside", "juvenile"]),
                                  "offence": "IPC 379"})


# ---------------------------------------------------------------------- entity-resolution set

def build_er_records(b: Builder) -> list[dict]:
    """Records as different courts/jails would hold them. truth_id is the real person."""
    rng = b.rng
    recs: list[dict] = []
    k = 0

    def add(truth: str, name: str, father: str | None, age_: int | None, district: str, ps: str | None,
            address: str | None, co: list[str], cnr: str | None, source: str) -> None:
        nonlocal k
        k += 1
        recs.append({"record_id": f"R{k:04d}", "truth_id": truth, "name": name, "relative_name": father, "age": age_,
                     "district": district, "police_station": ps, "address": address, "co_accused": co, "cnr": cnr,
                     "source": source})

    villages = ["Hebbal", "Yelahanka", "Kengeri", "Hunsur", "Nanjangud", "Aland", "Sedam", "Chittapur", "Jevargi"]
    for t, (name, variants) in enumerate(NAME_VARIANTS.items()):
        for copy in range(2 if name in ("Ravi Kumar", "Basavaraj", "Venkatesh") else 1):
            truth = f"ER-{t:02d}-{copy}"
            father = rng.choice(FATHERS)
            district = rng.choice(list(DISTRICTS))
            base_age = rng.randint(20, 55)
            village = rng.choice(villages)
            co = [rng.choice(list(NAME_VARIANTS))] if rng.random() < 0.4 else []
            cnr = f"KA0{rng.randint(1, 3)}0{rng.randint(1, 9)}{rng.randint(1, 999999):06d}2023"
            for j in range(rng.randint(2, 4)):
                nm = name if j == 0 else rng.choice(variants)
                fv = rng.choice(FATHER_VARIANTS.get(father, [father]))
                if rng.random() < 0.1:
                    fv = None  # missing father's name
                ag = base_age + rng.randint(-2, 2) if rng.random() < 0.9 else None
                addr = f"{rng.randint(1, 300)}, {village if rng.random() < 0.75 else rng.choice(villages)}"
                if rng.random() < 0.25:
                    addr = None  # many records carry no address
                add(truth, nm, fv, ag, district, rng.choice(DISTRICTS[district]["stations"]),
                    addr, co, cnr if j < 2 and rng.random() < 0.5 else None,
                    rng.choice(["court", "jail", "police"]))
    # look-alikes: different people with the same common name in the same district (single records)
    for name in ("Ravi Kumar", "Manjunath S", "Basavaraj", "Venkatesh", "Shivanna", "Nagesh"):
        for j in range(3):
            district = rng.choice(list(DISTRICTS))
            add(f"ER-LA-{name}-{j}", rng.choice([name] + NAME_VARIANTS[name][:2]), rng.choice(FATHERS),
                rng.randint(19, 60), district, rng.choice(DISTRICTS[district]["stations"]),
                f"{rng.randint(1, 300)}, {rng.choice(villages)}" if rng.random() < 0.7 else None, [], None, "court")
    # hard negatives: same name + same father, age differs by 20 years, same village (spec test 40)
    add("ER-LOOK-A", "Ravi Kumar", "Ramaiah", 24, "Bengaluru Urban", "Jayanagar PS", "12, Hebbal", [], None, "court")
    add("ER-LOOK-B", "Ravi Kumar", "Ramaiah", 44, "Bengaluru Urban", "Jayanagar PS", "14, Hebbal", [], None, "jail")
    # same name, different fathers, same district (spec test 39)
    add("ER-LOOK-C", "Ravi Kumar", "Krishnappa", 30, "Bengaluru Urban", "Shivajinagar PS", "3, Yelahanka", [], None, "court")
    add("ER-LOOK-D", "Ravi Kumar", "Hanumanthappa", 31, "Bengaluru Urban", "Shivajinagar PS", "9, Yelahanka", [], None, "jail")
    return recs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--population", type=int, default=60)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "out")
    args = ap.parse_args()
    data = generate(args.today, args.seed, args.population)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "dataset.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(data['persons'])} persons, {len(data['er_records'])} ER records, "
          f"{len(data['delay_reasons'])} delay reasons → {args.out / 'dataset.json'}")


def generate(today: date, seed: int = 7, population: int = 60) -> dict:
    rng = random.Random(seed)
    b = Builder(today, rng)
    build_demo(b)
    build_population(b, population)
    er = build_er_records(b)
    return {"generated_for_today": today.isoformat(), "seed": seed,
            "persons": [asdict(p) for p in b.people], "er_records": er,
            "delay_reasons": [{"text": t, "label": lab} for t, lab in ADJOURNMENT_REASONS]}


if __name__ == "__main__":
    main()
