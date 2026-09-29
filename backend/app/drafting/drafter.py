"""Grounded drafting: every sentence is built from (and mapped to) a source — a verified
fact, the eligibility trace, a legal-KB record, an accepted Defense Insight, or a retrieved
judgment passage. The verifier then re-checks every name, date, section, number and
citation in every sentence against that sentence's own sources; anything unsupported is
rejected (and the draft is flagged) before a lawyer ever sees it as "ready".
An LLM may only polish wording (prompts/draft_application.md); its output is re-verified
and discarded sentence-by-sentence if it changes any checked token."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date

from app.core.llm import get_llm
from app.defense.retrieval import CITATION_RE
from app.extraction.dates import extract_dates
from app.extraction.sections import parse_sections

DRAFT_TYPES = {
    "section_479": "Application under Section 479 BNSS for release of undertrial prisoner",
    "default_bail": "Application for default (statutory) bail under Section 187(3) BNSS",
    "regular_bail": "Application for regular bail",
    "plea_bargaining": "Application for plea bargaining",
    "discharge": "Application for discharge",
    "speedy_trial": "Petition for speedy trial / bail on the ground of delay (Article 21)",
    "surety_modification": "Application for modification of bail conditions (surety relief)",
}


@dataclass
class Source:
    type: str  # fact | eligibility | kb | insight | judgment | case | person | template
    ref: str
    values: list[str]  # the checkable values this source supports


@dataclass
class Sentence:
    id: str
    text: str
    sources: list[Source]
    status: str = "ok"  # ok | rejected
    problems: list[str] = field(default_factory=list)


@dataclass
class DraftDoc:
    type: str
    language: str
    title: str
    sentences: list[Sentence]
    disclaimer: str
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(s.text for s in self.sentences)


# ------------------------------------------------------------------ verifier

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def checkable_tokens(text: str, today: date) -> dict[str, list[str]]:
    toks: dict[str, list[str]] = {"dates": [], "sections": [], "citations": [], "numbers": [], "names": []}
    for d in extract_dates(text, today):
        if d.value:
            toks["dates"].append(d.value.isoformat())
    for c in parse_sections(text):
        toks["sections"].append(f"{c.act} {c.section}")
    toks["citations"] = CITATION_RE.findall(text)
    stripped = CITATION_RE.sub(" ", text)
    for d in extract_dates(stripped, today):
        stripped = stripped.replace(d.text, " ")
    for c in parse_sections(stripped):
        stripped = stripped.replace(c.text, " ")
    toks["numbers"] = [n for n in re.findall(r"(?<![\w/])\d{1,6}(?![\w/])", stripped)]
    toks["names"] = re.findall(r"«([^»]+)»", text)  # names are always wrapped «…» by the templates
    return toks


def verify(doc: DraftDoc, today: date) -> dict:
    report = {"sentences": len(doc.sentences), "rejected": 0, "grounded": 0, "problems": []}
    for s in doc.sentences:
        s.problems = []
        support = " | ".join(_norm(v) for src in s.sources for v in src.values)
        support_dates = {d.value.isoformat() for src in s.sources for v in src.values
                         for d in extract_dates(str(v), today) if d.value} | \
                        {str(v)[:10] for src in s.sources for v in src.values if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", str(v))}
        t = checkable_tokens(s.text, today)
        for d in t["dates"]:
            if d not in support_dates:
                s.problems.append(f"date {d} not in sources")
        for sec in t["sections"]:
            act, num = sec.split(" ", 1)
            if _norm(num) not in support:
                s.problems.append(f"section {sec} not in sources")
        for c in t["citations"]:
            if _norm(c) not in support:
                s.problems.append(f"citation {c} not in sources")
        for n in t["numbers"]:
            if not re.search(rf"(?<!\d){re.escape(n)}(?!\d)", support):
                s.problems.append(f"number {n} not in sources")
        for nm in t["names"]:
            if _norm(nm) not in support:
                s.problems.append(f"name {nm} not in sources")
        if not s.sources:
            s.problems.append("sentence has no source")
        s.status = "rejected" if s.problems else "ok"
        report["rejected" if s.problems else "grounded"] += 1
        report["problems"] += [f"[{s.id}] {p}" for p in s.problems]
    report["fully_grounded_pct"] = round(100 * report["grounded"] / max(1, report["sentences"]), 1)
    return report


# ------------------------------------------------------------------ templates

def _d(v: date | str | None) -> str:
    if v is None:
        return ""
    d = v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
    return d.strftime("%d/%m/%Y")


T = {
    "en": {
        "court": "IN THE COURT OF THE {court}",
        "cause": "{title}",
        "parties": "«{name}», {relation} «{relative}», presently lodged in {jail} as an undertrial prisoner … Applicant/Accused.",
        "case": "In {case_number} (CNR {cnr}), arising out of FIR No. {fir} of {ps}.",
        "charges": "The applicant is accused of offences under {sections}.",
        "arrest": "The applicant was arrested on {arrest_date} and has remained in custody since then.",
        "custody": "As on {today}, the applicant has undergone {counted} days of detention counted for this purpose "
                   "({custody} days in custody, less {accused} days of delay attributable to the applicant).",
        "max": "The maximum punishment prescribed for the offence is {max_term}.",
        "fraction_first": "The applicant has never been convicted of any offence and is therefore entitled to release on "
                          "bond after one-third of the maximum period, namely {threshold} days.",
        "fraction_general": "One-half of the maximum period is {threshold} days.",
        "eligible": "The applicant crossed this threshold on {eligible_from} and has been detained {overdue} days beyond it.",
        "ceiling": "The applicant has been detained beyond the maximum period of imprisonment for the offence, which "
                   "no undertrial may be.",
        "remand": "The applicant was first remanded to custody on {remand}.",
        "no_cs": "No charge sheet has been filed as on {today}, although the statutory period of {period} days expired on {accrual}.",
        "db_right": "The applicant therefore has an indefeasible right to be released on default bail and "
                    "exercises that right by this application.",
        "bail_granted": "Bail was granted to the applicant on {bail_date}, but the applicant has been unable to furnish surety.",
        "insight": "{title}: {explanation}",
        "judgment": "The applicant relies on {citation} ({court}), where it was observed: \"{passage}\"",
        "prayer_479": "It is therefore prayed that this Hon'ble Court may be pleased to release the applicant on bail/bond "
                      "under Section 479 of the BNSS.",
        "prayer_db": "It is therefore prayed that the applicant be released on default bail.",
        "prayer_surety": "It is therefore prayed that the bail conditions be modified and the applicant released on personal bond.",
        "prayer_generic": "It is therefore prayed that this Hon'ble Court may grant such relief as it deems fit.",
        "note": "Note: the Hon'ble Court may, after hearing the Public Prosecutor and recording reasons, order continued detention.",
        "sign": "Counsel for the Applicant (Legal Aid)",
    },
    "kn": {
        "court": "ಮಾನ್ಯ {court} ರವರ ನ್ಯಾಯಾಲಯದಲ್ಲಿ",
        "cause": "{title}",
        "parties": "«{name}», {relation} «{relative}», ಪ್ರಸ್ತುತ {jail} ನಲ್ಲಿ ವಿಚಾರಣಾಧೀನ ಕೈದಿಯಾಗಿರುವ … ಅರ್ಜಿದಾರರು/ಆರೋಪಿ.",
        "case": "{case_number} (CNR {cnr}), FIR ಸಂಖ್ಯೆ {fir}, {ps} ಪ್ರಕರಣದಲ್ಲಿ.",
        "charges": "ಅರ್ಜಿದಾರರ ಮೇಲೆ {sections} ಅಡಿಯಲ್ಲಿ ಆರೋಪಗಳಿವೆ.",
        "arrest": "ಅರ್ಜಿದಾರರನ್ನು {arrest_date} ರಂದು ಬಂಧಿಸಲಾಗಿದ್ದು, ಅಂದಿನಿಂದ ಬಂಧನದಲ್ಲಿದ್ದಾರೆ.",
        "custody": "{today} ರಂತೆ ಅರ್ಜಿದಾರರು ಈ ಉದ್ದೇಶಕ್ಕಾಗಿ ಎಣಿಸಲಾದ {counted} ದಿನಗಳ ಬಂಧನ ಅನುಭವಿಸಿದ್ದಾರೆ "
                   "(ಬಂಧನದಲ್ಲಿ {custody} ದಿನಗಳು, ಅರ್ಜಿದಾರರಿಂದಾದ ವಿಳಂಬ {accused} ದಿನಗಳನ್ನು ಕಳೆದು).",
        "max": "ಈ ಅಪರಾಧಕ್ಕೆ ನಿಗದಿಪಡಿಸಿದ ಗರಿಷ್ಠ ಶಿಕ್ಷೆ {max_term}.",
        "fraction_first": "ಅರ್ಜಿದಾರರು ಹಿಂದೆ ಯಾವುದೇ ಅಪರಾಧಕ್ಕೆ ಶಿಕ್ಷೆಗೊಳಗಾಗಿಲ್ಲವಾದ್ದರಿಂದ, ಗರಿಷ್ಠ ಅವಧಿಯ ಮೂರನೇ ಒಂದು ಭಾಗ, "
                          "ಅಂದರೆ {threshold} ದಿನಗಳ ನಂತರ ಬಾಂಡ್ ಮೇಲೆ ಬಿಡುಗಡೆಗೆ ಅರ್ಹರಾಗಿದ್ದಾರೆ.",
        "fraction_general": "ಗರಿಷ್ಠ ಅವಧಿಯ ಅರ್ಧ ಭಾಗ {threshold} ದಿನಗಳು.",
        "eligible": "ಅರ್ಜಿದಾರರು {eligible_from} ರಂದು ಈ ಮಿತಿಯನ್ನು ದಾಟಿದ್ದು, ಅದರ ನಂತರ {overdue} ದಿನಗಳು ಬಂಧನದಲ್ಲಿದ್ದಾರೆ.",
        "ceiling": "ಅರ್ಜಿದಾರರು ಅಪರಾಧಕ್ಕೆ ನಿಗದಿತ ಗರಿಷ್ಠ ಅವಧಿಗಿಂತ ಹೆಚ್ಚು ಕಾಲ ಬಂಧನದಲ್ಲಿದ್ದಾರೆ; ಯಾವುದೇ ವಿಚಾರಣಾಧೀನ ಕೈದಿಯನ್ನು ಹಾಗೆ ಇರಿಸುವಂತಿಲ್ಲ.",
        "remand": "ಅರ್ಜಿದಾರರನ್ನು ಮೊದಲ ಬಾರಿಗೆ {remand} ರಂದು ರಿಮಾಂಡ್ ಮಾಡಲಾಯಿತು.",
        "no_cs": "{today} ರವರೆಗೆ ದೋಷಾರೋಪಣ ಪಟ್ಟಿ ಸಲ್ಲಿಸಲಾಗಿಲ್ಲ; {period} ದಿನಗಳ ಶಾಸನಬದ್ಧ ಅವಧಿ {accrual} ರಂದು ಮುಗಿದಿದೆ.",
        "db_right": "ಆದ್ದರಿಂದ ಅರ್ಜಿದಾರರಿಗೆ ಡಿಫಾಲ್ಟ್ ಜಾಮೀನಿನ ಅವಿನಾಶಿ ಹಕ್ಕು ಇದ್ದು, ಈ ಅರ್ಜಿಯ ಮೂಲಕ ಆ ಹಕ್ಕನ್ನು ಚಲಾಯಿಸುತ್ತಾರೆ.",
        "bail_granted": "{bail_date} ರಂದು ಅರ್ಜಿದಾರರಿಗೆ ಜಾಮೀನು ನೀಡಲಾಗಿದ್ದರೂ, ಜಾಮೀನುದಾರರನ್ನು ಒದಗಿಸಲು ಸಾಧ್ಯವಾಗಿಲ್ಲ.",
        "insight": "{title}: {explanation}",
        "judgment": "ಅರ್ಜಿದಾರರು {citation} ({court}) ಅನ್ನು ಅವಲಂಬಿಸುತ್ತಾರೆ: \"{passage}\"",
        "prayer_479": "ಆದ್ದರಿಂದ BNSS ಕಲಂ 479 ರ ಅಡಿಯಲ್ಲಿ ಅರ್ಜಿದಾರರನ್ನು ಜಾಮೀನು/ಬಾಂಡ್ ಮೇಲೆ ಬಿಡುಗಡೆ ಮಾಡಬೇಕೆಂದು ಪ್ರಾರ್ಥನೆ.",
        "prayer_db": "ಆದ್ದರಿಂದ ಅರ್ಜಿದಾರರನ್ನು ಡಿಫಾಲ್ಟ್ ಜಾಮೀನಿನ ಮೇಲೆ ಬಿಡುಗಡೆ ಮಾಡಬೇಕೆಂದು ಪ್ರಾರ್ಥನೆ.",
        "prayer_surety": "ಆದ್ದರಿಂದ ಜಾಮೀನು ಷರತ್ತುಗಳನ್ನು ಮಾರ್ಪಡಿಸಿ ವೈಯಕ್ತಿಕ ಬಾಂಡ್ ಮೇಲೆ ಬಿಡುಗಡೆ ಮಾಡಬೇಕೆಂದು ಪ್ರಾರ್ಥನೆ.",
        "prayer_generic": "ಆದ್ದರಿಂದ ಮಾನ್ಯ ನ್ಯಾಯಾಲಯವು ಸೂಕ್ತವೆಂದು ಭಾವಿಸುವ ಪರಿಹಾರ ನೀಡಬೇಕೆಂದು ಪ್ರಾರ್ಥನೆ.",
        "note": "ಸೂಚನೆ: ಸರ್ಕಾರಿ ಅಭಿಯೋಜಕರನ್ನು ಆಲಿಸಿ ಕಾರಣಗಳನ್ನು ದಾಖಲಿಸಿ ಮಾನ್ಯ ನ್ಯಾಯಾಲಯವು ಬಂಧನ ಮುಂದುವರಿಸಲು ಆದೇಶಿಸಬಹುದು.",
        "sign": "ಅರ್ಜಿದಾರರ ಪರ ವಕೀಲರು (ಕಾನೂನು ನೆರವು)",
    },
}
KN_NOTE = "Kannada text is template-based; have it reviewed by a Kannada-speaking lawyer before filing."
REL_KN = {"s/o": "ತಂದೆ", "d/o": "ತಂದೆ", "w/o": "ಪತಿ"}


def build(draft_type: str, language: str, ctx: dict, today: date) -> DraftDoc:
    """ctx keys: person, case, eligibility (case result dict), facts (field→row), insights (accepted), judgments."""
    if draft_type not in DRAFT_TYPES:
        raise ValueError(f"Unknown draft type {draft_type}")
    L = T[language]
    p, c, e = ctx["person"], ctx["case"], ctx.get("eligibility") or {}
    facts = ctx.get("facts", {})
    S: list[Sentence] = []

    def add(key: str, sources: list[Source], **kw) -> None:
        S.append(Sentence(f"s{len(S) + 1}", L[key].format(**kw), sources))

    person_src = Source("person", p["id"], [p["name"], p.get("relative") or "", p.get("jail") or ""])
    case_src = Source("case", c["id"], [c.get("court") or "", c.get("case_number") or "", c.get("cnr") or "",
                                        c.get("fir") or "", c.get("ps") or ""])
    tpl = Source("kb", f"rules:{draft_type}", list(ctx.get("rule_refs", [])))
    add("court", [case_src], court=c.get("court") or "")
    add("cause", [tpl], title=DRAFT_TYPES[draft_type])
    rel = p.get("relation") or "s/o"
    add("parties", [person_src], name=p["name"], relation=REL_KN.get(rel, rel) if language == "kn" else rel,
        relative=p.get("relative") or "", jail=p.get("jail") or "")
    add("case", [case_src], case_number=c.get("case_number") or "", cnr=c.get("cnr") or "", fir=c.get("fir") or "",
        ps=c.get("ps") or "")
    sections = ", ".join(c.get("charges", []))
    add("charges", [Source("case", c["id"] + ":charges", c.get("charges", []))], sections=sections)
    arrest = facts.get("arrest_datetime")
    if arrest:
        add("arrest", [Source("fact", arrest["id"], [str(arrest["value"])[:10], arrest["span_text"]])],
            arrest_date=_d(arrest["value"]))
    elig_src = Source("eligibility", c["id"], [str(e.get(k)) for k in ("counted_days", "custody_days", "accused_days",
                                                                         "threshold_days", "max_days", "days_overdue",
                                                                         "eligible_from_date", "max_term") if e.get(k) is not None]
                      + [today.isoformat()])
    if draft_type in ("section_479", "regular_bail", "speedy_trial") and e:
        add("custody", [elig_src], today=_d(today), counted=e.get("counted_days"), custody=e.get("custody_days"),
            accused=e.get("accused_days"))
        if e.get("max_term"):
            add("max", [elig_src], max_term=e["max_term"])
        if e.get("status") == "CRITICAL_MUST_RELEASE":
            add("ceiling", [elig_src])
        elif e.get("threshold_days"):
            add("fraction_first" if e.get("first_time_offender") else "fraction_general", [elig_src],
                threshold=e["threshold_days"])
            if e.get("eligible_from_date"):
                add("eligible", [elig_src], eligible_from=_d(e["eligible_from_date"]), overdue=e.get("days_overdue", 0))
    if draft_type == "default_bail":
        f = next((f for f in e.get("findings", []) if f["code"] in ("URGENT_DEFAULT_BAIL", "DEFAULT_BAIL_RIGHT_ASSERTED")), None)
        if c.get("first_remand_date"):
            add("remand", [Source("case", c["id"] + ":remand", [c["first_remand_date"]])], remand=_d(c["first_remand_date"]))
        if f:
            m = re.search(r"period (\d+) days", f["message"])
            period = m.group(1) if m else ""
            add("no_cs", [Source("eligibility", c["id"] + ":default_bail", [f["message"], f["date"], today.isoformat()])],
                today=_d(today), period=period, accrual=_d(f["date"]))
            add("db_right", [Source("kb", "rule:default_bail", [])])
    if draft_type == "surety_modification" and c.get("bail_granted_date"):
        add("bail_granted", [Source("case", c["id"] + ":bail", [c["bail_granted_date"]])], bail_date=_d(c["bail_granted_date"]))
    for ins in ctx.get("insights", []):
        add("insight", [Source("insight", ins["id"], [ins["title"], ins["explanation"]] + [ev["text"] for ev in ins["evidence"]])],
            title=ins["title"], explanation=ins["explanation"])
    for j in ctx.get("judgments", [])[:3]:
        add("judgment", [Source("judgment", j["id"], [j["citation"], j["court"], j["passage"]])], citation=j["citation"],
            court=j["court"], passage=j["passage"][:300])
    prayer = {"section_479": "prayer_479", "default_bail": "prayer_db", "surety_modification": "prayer_surety"}.get(draft_type,
                                                                                                                  "prayer_generic")
    add(prayer, [tpl])
    add("note", [tpl])
    add("sign", [tpl])
    notes = [KN_NOTE] if language == "kn" else []
    return DraftDoc(draft_type, language, DRAFT_TYPES[draft_type], S,
                    "Decision support for a qualified lawyer. Not legal advice. Verify all sections and citations.", notes)


def polish_with_llm(doc: DraftDoc, today: date) -> int:
    """Optional LLM wording pass. A polished sentence is kept only if it passes verification
    AND keeps exactly the same checkable tokens. Returns number of sentences changed."""
    from pydantic import BaseModel

    class Out(BaseModel):
        sentences: list[dict[str, str]]

    res = get_llm().structured("draft_application", Out, language=doc.language,
                               sentences=json.dumps([{"id": s.id, "text": s.text} for s in doc.sentences], ensure_ascii=False))
    if res.data is None:
        return 0
    changed = 0
    by_id = {s.id: s for s in doc.sentences}
    for item in res.data.sentences:  # type: ignore[attr-defined]
        s = by_id.get(item.get("id", ""))
        if not s or not item.get("text"):
            continue
        before, after = checkable_tokens(s.text, today), checkable_tokens(item["text"], today)
        if {k: sorted(v) for k, v in before.items()} == {k: sorted(v) for k, v in after.items()}:
            s.text = item["text"]
            changed += 1
    return changed


def to_dict(doc: DraftDoc) -> dict:
    return asdict(doc)
