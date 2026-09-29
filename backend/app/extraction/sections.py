"""Section-string parser: "379 IPC", "u/s 379", "S.379", "379/34", "379 r/w 34",
"323, 324, 504 & 506", "303(2) BNS", "Sec. 20(b)(ii)(A) NDPS Act", OCR slips (l→1, O→0).

Output: charges with act, section and modifier (attempt / abetment / conspiracy /
common intention) derived from the companion liability sections."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ACT_ALIASES = {
    "ipc": "IPC", "i.p.c": "IPC", "i.p.c.": "IPC", "indian penal code": "IPC",
    "bns": "BNS", "b.n.s": "BNS", "bharatiya nyaya sanhita": "BNS",
    "bnss": "BNSS", "b.n.s.s": "BNSS", "bharatiya nagarik suraksha sanhita": "BNSS", "crpc": "CRPC", "cr.p.c": "CRPC",
    "cr.p.c.": "CRPC", "of the bnss": "BNSS",
    "ndps": "NDPS", "ndps act": "NDPS", "pocso": "POCSO", "pocso act": "POCSO",
    "arms act": "ARMS", "uapa": "UAPA", "pmla": "PMLA", "sc/st act": "SCST", "sc st act": "SCST", "scst": "SCST",
}
LIABILITY = {
    "IPC": {"34": "common_intention", "109": "abetment", "120B": "conspiracy", "511": "attempt", "149": "common_object"},
    "BNS": {"3(5)": "common_intention", "49": "abetment", "61(2)": "conspiracy", "62": "attempt"},
}
_ACT_RE = "|".join(sorted((re.escape(a) for a in ACT_ALIASES), key=len, reverse=True))
SEC_TOKEN = r"\d{1,3}[A-Z]?(?:\s*\(\s*[0-9a-z]{1,4}\s*\))*(?:-II)?"
SECTION_LIST_RE = re.compile(
    rf"(?:(?:u/s|u/ss|u\.s\.|under\s+sections?|sections?|secs?\.?|s\.|ss\.|ಕಲಂ(?:ಗಳು)?|धारा)\s*:?\s*)?"
    rf"(?P<list>{SEC_TOKEN}(?:\s*(?:,|/|&|and|r/w|read\s+with|ಮತ್ತು|व|और)\s*{SEC_TOKEN})*)"
    rf"\s*(?:of\s+(?:the\s+)?)?(?P<act>{_ACT_RE})?\.?",
    re.IGNORECASE)
_OCR_FIX = str.maketrans({"l": "1", "O": "0", "o": "0", "I": "1"})


@dataclass
class ParsedCharge:
    act: str
    section: str
    modifier: str | None = None
    text: str = ""
    start: int = 0
    end: int = 0
    confidence: float = 0.9
    flags: list[str] = field(default_factory=list)


def _clean_section(s: str) -> str:
    return re.sub(r"\s+", "", s).upper().replace("(", "(").replace(")", ")").replace("(II)", "(ii)").replace("-II", "-II")


def _fix_ocr(text: str) -> tuple[str, bool]:
    # only fix inside digit-ish tokens: "3l9" → "319", "5O6" → "506"
    fixed = re.sub(r"(?<=\d)[lOoI]|[lOoI](?=\d)", lambda m: m.group(0).translate(_OCR_FIX), text)
    return fixed, fixed != text


def parse_sections(text: str, default_act: str | None = None) -> list[ParsedCharge]:
    fixed, ocr = _fix_ocr(text)
    out: list[ParsedCharge] = []
    for m in SECTION_LIST_RE.finditer(fixed):
        prefix = m.group(0)[: m.start("list") - m.start()]
        act_raw = m.group("act")
        if not prefix.strip() and not act_raw:
            continue  # bare numbers are not sections
        act = ACT_ALIASES.get(act_raw.lower().rstrip(".")) if act_raw else default_act
        flags = ["OCR_CORRECTED"] if ocr else []
        if act is None:
            flags.append("ACT_NOT_STATED")
        tokens = re.split(r"\s*(?:,|/|&|\band\b|r/w|read\s+with|ಮತ್ತು|व|और)\s*", m.group("list"), flags=re.IGNORECASE)
        secs = [_clean_section(t) for t in tokens if t.strip()]
        # restore lowercase clause letters, e.g. 20(B)(II)(A) → 20(b)(ii)(A) as written in the Acts
        secs = [re.sub(r"\(([A-Z]{1,4})\)", lambda x: f"({x.group(1).lower()})" if len(x.group(1)) > 1 or x.group(1) in "BCDEFGH" else x.group(0), s)
                for s in secs]
        liab = LIABILITY.get(act or "", {})
        modifiers = [liab[s] for s in secs if s in liab]
        offences = [s for s in secs if s not in liab]
        mod = modifiers[0] if modifiers else None
        if len(set(modifiers)) > 1:
            flags.append("MULTIPLE_LIABILITY_PROVISIONS")
        if not offences:
            offences, mod = secs, None  # e.g. "u/s 34" alone
            flags.append("LIABILITY_PROVISION_ONLY")
        conf = 0.9 - (0.2 if "ACT_NOT_STATED" in flags else 0) - (0.15 if ocr else 0)
        for s in offences:
            out.append(ParsedCharge(act or "UNKNOWN", s, mod if mod != "common_object" else None,
                                    text[m.start():m.end()], m.start(), m.end(), round(conf, 2), list(flags)))
    return out
