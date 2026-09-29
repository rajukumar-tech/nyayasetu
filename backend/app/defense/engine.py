"""Defense Insight Engine — every lawful route to release, discharge, acquittal or faster
disposal, grounded in the record. It SUGGESTS; the assigned lawyer decides.

Guardrails (enforced here, tested in tests/test_defense.py):
  * an insight with no record evidence span is never emitted;
  * judgments come only from the local retrieved corpus (retrieval.py) — never generated;
  * no win probabilities; only lawful strategies (nothing about contacting/pressuring
    witnesses or victims);
  * access control + audit happen in the API layer (lawyer-only).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from app.core.config import settings
from app.domain import Case, Person
from app.eligibility.engine import CaseResult, Status
from app.legal_kb.kb import KnowledgeBase

DISCLAIMER = "Decision support for a qualified lawyer. Not legal advice. Verify all sections and citations."
POLICE_RANKS = re.compile(r"\b(HC|PC|ASI|SI|PSI|CPC|WPC|Inspector|Constable|Head Constable|IO|police)\b", re.I)
FORBIDDEN = re.compile(r"contact(ing)? (the )?(witness|victim|complainant)|influenc|pressur|threat(en)? (the )?witness|"
                       r"persuade (the )?(witness|victim)|fabricat|abscond|evade", re.I)


@dataclass
class Evidence:
    fact_id: str
    document_id: str
    doc_type: str
    page: int
    start: int
    end: int
    text: str
    field: str


@dataclass
class Insight:
    code: str
    category: str  # A-F
    severity: str  # critical | high | medium | low
    title: str
    explanation: str
    next_steps: str
    evidence: list[Evidence]
    legal_basis: list[str]
    liberty_impact: int  # 0-3 (3 = immediate release route)
    urgency: int  # 0-3
    support: float  # 0-1 strength of record support
    query: str = ""  # retrieval query for similar judgments
    judgments: list[dict] = field(default_factory=list)

    @property
    def rank_score(self) -> float:
        return round(0.45 * self.support + 0.35 * self.liberty_impact / 3 + 0.20 * self.urgency / 3, 4)


class Facts:
    """Extracted facts for one case, grouped by field; best (highest confidence, reviewed) first."""

    def __init__(self, rows: list[dict]):
        self.rows = [r for r in rows if r.get("review_status") != "rejected"]
        self.by_field: dict[str, list[dict]] = {}
        for r in sorted(self.rows, key=lambda r: (r.get("review_status") in ("confirmed", "corrected"), r["confidence"]),
                        reverse=True):
            self.by_field.setdefault(r["field"], []).append(r)

    def get(self, name: str) -> dict | None:
        return (self.by_field.get(name) or [None])[0]

    def all(self, name: str) -> list[dict]:
        return self.by_field.get(name, [])

    @staticmethod
    def value(r: dict | None):
        if r is None:
            return None
        return r["corrected_value"] if r.get("review_status") == "corrected" else r["value"]

    @staticmethod
    def ev(r: dict) -> Evidence:
        return Evidence(r["id"], r["document_id"], r.get("doc_type", ""), r.get("page", 1), r["span_start"], r["span_end"],
                        r["span_text"], r["field"])


def _dt(v) -> datetime | None:
    if not v:
        return None
    try:
        s = str(v)
        return datetime.fromisoformat(s if "T" in s else s + "T00:00")
    except ValueError:
        return None


def _load_ingredients() -> list[dict]:
    p = Path(settings.legal_data_dir) / "ingredients.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("ingredients", []) if p.exists() else []


def detect(person: Person, case: Case, facts_rows: list[dict], result: CaseResult | None, kb: KnowledgeBase,
           today: date, age_years: int | None = None) -> list[Insight]:
    F = Facts(facts_rows)
    out: list[Insight] = []
    rule = kb.rules
    ref = lambda name: rule[name].ref if name in rule else name  # noqa: E731

    def yn(field_name: str) -> tuple[str | None, dict | None]:
        r = F.get(field_name)
        return (Facts.value(r), r)

    # ---------------- A. Procedural / arrest safeguards
    v, r = yn("grounds_of_arrest")
    if r and v in ("no", "not_recorded"):
        out.append(Insight("GROUNDS_NOT_COMMUNICATED", "A", "high", "Grounds of arrest not communicated / not recorded",
                           f"The arrest memo records grounds of arrest as '{r['span_text'] or 'blank'}'. Communicating the grounds "
                           "of arrest is a constitutional and statutory requirement; non-compliance can vitiate the arrest "
                           "and consequential remand.",
                           "Raise in the bail application and seek a declaration that the arrest is illegal; request the "
                           "arrest memo and case diary.", [Facts.ev(r)], [ref("grounds_of_arrest")], 3, 2, r["confidence"],
                           "grounds of arrest not communicated in writing Article 22 arrest illegal"))
    a, p = F.get("arrest_datetime"), F.get("production_datetime")
    at, pt = _dt(Facts.value(a)), _dt(Facts.value(p))
    if a and p and at and pt:
        hours = (pt - at).total_seconds() / 3600
        limit = rule["production_before_magistrate"]["max_hours"] if "production_before_magistrate" in rule else 24
        time_known = "T" in str(Facts.value(a)) and "T" in str(Facts.value(p))
        if hours > limit and time_known:
            out.append(Insight("PRODUCTION_BEYOND_24H", "A", "critical", f"Produced before Magistrate after {hours:.0f} hours",
                               f"Arrested {at:%d %b %Y %H:%M}; first produced {pt:%d %b %Y %H:%M} — {hours:.0f} hours, beyond "
                               f"the {limit}-hour limit (journey time is excluded; check the record for any).",
                               "Plead illegal detention for the excess period; seek release and consider a complaint to "
                               "the Magistrate. Obtain station diary entries for the journey.", [Facts.ev(a), Facts.ev(p)],
                               [ref("production_before_magistrate")], 3, 3, min(a["confidence"], p["confidence"]),
                               "produced before magistrate more than twenty-four hours after arrest illegal detention"))
    v1, r1 = yn("arrest_memo_attested")
    v2, r2 = yn("relative_informed")
    defects = [(r1, "memo not attested by a witness") if r1 and v1 in ("no", "not_recorded") else None,
               (r2, "no relative/friend informed of the arrest") if r2 and v2 in ("no", "not_recorded") else None]
    defects = [d for d in defects if d]
    if defects:
        out.append(Insight("ARREST_MEMO_DEFECTS", "A", "medium", "Arrest memo defects",
                           "The arrest memo shows: " + "; ".join(d[1] for d in defects) + ".",
                           "Point out the procedural lapses in the bail application; they bear on the reliability of the "
                           "arrest record.", [Facts.ev(d[0]) for d in defects], [ref("arrest_memo"), ref("inform_relative")],
                           1, 1, min(d[0]["confidence"] for d in defects),
                           "arrest memo not attested relative not informed procedure violation"))
    g = Facts.value(F.get("gender")) or person.gender or ""
    if str(g).lower().startswith("f") and at and (at.hour >= 18 or at.hour < 6) and "T" in str(Facts.value(a)):
        perm_v, perm_r = yn("night_arrest_permission")
        wo_v, wo_r = yn("woman_officer_present")
        ev = [Facts.ev(a)] + [Facts.ev(x) for x, val in ((perm_r, perm_v), (wo_r, wo_v)) if x and val in ("no", "not_recorded")]
        if len(ev) > 1:
            out.append(Insight("WOMAN_ARRESTED_AT_NIGHT", "A", "high", "Woman arrested after sunset without safeguards",
                               f"A woman was arrested at {at:%H:%M} and the record shows the required safeguards were not "
                               "followed (prior Magistrate permission and/or a woman officer).",
                               "Challenge the legality of the arrest in the bail application.", ev,
                               [ref("woman_arrest_night")], 2, 2, a["confidence"],
                               "woman arrested after sunset without permission of magistrate woman police officer"))
    v, r = yn("medical_examination")
    if r and v in ("no", "not_recorded"):
        out.append(Insight("NO_MEDICAL_EXAMINATION", "A", "medium", "No medical examination after arrest",
                           "The record does not show a medical examination of the arrested person.",
                           "Seek the medical examination record; relevant if custodial ill-treatment is alleged.",
                           [Facts.ev(r)], [ref("medical_examination")], 1, 1, r["confidence"], "medical examination arrested person"))
    r = F.get("remand_reasons")
    if r and len(str(Facts.value(r)).split()) <= 3:
        out.append(Insight("MECHANICAL_REMAND", "A", "medium", "Remand order without reasons",
                           f"The remand order's reasons read only '{r['span_text']}' — suggesting non-application of mind.",
                           "Challenge the remand order; argue that further detention was authorised mechanically.",
                           [Facts.ev(r)], [ref("police_custody_limit")], 2, 1, r["confidence"],
                           "remand order mechanical without reasons application of mind"))
    r = F.get("recovery")
    if r and re.search(r"no independent|without (independent|panch)|no panch", str(Facts.value(r)), re.I):
        out.append(Insight("SEIZURE_WITHOUT_INDEPENDENT_WITNESS", "A", "high", "Recovery/seizure without independent witnesses",
                           f"The charge sheet says: '{r['span_text']}'.",
                           "Argue that the recovery is not proved; cross-examine the seizure witnesses.",
                           [Facts.ev(r)], [ref("search_seizure_videography")], 1, 1, r["confidence"],
                           "recovery police witnesses no independent panch witness not proved"))

    # ---------------- B. Investigation & evidence gaps
    o, fr = F.get("offence_datetime"), F.get("fir_datetime")
    ot, ft = _dt(Facts.value(o)), _dt(Facts.value(fr))
    if o and fr and ot and ft:
        delay = (ft.date() - ot.date()).days
        expl = Facts.value(F.get("fir_delay_reason"))
        flag_after = rule["fir_delay"]["flag_after_days"] if "fir_delay" in rule else 2
        if delay > flag_after and not (expl and str(expl).strip()):
            ev = [Facts.ev(o), Facts.ev(fr)] + ([Facts.ev(F.get("fir_delay_reason"))] if F.get("fir_delay_reason") else [])
            out.append(Insight("FIR_DELAY_UNEXPLAINED", "B", "high", f"FIR lodged {delay} days after the occurrence, unexplained",
                               f"Occurrence {ot:%d %b %Y}; FIR {ft:%d %b %Y}. No reason for the delay is recorded.",
                               "Use the unexplained delay to argue possible embellishment; cross-examine the informant on it.",
                               ev, [ref("fir_delay")], 1, 1, min(o["confidence"], fr["confidence"]),
                               "delay in lodging FIR unexplained embellishment"))
    cs = F.get("charge_sheet_offence_date")
    if o and cs and ot:
        csd = _dt(Facts.value(cs))
        if csd and csd.date() != ot.date():
            out.append(Insight("DATE_CONTRADICTION_FIR_CHARGESHEET", "B", "high", "FIR and charge sheet give different offence dates",
                               f"FIR: {ot:%d %b %Y}; charge sheet: {csd:%d %b %Y}.",
                               "Put the contradiction to the investigating officer in cross-examination; it goes to the "
                               "reliability of the prosecution case.", [Facts.ev(o), Facts.ev(cs)], [], 1, 1,
                               min(o["confidence"], cs["confidence"]), "contradiction date of offence FIR charge sheet"))
    for w in F.all("witnesses")[:1]:
        names = [x.strip() for x in re.split(r"[;,]", str(Facts.value(w))) if x.strip()]
        independent = [x for x in names if not POLICE_RANKS.search(x) and not re.search(r"complainant|victim|informant|CW-1\b", x, re.I)]
        if names and not independent:
            out.append(Insight("NO_INDEPENDENT_WITNESSES", "B", "medium", "No independent witnesses cited",
                               "Every cited witness is a police official or the complainant.",
                               "Stress the absence of independent corroboration at the bail and trial stages.",
                               [Facts.ev(w)], [], 1, 0, w["confidence"],
                               "all witnesses police officials interested witnesses no independent witness"))
    r = F.get("fsl_status")
    if r and re.search(r"pending|awaited|not (received|sent|obtained)|nil", str(Facts.value(r)), re.I):
        out.append(Insight("FSL_PENDING", "B", "medium", "Forensic (FSL) report pending",
                           f"FSL report: '{r['span_text']}'.", "Seek bail on the ground that the investigation relies on "
                           "evidence not yet available; press the prosecution to produce the report or proceed without it.",
                           [Facts.ev(r)], [], 1, 1, r["confidence"], "FSL report not produced forensic link seized article"))
    r = F.get("tip_status")
    if r and re.search(r"not held|no|nil", str(Facts.value(r)), re.I):
        out.append(Insight("TIP_NOT_HELD", "B", "low", "Test identification parade not held",
                           "No test identification parade was held. If identity is disputed, dock identification alone is weak.",
                           "Confirm whether identity is disputed; if so, raise it in cross-examination.",
                           [Facts.ev(r)], [], 0, 0, r["confidence"] * 0.8,
                           "test identification parade not held identity disputed dock identification"))
    r = F.get("confession")
    if r and re.search(r"police|investigating officer|\bIO\b|inspector|sub.?inspector", str(Facts.value(r)), re.I):
        out.append(Insight("CONFESSION_TO_POLICE", "B", "high", "Prosecution relies on a confession to police",
                           f"The charge sheet records: '{r['span_text']}'. A confession to a police officer is generally "
                           "inadmissible, save for the part leading to discovery of a fact.",
                           "Object to reliance on the confession; limit any discovery evidence strictly.",
                           [Facts.ev(r)], [ref("confession_to_police")], 1, 1, r["confidence"],
                           "confession before investigating officer inadmissible discovery"))
    hearings = F.all("hearing")
    absent = [h for h in hearings if re.search(r"witness\w* (absent|not present)|summons to be re-?issued|NBW",
                                               str((Facts.value(h) or {}).get("reason_text", "")), re.I)]
    hostile = [h for h in hearings if re.search(r"hostile", str((Facts.value(h) or {}).get("reason_text", "")), re.I)]
    if len(absent) >= 3:
        out.append(Insight("PROSECUTION_WITNESSES_ABSENT", "B", "medium", f"Prosecution witnesses absent at {len(absent)} hearings",
                           "The order sheet repeatedly records prosecution witnesses as absent.",
                           "Seek closure of prosecution evidence or bail citing the prosecution's delay.",
                           [Facts.ev(h) for h in absent[:5]], [], 2, 1, 0.85,
                           "prosecution witnesses repeatedly absent closure of evidence"))
    if hostile:
        out.append(Insight("WITNESS_HOSTILE", "B", "medium", "Prosecution witness turned hostile",
                           "At least one prosecution witness has turned hostile.",
                           "Note the weakening of the prosecution case in the bail application.",
                           [Facts.ev(h) for h in hostile[:3]], [], 1, 0, 0.8, "prosecution witness turned hostile"))

    # ---------------- C. Charge-level arguments
    charge_rows = F.all("charge")
    text_blob = " ".join(str(Facts.value(x)) for x in F.all("brief_facts") + F.all("recovery") + F.all("weapon")).lower()
    for ing in _load_ingredients():
        for crow in charge_rows:
            cv = Facts.value(crow) or {}
            key = f"{cv.get('act')}:{cv.get('section')}"
            if key in ing["sections"] and text_blob.strip() and not any(k in text_blob for k in ing["any_of"]):
                ev = [Facts.ev(crow)] + [Facts.ev(x) for x in F.all("brief_facts")[:1]]
                lesser = ing.get("lesser", {}).get(key)
                out.append(Insight("INGREDIENT_NOT_IN_RECORD", "C", "medium",
                                   f"{key.replace(':', ' ')}: an essential ingredient is not described in the record",
                                   f"Ingredient: {ing['ingredient']}. The recorded facts do not mention it."
                                   + (f" A lesser section ({lesser}) may be the better fit." if lesser else ""),
                                   "Assess a discharge application or argue for framing a lesser charge.", ev,
                                   [f"ingredients:{key}"], 1, 0, 0.6, f"essential ingredient {key} discharge lesser offence"))
                break
    if result and "IPC_BNS_TRANSITION_MISMATCH" in result.flag_codes() and charge_rows:
        out.append(Insight("IPC_BNS_TRANSITION_ERROR", "C", "high", "Wrong code applied for the offence date",
                           "The charge uses a section from a code that does not govern punishment for the offence date "
                           "(offences before 1 July 2024 remain under the IPC for punishment).",
                           "Seek correction of the charge; ensure the lower punishment regime is applied.",
                           [Facts.ev(charge_rows[0])], [ref("transition")], 1, 1, 0.8, "IPC BNS transition offence before 1 July 2024"))

    # ---------------- D. Faster exits (from legal KB)
    recs = []
    for crow in charge_rows:
        cv = Facts.value(crow) or {}
        rec = kb.get(cv.get("act", ""), cv.get("section", ""))
        if rec:
            recs.append((crow, rec))
    if recs:
        pb = rule.get("plea_bargaining")
        excluded_cats = set(pb["excluded_categories"]) if pb else set()
        max_years = pb["max_imprisonment_years"] if pb else 7
        def pb_ok(rec) -> bool:
            t = rec.effective_max
            return (not rec.special_law and not (set(rec.offence_categories) & excluded_cats)
                    and (t.kind == "none" or (t.kind == "term" and t.months <= max_years * 12)))
        if all(pb_ok(rec) for _, rec in recs) and (result is None or result.status != Status.EXCLUDED_479):
            out.append(Insight("PLEA_BARGAINING_AVAILABLE", "D", "medium", "Plea bargaining appears available",
                               "Every charged offence is within the plea-bargaining ceiling and none falls in an excluded category "
                               "(offences against women or children, socio-economic offences).",
                               "Discuss plea bargaining with the accused ONLY if they wish to plead guilty voluntarily; "
                               "explain consequences fully.", [Facts.ev(c) for c, _ in recs],
                               [pb.ref if pb else "plea_bargaining"] + [r.key for _, r in recs], 2, 1, 0.8,
                               "plea bargaining offence punishable less than seven years"))
        comp = [(c, rec) for c, rec in recs if rec.compoundable in ("with_permission", "without_permission")]
        if comp and len(comp) == len(recs):
            c, rec = comp[0]
            perm = "with the court's permission" if any(r.compoundable == "with_permission" for _, r in comp) else "without the court's permission"
            out.append(Insight("COMPOUNDABLE_SETTLEMENT", "D", "medium", "Offence is compoundable — settlement route",
                               f"{', '.join(r.key.replace(':', ' ') for _, r in comp)} may be compounded {perm} by "
                               f"{rec.compoundable_by or 'the aggrieved person'}. Lok Adalat referral may also be suitable.",
                               "If the aggrieved person independently wishes to settle, a compounding application can be filed. "
                               "Any settlement must be entirely voluntary — do not approach or pressure the victim.",
                               [Facts.ev(x) for x, _ in comp], [r.key for _, r in comp] + [ref("lok_adalat")], 2, 1, 0.8,
                               "compounding of offence settlement permission of court"))
        young = age_years is not None and age_years < (rule["probation"]["young_offender_age_below"] if "probation" in rule else 21)
        if result and result.first_time_offender and not any(r.effective_max.is_death_or_life for _, r in recs):
            out.append(Insight("PROBATION_CONSIDERATION", "D", "low",
                               "Probation may be available" + (" (young first-time offender)" if young else " (first-time offender)"),
                               "No subsisting prior conviction and the offence is not punishable with death or life imprisonment.",
                               "If convicted, seek release on probation of good conduct instead of sentence.",
                               [Facts.ev(c) for c, _ in recs[:1]], [ref("probation")], 1, 0, 0.7,
                               "probation of offenders first offender release good conduct"))

    # ---------------- release routes from the deterministic engine (evidence = custody documents)
    custody_ev = [Facts.ev(x) for x in (F.all("arrest_datetime")[:1] + F.all("remand_date")[:1] + F.all("admission_date")[:1])]
    if result and custody_ev:
        if result.status == Status.CRITICAL_MUST_RELEASE:
            out.append(Insight("DETAINED_BEYOND_MAXIMUM", "D", "critical", "Detained beyond the maximum sentence",
                               f"Counted detention {result.counted_days} days ≥ maximum {result.max_days} days.",
                               "Move immediately for release; notify the jail superintendent and DLSA.", custody_ev,
                               [ref("section_479")], 3, 3, 0.95, "undertrial detained beyond maximum period release"))
        elif result.status == Status.ELIGIBLE or result.interpretations.get("if_inputs_confirmed", {}).get("status") == "ELIGIBLE":
            out.append(Insight("SECTION_479_RELEASE", "D", "high", "Section 479 BNSS release application",
                               f"Counted detention {result.counted_days} days vs threshold {result.threshold_days} days "
                               f"({result.fraction} of maximum).", "File the Section 479 application; ask the "
                               "superintendent to forward it.", custody_ev, [ref("section_479")], 3, 3, 0.9 if result.status == Status.ELIGIBLE else 0.6,
                               "undertrial one-half one-third maximum period release bail section 479 436A"))
        if "URGENT_DEFAULT_BAIL" in result.finding_codes():
            out.append(Insight("DEFAULT_BAIL", "D", "critical", "Default bail — charge sheet not filed in time",
                               next(f.message for f in result.findings if f.code == "URGENT_DEFAULT_BAIL"),
                               "File the default-bail application TODAY, before any charge sheet is filed.", custody_ev,
                               [ref("default_bail")], 3, 3, 0.9, "default bail charge sheet not filed statutory period indefeasible right"))
        if "CRITICAL_BAIL_NOT_FURNISHED" in result.finding_codes():
            out.append(Insight("SURETY_RELIEF", "D", "critical", "Bail granted but surety not furnished",
                               next(f.message for f in result.findings if f.code == "CRITICAL_BAIL_NOT_FURNISHED"),
                               "Apply for modification of bail conditions / personal bond; refer to the poor-prisoner "
                               "support scheme via DLSA.", custody_ev, [ref("surety_not_furnished")], 3, 3, 0.9,
                               "indigent accused unable to furnish surety relaxation personal bond"))
        if {"TIME_SERVED_EXCEEDS_MINIMUM", "TIME_SERVED_SUBSTANTIAL"} & result.finding_codes():
            f = next(f for f in result.findings if f.code.startswith("TIME_SERVED"))
            out.append(Insight("TIME_SERVED", "D", "medium", "Time already served is substantial", f.message,
                               "Consider early disposal / plea bargaining if the accused so wishes.", custody_ev, [], 2, 1, 0.8,
                               "time already undergone set off early disposal"))

    # ---------------- E. Speedy trial
    if result and result.timeline and hearings:
        years = result.custody_days / 365.25
        accused = sum(1 for h in hearings if re.search(r"accused", str((Facts.value(h) or {}).get("reason_text", "")), re.I)
                      and not re.search(r"not produced", str((Facts.value(h) or {}).get("reason_text", "")), re.I))
        flag_years = rule["speedy_trial"]["flag_if_pending_years"] if "speedy_trial" in rule else 3
        if years >= flag_years * 0.66 and accused <= len(hearings) / 4:
            out.append(Insight("SPEEDY_TRIAL", "E", "high" if years >= flag_years else "medium",
                               f"Prolonged pre-trial detention ({years:.1f} years) with delay not caused by the accused",
                               f"{len(hearings)} recorded hearings; only {accused} adjournment(s) at the accused's instance.",
                               "Prepare the timeline exhibit (auto-generated) and an Article 21 speedy-trial argument; "
                               "seek bail and directions for day-to-day trial.", [Facts.ev(h) for h in hearings[:6]],
                               [ref("speedy_trial")], 2, 2, 0.8, "right to speedy trial Article 21 prolonged incarceration undertrial"))

    return rank([i for i in out if _guard(i)])


def _guard(i: Insight) -> bool:
    """Insights without record evidence are never shown; forbidden strategies never emitted."""
    if not i.evidence or not any(e.text or e.end > e.start for e in i.evidence):
        return False
    return not FORBIDDEN.search(i.next_steps.replace("do not approach or pressure the victim", ""))


def rank(insights: list[Insight]) -> list[Insight]:
    return sorted(insights, key=lambda i: -i.rank_score)


def attach_judgments(insights: list[Insight], index, k: int = 2) -> None:
    """Similar judgments come ONLY from the retrieved corpus; nothing is generated."""
    for i in insights:
        if not i.query:
            continue
        i.judgments = [{"citation": h.passage.citation, "court": h.passage.court, "date": h.passage.date,
                        "url": h.passage.url, "passage": h.snippet, "score": round(h.score, 3),
                        "synthetic": h.passage.synthetic, "id": h.passage.id} for h in index.search(i.query, k)]
