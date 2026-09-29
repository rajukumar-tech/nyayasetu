"""Date extraction for messy multilingual legal records.

Handles dd/mm/yyyy (Indian default) vs mm/dd/yyyy, "12th March 2025", Kannada and
Devanagari digits and month names, two-digit years, partial dates ("March 2023"),
impossible dates (31/02) and future dates. Every result carries flags and a confidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

DIGIT_MAP = str.maketrans("೦೧೨೩೪೫೬೭೮೯०१२३४५६७८९", "01234567890123456789")

MONTHS: dict[str, int] = {}
for i, names in enumerate([
    ["january", "jan", "ಜನವರಿ", "जनवरी"],
    ["february", "feb", "ಫೆಬ್ರವರಿ", "ಫೆಬ್ರುವರಿ", "फ़रवरी", "फरवरी"],
    ["march", "mar", "ಮಾರ್ಚ್", "ಮಾರ್ಚಿ", "मार्च"],
    ["april", "apr", "ಏಪ್ರಿಲ್", "अप्रैल"],
    ["may", "ಮೇ", "मई"],
    ["june", "jun", "ಜೂನ್", "जून"],
    ["july", "jul", "ಜುಲೈ", "जुलाई"],
    ["august", "aug", "ಆಗಸ್ಟ್", "ಆಗಸ್ಟ", "अगस्त"],
    ["september", "sep", "sept", "ಸೆಪ್ಟೆಂಬರ್", "सितंबर", "सितम्बर"],
    ["october", "oct", "ಅಕ್ಟೋಬರ್", "अक्टूबर"],
    ["november", "nov", "ನವೆಂಬರ್", "नवंबर", "नवम्बर"],
    ["december", "dec", "ಡಿಸೆಂಬರ್", "दिसंबर", "दिसम्बर"],
], start=1):
    for n in names:
        MONTHS[n] = i

_MONTH_ALT = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))
# OCR confusions inside digit runs
_OCR_DIGIT = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1", "S": "5"})

NUMERIC_RE = re.compile(r"(?<![\d\w])([0-9OolIS|]{1,2})\s*[/\-.]\s*([0-9OolIS|]{1,2})\s*[/\-.]\s*([0-9OolIS|]{2,4})(?![\d])")
TEXTUAL_RE = re.compile(
    rf"(?<![\w])(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:day\s+of\s+)?[\s,.-]*({_MONTH_ALT})[\s,.-]*(\d{{2,4}})(?![\d])", re.IGNORECASE)
TEXTUAL_MDY_RE = re.compile(rf"(?<![\w])({_MONTH_ALT})\s+(\d{{1,2}})(?:st|nd|rd|th)?,\s*(\d{{4}})", re.IGNORECASE)
PARTIAL_RE = re.compile(rf"(?<![\w\d])({_MONTH_ALT})[\s,.-]+(\d{{4}})(?![\d])", re.IGNORECASE)


@dataclass
class ParsedDate:
    value: date | None
    text: str
    start: int
    end: int
    confidence: float
    flags: list[str] = field(default_factory=list)
    alternatives: list[date] = field(default_factory=list)
    precision: str = "day"  # day | month

    @property
    def iso(self) -> str | None:
        return self.value.isoformat() if self.value else None


def normalise_digits(s: str) -> str:
    return s.translate(DIGIT_MAP)


def _year(y: str, flags: list[str], today: date) -> int:
    n = int(y)
    if len(y) == 2:
        flags.append("TWO_DIGIT_YEAR")
        # pivot: choose the century that does not put the date in the future
        n = 2000 + n if 2000 + n <= today.year else 1900 + n
    return n


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_numeric(a: str, b: str, y: str, today: date, prefer: str = "dmy") -> tuple[date | None, list[str], float, list[date]]:
    flags: list[str] = []
    raw = f"{a}{b}{y}"
    a, b, y = (s.translate(_OCR_DIGIT) for s in (a, b, y))
    if raw != f"{a}{b}{y}":
        flags.append("OCR_DIGIT_CORRECTED")
    if not (a.isdigit() and b.isdigit() and y.isdigit()):
        return None, flags + ["UNPARSEABLE"], 0.0, []
    yr = _year(y, flags, today)
    x, z = int(a), int(b)
    dmy = _mk(yr, z, x)
    mdy = _mk(yr, x, z)
    conf = 0.95
    alts: list[date] = []
    if dmy and mdy and dmy != mdy:
        flags.append("AMBIGUOUS_DMY_MDY")
        alts = [mdy] if prefer == "dmy" else [dmy]
        chosen = dmy if prefer == "dmy" else mdy
        conf = 0.75
    elif dmy:
        chosen = dmy
    elif mdy:
        chosen = mdy
        flags.append("PARSED_AS_MDY")  # only valid reading is month-first
        conf = 0.7
    else:
        return None, flags + ["IMPOSSIBLE_DATE"], 0.0, []
    if "TWO_DIGIT_YEAR" in flags:
        conf -= 0.1
    if "OCR_DIGIT_CORRECTED" in flags:
        conf -= 0.15
    return chosen, flags, conf, alts


def extract_dates(text: str, today: date | None = None, prefer: str = "dmy") -> list[ParsedDate]:
    today = today or date.today()
    norm = normalise_digits(text)  # same length as text: all digit maps are 1:1 characters
    found: list[ParsedDate] = []
    taken: list[tuple[int, int]] = []

    def free(s: int, e: int) -> bool:
        return all(e <= a or s >= b for a, b in taken)

    for m in TEXTUAL_RE.finditer(norm):
        flags: list[str] = []
        yr = _year(m.group(3), flags, today)
        d = _mk(yr, MONTHS[m.group(2).lower()], int(m.group(1)))
        pd = ParsedDate(d, text[m.start():m.end()], m.start(), m.end(), 0.97 if d else 0.0,
                        flags + ([] if d else ["IMPOSSIBLE_DATE"]))
        found.append(pd)
        taken.append((m.start(), m.end()))
    for m in TEXTUAL_MDY_RE.finditer(norm):
        if not free(m.start(), m.end()):
            continue
        d = _mk(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        found.append(ParsedDate(d, text[m.start():m.end()], m.start(), m.end(), 0.95 if d else 0.0, [] if d else ["IMPOSSIBLE_DATE"]))
        taken.append((m.start(), m.end()))
    for m in NUMERIC_RE.finditer(norm):
        if not free(m.start(), m.end()):
            continue
        d, flags, conf, alts = parse_numeric(m.group(1), m.group(2), m.group(3), today, prefer)
        found.append(ParsedDate(d, text[m.start():m.end()], m.start(), m.end(), conf, flags, alts))
        taken.append((m.start(), m.end()))
    for m in PARTIAL_RE.finditer(norm):
        if not free(m.start(), m.end()):
            continue
        d = date(int(m.group(2)), MONTHS[m.group(1).lower()], 1)
        found.append(ParsedDate(d, text[m.start():m.end()], m.start(), m.end(), 0.5, ["PARTIAL_DATE"], precision="month"))
        taken.append((m.start(), m.end()))
    for pd in found:
        if pd.value and pd.value > today:
            pd.flags.append("FUTURE_DATE")
            pd.confidence = min(pd.confidence, 0.3)
    return sorted(found, key=lambda p: p.start)


def resolve_ambiguity(candidates: list[ParsedDate], anchors: list[date]) -> list[ParsedDate]:
    """Use other unambiguous dates in the same record (e.g. FIR < arrest < remand) to pick
    between dd/mm and mm/dd: prefer the reading closest to the anchors."""
    if not anchors:
        return candidates
    for pd in candidates:
        if "AMBIGUOUS_DMY_MDY" in pd.flags and pd.value and pd.alternatives:
            options = [pd.value] + pd.alternatives
            best = min(options, key=lambda d: min(abs((d - a).days) for a in anchors))
            if best != pd.value:
                pd.alternatives = [pd.value]
                pd.value = best
            pd.flags.append("AMBIGUITY_RESOLVED_BY_CONTEXT")
            pd.confidence = 0.85
    return candidates
