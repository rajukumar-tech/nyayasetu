"""Rule-based extraction of labelled fields ("Label: value") from legal forms in
English and Kannada, plus names with relations (s/o, d/o, w/o) and hearing lines.
Every value keeps its character span for source highlighting."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.extraction.dates import extract_dates
from app.extraction.sections import parse_sections


@dataclass
class Field:
    name: str
    value: object
    start: int
    end: int
    text: str
    confidence: float
    method: str = "regex"
    flags: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)  # other readings of an ambiguous date


# label pattern → (field name, kind). kind: date | datetime | yesno | text | sections | person | int
LABELS: list[tuple[str, str, str]] = [
    (r"police station|ಪೊಲೀಸ್ ಠಾಣೆ", "police_station", "text"),
    (r"fir no\.?|fir ಸಂಖ್ಯೆ|crime no\.?", "fir_number", "text"),
    (r"accused|ಆರೋಪಿ|name of arrested person|name|ಹೆಸರು", "accused", "person"),
    (r"date and time of occurrence|ಅಪರಾಧದ ದಿನಾಂಕ", "offence_datetime", "datetime"),
    (r"date and time of fir|fir ದಿನಾಂಕ", "fir_datetime", "datetime"),
    (r"sections?|ಕಲಂಗಳು", "sections", "sections"),
    (r"reason for delay in reporting", "fir_delay_reason", "text"),
    (r"witnesses(?: cited)?", "witnesses", "text"),
    (r"brief facts", "brief_facts", "text"),
    (r"gender", "gender", "text"),
    (r"date and time of arrest|ಬಂಧನದ ದಿನಾಂಕ", "arrest_datetime", "datetime"),
    (r"grounds of arrest communicated", "grounds_of_arrest", "yesno"),
    (r"relative/friend informed", "relative_informed", "yesno"),
    (r"memo attested by witness", "arrest_memo_attested", "yesno"),
    (r"medical examination", "medical_examination", "yesno"),
    (r"woman police officer present", "woman_officer_present", "yesno"),
    (r"prior permission of magistrate.*?", "night_arrest_permission", "yesno"),
    (r"accused produced before magistrate on|ಹಾಜರುಪಡಿಸಿದ ದಿನಾಂಕ", "production_datetime", "datetime"),
    (r"remanded to (?:\w+ )?custody from|ನ್ಯಾಯಾಂಗ ಬಂಧನಕ್ಕೆ ರಿಮಾಂಡ್ ದಿನಾಂಕ", "remand_date", "date"),
    (r"reasons", "remand_reasons", "text"),
    (r"date of filing", "charge_sheet_date", "date"),
    (r"date of offence", "charge_sheet_offence_date", "date"),
    (r"fsl report", "fsl_status", "text"),
    (r"recovery", "recovery", "text"),
    (r"confession", "confession", "text"),
    (r"test identification parade", "tip_status", "text"),
    (r"weapon", "weapon", "text"),
    (r"utp no\.?|ಕೈದಿ ಸಂಖ್ಯೆ", "prisoner_number", "text"),
    (r"date of admission|ದಾಖಲಾದ ದಿನಾಂಕ", "admission_date", "date"),
    (r"date of arrest \(as stated\)", "stated_arrest_date", "date"),
]
_SEG_SPLIT = re.compile(r"[ \t]{2,}(?=[^\s:][^:\n]{0,40}:)")
_SEG_RE = re.compile(r"^(?P<label>[^:\n]{2,80}?)[ \t]*:[ \t]*(?P<value>.*?)[ \t]*$")


class _Seg:
    def __init__(self, label: str, value: str, vstart: int):
        self._g = {"label": label, "value": value}
        self._vstart = vstart

    def group(self, k: str) -> str:
        return self._g[k]

    def start(self, k: str) -> int:
        return self._vstart


class _LineRE:
    """Finds "Label: value" segments; several may share one line ("Police Station: X   FIR No.: Y")."""
    def finditer(self, text: str):
        pos = 0
        for line in text.split("\n"):
            seg_starts = [0] + [m.end() for m in _SEG_SPLIT.finditer(line)]
            bounds = list(zip(seg_starts, seg_starts[1:] + [len(line)]))
            for a, b in bounds:
                seg = line[a:b]
                m = _SEG_RE.match(seg)
                if m:
                    yield _Seg(m.group("label"), m.group("value"), pos + a + m.start("value"))
            pos += len(line) + 1


_LINE_RE = _LineRE()
_TIME_RE = re.compile(r"(?:at\s*|ಸಮಯ\s*)?(\d{1,2})[:.](\d{2})\s*(?:hrs|hours)?", re.I)
_PERSON_RE = re.compile(
    r"^(?P<name>.+?)(?:\s+(?P<rel>s/o|d/o|w/o|ತಂದೆ|ಪತಿ|son of|daughter of|wife of)\s+(?P<relname>[^,\n]+?))?"
    r"(?:,\s*aged\s+about\s+(?P<age>\d{1,3})\s+years)?\s*$", re.I)
_REL = {"ತಂದೆ": "s/o", "ಪತಿ": "w/o", "son of": "s/o", "daughter of": "d/o", "wife of": "w/o"}
_HEARING_RE = re.compile(r"^(?P<date>[0-9೦-೯]{1,2}/[0-9೦-೯]{1,2}/[0-9೦-೯]{2,4}):\s*(?P<text>[^\n]*?)(?:\s*Call on (?P<next>[0-9/]+)\.)?\s*$", re.M)

YES = {"yes", "y", "done", "ಹೌದು", "हाँ", "obtained", "present"}
NO = {"no", "n", "not done", "ಇಲ್ಲ", "नहीं", "not obtained", "absent", "nil"}
NOT_RECORDED = {"not recorded", "", "-", "blank", "not mentioned", "n/a"}


def _yesno(v: str) -> tuple[str, float]:
    s = v.strip().lower().rstrip(".")
    head = re.split(r"[\s(,]", s, maxsplit=1)[0] if s else ""
    if s in NOT_RECORDED:
        return "not_recorded", 0.9
    if s in NO or s.startswith("not ") or head in NO:
        return "no", 0.9
    if s in YES or head in YES:
        return "yes", 0.9
    return "unclear", 0.4


def extract_fields(text: str, today: date) -> list[Field]:
    out: list[Field] = []
    for m in _LINE_RE.finditer(text):
        label = m.group("label").strip().lower()
        if re.fullmatch(r"[0-9೦-೯/]+", label):
            continue  # order-sheet date lines are handled below
        value = m.group("value")
        vstart = m.start("value")
        for pat, name, kind in LABELS:
            if not re.fullmatch(pat, label, re.I):
                continue
            out.extend(_convert(name, kind, value, vstart, today))
            break
    for m in _HEARING_RE.finditer(text):
        ds = extract_dates(m.group("date"), today)
        nxt = extract_dates(m.group("next"), today) if m.group("next") else []
        if ds and ds[0].value:
            out.append(Field("hearing", {"date": ds[0].iso, "next_date": nxt[0].iso if nxt and nxt[0].value else None,
                                         "reason_text": m.group("text").strip()},
                             m.start(), m.end(), m.group(0), min(ds[0].confidence, 0.95), flags=list(ds[0].flags),
                             alternatives=[a.isoformat() for a in ds[0].alternatives]))
    _resolve_by_context(out)
    return out


def _resolve_by_context(fields: list[Field]) -> None:
    """Pick dd/mm vs mm/dd for ambiguous dates using the document's unambiguous dates as anchors."""
    def d_of(f: Field) -> date | None:
        v = f.value.get("date") if isinstance(f.value, dict) else f.value
        try:
            return date.fromisoformat(str(v)[:10]) if v else None
        except ValueError:
            return None
    anchors = [d for f in fields if "AMBIGUOUS_DMY_MDY" not in f.flags and (d := d_of(f))]
    if not anchors:
        return
    for f in fields:
        if "AMBIGUOUS_DMY_MDY" not in f.flags or not f.alternatives:
            continue
        cur = d_of(f)
        alt = date.fromisoformat(f.alternatives[0])
        dist = lambda d: min(abs((d - a).days) for a in anchors)  # noqa: E731
        if cur and dist(alt) < dist(cur):
            new = alt.isoformat()
            if isinstance(f.value, dict):
                f.value = {**f.value, "date": new}
            else:
                f.value = new + str(f.value)[10:]
            f.alternatives = [cur.isoformat()]
        f.flags.append("AMBIGUITY_RESOLVED_BY_CONTEXT")
        f.confidence = max(f.confidence, 0.85)


def _convert(name: str, kind: str, value: str, start: int, today: date) -> list[Field]:
    v = value.strip()
    lead = len(value) - len(value.lstrip())
    s0, e0 = start + lead, start + lead + len(v)
    if kind == "text":
        return [Field(name, v, s0, e0, v, 0.9 if v else 0.5, flags=[] if v else ["EMPTY"])]
    if kind == "yesno":
        val, conf = _yesno(v)
        return [Field(name, val, s0, e0, v, conf, flags=["UNCLEAR"] if val == "unclear" else [])]
    if kind in ("date", "datetime"):
        ds = [d for d in extract_dates(v, today) if d.value]
        if not ds:
            return [Field(name, None, s0, e0, v, 0.2, flags=["NO_DATE_FOUND"])]
        d = ds[0]
        val: str = d.iso or ""
        if kind == "datetime":
            tm = _TIME_RE.search(v[d.end:])
            if tm and int(tm.group(1)) < 24:
                val = f"{val}T{int(tm.group(1)):02d}:{tm.group(2)}"
            else:
                d.flags.append("TIME_MISSING")
        return [Field(name, val, s0 + d.start, s0 + d.end, d.text, d.confidence, flags=list(d.flags),
                      alternatives=[a.isoformat() for a in d.alternatives])]
    if kind == "sections":
        return [Field("charge", {"act": c.act, "section": c.section, "modifier": c.modifier}, s0 + c.start, s0 + c.end,
                      c.text, c.confidence, flags=c.flags) for c in parse_sections(v)]
    if kind == "person":
        m = _PERSON_RE.match(v)
        if not m or not m.group("name").strip():
            return []
        rel = m.group("rel")
        rel = _REL.get(rel.lower(), rel.lower()) if rel else None
        val = {"name": m.group("name").strip(), "relation": rel,
               "relative_name": (m.group("relname") or "").strip() or None,
               "age": int(m.group("age")) if m.group("age") else None}
        return [Field("person", val, s0, e0, v, 0.85)]
    return []
