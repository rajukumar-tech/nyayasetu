"""Deterministic eligibility engine — Section 479 BNSS, statutory ceiling, default bail,
bail-not-furnished and time-served checks.

Pure Python. No LLM, no I/O. Every threshold comes from the legal knowledge base
(data/legal/rules.yaml); every step is written to a reasoning trace. A result of
ELIGIBLE means "eligible to apply" — the court may still order continued detention.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from fractions import Fraction

from app.domain import (
    Attribution, Case, CaseStatus, Charge, ComputeContext, ConvictionStatus, Person,
)
from app.legal_kb.kb import Derivation, KnowledgeBase, Term
from app.timeline.reconstruct import Timeline, inclusive_days, reconstruct

RULE_VERSION = "eligibility-engine/1.0.0"
DISCLAIMER = ("Decision support for a qualified lawyer. Not legal advice. 'Eligible' means eligible to apply: "
              "the court may, after hearing the Public Prosecutor and recording reasons, order continued detention. "
              "Verify all sections and citations.")
BORDERLINE_DAYS = 2


class Status(StrEnum):
    CRITICAL_ACQUITTED_DETAINED = "CRITICAL_ACQUITTED_DETAINED"
    CRITICAL_MUST_RELEASE = "CRITICAL_MUST_RELEASE"
    URGENT_DEFAULT_BAIL = "URGENT_DEFAULT_BAIL"
    CRITICAL_BAIL_NOT_FURNISHED = "CRITICAL_BAIL_NOT_FURNISHED"
    ELIGIBLE = "ELIGIBLE"
    REVIEW_MULTIPLE_CASES = "REVIEW_MULTIPLE_CASES"
    REVIEW = "REVIEW"
    NOT_YET = "NOT_YET"
    EXCLUDED_479 = "EXCLUDED_479"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# Most urgent first. Used for the person's overall status and for sorting dashboards.
URGENCY: list[str] = [s.value for s in Status]


def urgency_rank(code: str) -> int:
    return URGENCY.index(code) if code in URGENCY else len(URGENCY)


@dataclass
class TraceStep:
    rule: str
    text: str
    refs: list[str] = field(default_factory=list)


@dataclass
class Flag:
    code: str
    message: str
    severity: str = "warning"  # info | warning | critical


@dataclass
class Finding:
    code: str
    message: str
    severity: str
    date: date | None = None
    refs: list[str] = field(default_factory=list)


@dataclass
class ChargeCalc:
    charge: str
    max_term: str
    is_death_or_life: bool
    fine_only: bool
    special_law: bool
    max_days: int | None
    threshold_days: int | None
    eligible_from: date | None
    derivation: list[str]
    record_key: str | None
    unverified: list[str]


@dataclass
class CaseResult:
    case_id: str
    status: Status
    eligible_from_date: date | None = None
    projected_date: date | None = None
    days_overdue: int | None = None
    custody_days: int = 0
    accused_days: int = 0
    counted_days: int = 0
    threshold_days: int | None = None
    max_days: int | None = None
    max_term: str | None = None
    fraction: str | None = None
    first_time_offender: bool | None = None
    trace: list[TraceStep] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    needs_verification: list[str] = field(default_factory=list)
    charge_calcs: list[ChargeCalc] = field(default_factory=list)
    interpretations: dict[str, dict] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    timeline: Timeline | None = None
    confidence: float = 1.0

    def flag_codes(self) -> set[str]:
        return {f.code for f in self.flags}

    def finding_codes(self) -> set[str]:
        return {f.code for f in self.findings}

    @property
    def urgency(self) -> str:
        codes = [self.status.value] + [f.code for f in self.findings]
        return min(codes, key=urgency_rank)


@dataclass
class PersonResult:
    person_id: str
    overall_status: str
    cases: list[CaseResult]
    rule_version: str
    legal_data_version: str
    computed_at: datetime
    flags: list[Flag]
    confidence: float
    disclaimer: str = DISCLAIMER

    @property
    def eligible_from_date(self) -> date | None:
        dates = [c.eligible_from_date for c in self.cases if c.eligible_from_date]
        return min(dates) if dates else None

    @property
    def days_overdue(self) -> int | None:
        vals = [c.days_overdue for c in self.cases if c.days_overdue is not None and c.status == Status.ELIGIBLE]
        return max(vals) if vals else None


# ---------------------------------------------------------------- helpers

class _Trace:
    def __init__(self) -> None:
        self.steps: list[TraceStep] = []

    def add(self, rule: str, text: str, *refs: str) -> None:
        self.steps.append(TraceStep(rule, text, [r for r in refs if r]))


def _severity_of_term(t: Term) -> tuple[int, int]:
    return {"death": (3, 0), "life": (2, 0), "term": (1, t.months), "none": (0, 0)}[t.kind]


def _prior_conviction_analysis(person: Person, case: Case, kb: KnowledgeBase, trace: _Trace,
                               flags: list[Flag]) -> bool:
    """Return True if the person is a first-time offender for Section 479."""
    rule = kb.rule("prior_convictions")
    counts = set(rule["counts"])
    priors = [c for c in person.convictions if c.case_id != case.id]
    counted = []
    for c in priors:
        if c.status == ConvictionStatus.JUVENILE:
            juv_counts = bool(rule["juvenile_adjudication_counts"])
            flags.append(Flag("JUVENILE_ADJUDICATION", f"Juvenile adjudication on {c.date.isoformat()} "
                              f"({'counted' if juv_counts else 'not counted'} per legal KB). {rule['juvenile_note']}"))
            if juv_counts:
                counted.append(c)
        elif c.status.value in counts:
            counted.append(c)
            if c.status == ConvictionStatus.UNDER_APPEAL:
                flags.append(Flag("PRIOR_CONVICTION_UNDER_APPEAL",
                                  f"Prior conviction of {c.date.isoformat()} is under appeal — {rule['under_appeal_note']}"))
        else:
            trace.add("prior_convictions", f"Prior conviction of {c.date.isoformat()} was {c.status.value.replace('_', ' ')} "
                      f"— does not count.", rule.ref)
    first = not counted
    trace.add("prior_convictions",
              "No subsisting prior conviction → first-time offender (acquittals, discharges and pending cases do not count)."
              if first else f"{len(counted)} subsisting prior conviction(s) → not a first-time offender.", rule.ref)
    return first


def _accused_delay_days(case: Case, tl: Timeline, ctx: ComputeContext, trace: _Trace,
                        flags: list[Flag], needs: list[str]) -> int:
    """Days of custody that fall inside adjournments attributed to the accused."""
    accused_days = 0
    unknown = 0
    for h in sorted(case.hearings, key=lambda h: h.date):
        if h.attribution == Attribution.ACCUSED:
            if h.next_date is None:
                flags.append(Flag("ACCUSED_DELAY_NO_NEXT_DATE",
                                  f"Adjournment on {h.date.isoformat()} attributed to the accused has no next date — not subtracted."))
                continue
            if not h.reviewer_verified and h.attribution_confidence < ctx.confidence_threshold:
                needs.append(f"Delay attribution for hearing {h.date.isoformat()} ('{h.reason_text[:60]}', "
                             f"confidence {h.attribution_confidence:.2f})")
            period_end = h.next_date - timedelta(days=1)
            overlap = sum(inclusive_days(max(i.start, h.date), min(i.end, period_end)) for i in tl.intervals)
            accused_days += overlap
            trace.add("section_479.accused_delay",
                      f"Hearing {h.date.isoformat()} adjourned to {h.next_date.isoformat()} at the instance of the accused "
                      f"('{h.reason_text[:60]}') → {overlap} custody day(s) excluded.")
        elif h.attribution in (Attribution.UNKNOWN, Attribution.BOTH):
            unknown += 1
    if unknown:
        flags.append(Flag("DELAY_ATTRIBUTION_UNCERTAIN",
                          f"{unknown} adjournment(s) have unknown or shared attribution — NOT subtracted; review to confirm.", "info"))
    return accused_days


# ---------------------------------------------------------------- per-case evaluation

def evaluate_case(person: Person, case: Case, kb: KnowledgeBase, ctx: ComputeContext,
                  other_pending: list[Case]) -> CaseResult:
    today = ctx.today
    trace = _Trace()
    flags: list[Flag] = []
    needs: list[str] = []
    r479 = kb.rule("section_479")
    res = CaseResult(case.id, Status.REVIEW)

    # ---- conviction set aside → treat as pending
    set_aside = any(c.case_id == case.id and c.status == ConvictionStatus.SET_ASIDE for c in person.convictions)
    status = case.status
    if status == CaseStatus.CONVICTED and set_aside:
        flags.append(Flag("CONVICTION_SET_ASIDE_REASSESS", "Conviction in this case was set aside — reassessed as an undertrial."))
        status = CaseStatus.TRIAL

    tl = reconstruct(person, case if status == case.status else _as_pending(case), today, ctx.confidence_threshold)
    res.timeline = tl
    res.custody_days = tl.custody_days
    flags += [Flag(f.code, f.message, f.severity) for f in tl.flags]
    needs += tl.low_confidence
    if not r479.verified:
        needs.append(f"Legal rule 'section_479' ({r479.ref}) is unverified")

    if case.status_confidence < ctx.confidence_threshold:
        needs.append(f"Case status '{case.status.value}' (confidence {case.status_confidence:.2f})")

    # ---- Step 1: not an undertrial?
    if status == CaseStatus.CONVICTED:
        trace.add("step1.status", f"Convicted on {case.conviction_date.isoformat() if case.conviction_date else 'unknown date'} "
                  f"— no longer an undertrial in this case.", r479.ref)
        return _finish(res, Status.NOT_APPLICABLE, trace, flags, needs)
    if status in (CaseStatus.ACQUITTED, CaseStatus.DISCHARGED, CaseStatus.DISPOSED):
        end = case.acquittal_date
        detained_after = end is not None and any(i.end > end for i in tl.intervals)
        if detained_after and not other_pending:
            days = sum(inclusive_days(max(i.start, end + timedelta(days=1)), i.end) for i in tl.intervals if i.end > end)
            trace.add("step1.status", f"Case {status.value} on {end.isoformat()} but custody continues for {days} day(s) afterwards.")
            flags.append(Flag("ACQUITTED_BUT_DETAINED", f"{status.value.capitalize()} on {end.isoformat()} yet still detained "
                              f"({days} day(s)). Immediate release required.", "critical"))
            return _finish(res, Status.CRITICAL_ACQUITTED_DETAINED, trace, flags, needs)
        if detained_after:
            flags.append(Flag("DETAINED_IN_OTHER_CASE", "Custody after disposal is attributable to another pending case.", "info"))
        trace.add("step1.status", f"Case {status.value}" + (f" on {end.isoformat()}" if end else "") + " — Section 479 not applicable.")
        return _finish(res, Status.NOT_APPLICABLE, trace, flags, needs)
    if not tl.in_custody_today:
        trace.add("step1.custody", "Not in custody in this case today — Section 479 not applicable.")
        return _finish(res, Status.NOT_APPLICABLE, trace, flags, needs)
    trace.add("step1.status", f"Case is pending ({status.value}) and the person is in custody → undertrial.", r479.ref)

    # ---- Charges → effective maxima
    active = case.active_charges(today)
    for c in case.charges:
        if c not in active:
            trace.add("charges", f"{c.label} dropped on {c.dropped_on.isoformat()} — ignored.")
    derivs: list[tuple[Charge, Derivation]] = []
    for ch in active:
        d = kb.effective_max(ch)
        if "LIABILITY_RULE_ONLY" in d.flags:
            trace.add("charges", f"{ch.label} is a liability provision, not a separate offence — no separate maximum.",
                      d.record.key if d.record else "")
            continue
        derivs.append((ch, d))
        if ch.confidence < ctx.confidence_threshold:
            needs.append(f"Charge {ch.label} (confidence {ch.confidence:.2f})")
        for code in d.flags:
            if code in ("NO_RECORD", "UNKNOWN_SECTION", "MAPPING_AMBIGUOUS_OR_MISSING"):
                needs.append(f"Legal data for {ch.label}: {code}")
            else:  # IPC_BNS_TRANSITION_MISMATCH | OFFENCE_DATE_UNKNOWN | UNVERIFIED_MAPPING
                flags.append(Flag(code, f"{ch.label}: " + " ".join(d.steps[:3])))
        needs += [f"Legal data record {u} is unverified" for u in d.unverified]
    if not derivs:
        trace.add("charges", "No offence charges on record.")
        flags.append(Flag("NO_CHARGES", "No charges recorded — cannot evaluate."))
        needs.append("Charges for this case")
        _add_findings(res, person, case, tl, None, kb, ctx, trace, flags, needs)
        return _finish(res, Status.REVIEW, trace, flags, needs)

    most_serious_ch, most = max(derivs, key=lambda cd: _severity_of_term(cd[1].term))
    for ch, d in derivs:
        trace.add("charges", " ".join(d.steps), *(r.ref for r in d.rules_used), d.record.key if d.record else "")
    res.max_term = str(most.term)
    if most_serious_ch.offence_date and most_serious_ch.offence_date < kb.rule("transition")["bns_commencement"]:
        flags.append(Flag("LEGACY_OFFENCE_479_APPLIED",
                          "Offence pre-dates BNS: IPC punishment used; Section 479 BNSS thresholds applied to this pending case.", "info"))

    # ---- Delay & counted detention
    res.accused_days = _accused_delay_days(case, tl, ctx, trace, flags, needs)
    res.counted_days = tl.custody_days - res.accused_days
    trace.add("section_479.counting", f"Custody {tl.custody_days} day(s) (inclusive counting) − accused-caused delay "
              f"{res.accused_days} day(s) = counted detention {res.counted_days} day(s).", r479.ref)

    # ---- First-time offender → fraction
    first = _prior_conviction_analysis(person, case, kb, trace, flags)
    frac: Fraction = r479.fraction("first_offender_fraction" if first else "general_fraction")
    res.first_time_offender = first
    res.fraction = f"{frac.numerator}/{frac.denominator}"

    def calc(term: Term) -> tuple[int | None, int | None, date | None]:
        if term.kind != "term":
            return None, None, None
        max_days = math.ceil(term.days)
        thr = math.ceil(term.days * frac)
        return max_days, thr, today - timedelta(days=res.counted_days - thr)

    for ch, d in derivs:
        md, thr, ef = calc(d.term)
        res.charge_calcs.append(ChargeCalc(ch.label, str(d.term), d.term.is_death_or_life, d.term.kind == "none",
                                           bool(d.record and d.record.special_law), md, thr, ef, d.steps,
                                           d.record.key if d.record else None, d.unverified))

    death_or_life = most.term.is_death_or_life
    fine_only = all(d.term.kind == "none" for _, d in derivs)
    special = [ch.label for ch, d in derivs if d.record and d.record.special_law]
    res.max_days, res.threshold_days, ef = calc(most.term)

    # ---- time-served, default bail, surety findings (run regardless of 479 outcome)
    _add_findings(res, person, case, tl, most, kb, ctx, trace, flags, needs)

    # ---- Step 2: death or life
    if death_or_life:
        trace.add("step2.exclusion", f"{most_serious_ch.label} is punishable with {most.term} → Section 479 does not apply. "
                  "Default bail and other routes still checked.", r479.ref)
        return _finish(res, Status.EXCLUDED_479, trace, flags, needs, gate=True)

    # ---- fine-only
    if fine_only:
        flags.append(Flag("UNUSUAL_DETENTION_FINE_ONLY",
                          f"All charges are punishable with fine only, yet the person has been detained {res.counted_days} day(s). "
                          "Detention is unusual — check for other cases or errors; seek immediate release.", "critical"))
        trace.add("step3.ceiling", "No imprisonment is provided for any charge — detention exceeds the maximum by definition.")
        return _finish(res, Status.REVIEW, trace, flags, needs)

    # ---- Step 3: absolute ceiling
    if res.counted_days >= res.max_days:
        trace.add("step3.ceiling", f"Counted detention {res.counted_days} ≥ maximum {res.max_days} day(s) ({most.term}) "
                  "→ no undertrial may be detained beyond the maximum. Applies even with multiple cases.", r479.ref)
        res.eligible_from_date = today - timedelta(days=res.counted_days - res.max_days)
        res.days_overdue = res.counted_days - res.max_days
        if special:
            flags.append(Flag("SPECIAL_LAW", f"Special-law charge(s) {', '.join(special)} — confirm the ceiling with the lawyer."))
        return _finish(res, Status.CRITICAL_MUST_RELEASE, trace, flags, needs)
    trace.add("step3.ceiling", f"Counted detention {res.counted_days} < maximum {res.max_days} day(s) ({most.term}).")

    # ---- threshold calc (shared by all remaining branches)
    trace.add("step5.threshold", f"{'First-time offender' if first else 'Not a first-time offender'} → {res.fraction} of "
              f"{res.max_days} day(s) = {res.threshold_days} day(s) (rounded up).", r479.ref)
    eligible_now = res.counted_days >= res.threshold_days
    if abs(res.counted_days - res.threshold_days) <= BORDERLINE_DAYS:
        flags.append(Flag("BORDERLINE", f"Within {BORDERLINE_DAYS} days of the threshold — day-counting conventions may matter."))
    case_wise = {
        "summary": (f"Case-wise reading: threshold {res.threshold_days} day(s) on the most serious offence "
                    f"({most_serious_ch.label}); counted {res.counted_days}."),
        "status": Status.ELIGIBLE.value if eligible_now else Status.NOT_YET.value,
        "eligible_from": ef.isoformat() if eligible_now else None,
        "projected_date": None if eligible_now else (today + timedelta(days=res.threshold_days - res.counted_days)).isoformat(),
    }
    bar = {
        "summary": ("479(2) bar reading: with more than one offence/case pending, release under 479(1) is barred; "
                    "only the absolute ceiling (maximum sentence) applies."),
        "status": Status.NOT_YET.value,
        "ceiling_date": (today + timedelta(days=res.max_days - res.counted_days)).isoformat(),
    }

    # ---- special law
    if special:
        flags.append(Flag("SPECIAL_LAW", f"Special-law charge(s) {', '.join(special)}: Section 479 interplay is not "
                          "auto-decided — lawyer review required.", "warning"))
        trace.add("special_law", "Special-law charge present → routed to lawyer review.")
        res.interpretations = {"case_wise": case_wise}
        return _finish(res, Status.REVIEW, trace, flags, needs)

    # ---- Step 4: multiple cases / offences
    distinct_offences = {d.record.key for _, d in derivs if d.record}
    if other_pending:
        res.interpretations = {"case_wise": case_wise, "bar_applies": bar}
        trace.add("step4.multiple", f"{len(other_pending) + 1} cases pending "
                  f"({', '.join([case.id] + [c.id for c in other_pending])}) → 479(2) may bar release; both readings shown.",
                  r479.ref)
        _set_dates(res, today, eligible_now, ef)
        return _finish(res, Status.REVIEW_MULTIPLE_CASES, trace, flags, needs)
    if len(distinct_offences) > 1:
        res.interpretations = {"case_wise": case_wise, "bar_applies": bar}
        flags.append(Flag("MULTIPLE_OFFENCES", f"{len(distinct_offences)} offences charged in one case — 479(2) "
                          "'more than one offence' reading is contested; per-charge calculations shown."))
        trace.add("step4.multiple", "More than one offence in this case → review with per-charge calculations.", r479.ref)
        _set_dates(res, today, eligible_now, ef)
        return _finish(res, Status.REVIEW, trace, flags, needs)

    # ---- lenient vs strict custody (custody in another case)
    if tl.lenient_custody_days is not None and tl.lenient_custody_days != tl.custody_days:
        lenient_counted = tl.lenient_custody_days - res.accused_days
        if (lenient_counted >= res.threshold_days) != eligible_now:
            res.interpretations = {"this_case_only": case_wise,
                                   "including_other_case_custody": {
                                       "summary": f"Counting custody in the other case: {lenient_counted} day(s).",
                                       "status": Status.ELIGIBLE.value}}
            trace.add("step6.counting", "Outcome depends on whether custody in another case counts → review.")
            _set_dates(res, today, eligible_now, ef)
            return _finish(res, Status.REVIEW, trace, flags, needs)

    # ---- Step 7: compare
    _set_dates(res, today, eligible_now, ef)
    if eligible_now:
        trace.add("step7.compare", f"Counted {res.counted_days} ≥ threshold {res.threshold_days} → eligible to apply since "
                  f"{res.eligible_from_date.isoformat()} ({res.days_overdue} day(s) overdue).", r479.ref)
        status_out = Status.ELIGIBLE
    else:
        trace.add("step7.compare", f"Counted {res.counted_days} < threshold {res.threshold_days} → projected eligibility "
                  f"{res.projected_date.isoformat()} if custody continues.", r479.ref)
        status_out = Status.NOT_YET
    return _finish(res, status_out, trace, flags, needs, gate=True)


def _as_pending(case: Case) -> Case:
    from dataclasses import replace
    return replace(case, status=CaseStatus.TRIAL, conviction_date=None)


def _set_dates(res: CaseResult, today: date, eligible_now: bool, ef: date | None) -> None:
    if eligible_now:
        res.eligible_from_date = ef
        res.days_overdue = res.counted_days - res.threshold_days
    else:
        res.projected_date = today + timedelta(days=res.threshold_days - res.counted_days)


def _add_findings(res: CaseResult, person: Person, case: Case, tl: Timeline, most: Derivation | None,
                  kb: KnowledgeBase, ctx: ComputeContext, trace: _Trace, flags: list[Flag], needs: list[str]) -> None:
    today = ctx.today
    # ---- default (statutory) bail
    db = kb.rule("default_bail")
    if case.first_remand_date is None:
        trace.add("default_bail", "First remand date unknown — default-bail window cannot be computed.", db.ref)
    elif most is None:
        trace.add("default_bail", "No charge data — default-bail period cannot be determined.", db.ref)
    else:
        long_ = most.term.is_death_or_life or (most.term.kind == "term" and most.term.months >= int(db["long_period_min_years"]) * 12)
        period = int(db["long_period_days" if long_ else "short_period_days"])
        if most.record and most.record.default_bail_period_days:
            period = max(period, int(most.record.default_bail_period_days))
            flags.append(Flag("SPECIAL_LAW_DEFAULT_BAIL_PERIOD", f"Special law may extend the investigation period "
                              f"(using {period} days) — verify.", "warning"))
        accrual = case.first_remand_date + timedelta(days=period)
        if not db.verified:
            needs.append(f"Legal rule 'default_bail' ({db.ref}) is unverified")
        base = (f"Default-bail period {period} days from first remand {case.first_remand_date.isoformat()} "
                f"→ right accrues on {accrual.isoformat()} if no charge sheet by then.")
        if case.charge_sheet_date is None:
            if today >= accrual:
                if case.default_bail_application_date and case.default_bail_application_date >= accrual:
                    res.findings.append(Finding("DEFAULT_BAIL_RIGHT_ASSERTED", base + f" Application filed "
                                                f"{case.default_bail_application_date.isoformat()} — press for release.",
                                                "critical", accrual, [db.ref]))
                else:  # findings only run for persons in custody
                    res.findings.append(Finding(Status.URGENT_DEFAULT_BAIL.value, base + " No charge sheet on record — "
                                                "apply for default bail BEFORE the charge sheet is filed.", "critical",
                                                accrual, [db.ref]))
            elif (accrual - today).days <= int(db["warn_days_before_deadline"]):
                res.findings.append(Finding("DEFAULT_BAIL_WINDOW_SOON", base + f" {(accrual - today).days} day(s) left.",
                                            "warning", accrual, [db.ref]))
            trace.add("default_bail", base, db.ref)
        elif case.charge_sheet_date < accrual:
            trace.add("default_bail", base + f" Charge sheet filed {case.charge_sheet_date.isoformat()} — within time.", db.ref)
        elif case.default_bail_application_date and accrual <= case.default_bail_application_date < case.charge_sheet_date:
            res.findings.append(Finding("DEFAULT_BAIL_RIGHT_ASSERTED", base + f" Applied {case.default_bail_application_date.isoformat()}"
                                        f" before the late charge sheet ({case.charge_sheet_date.isoformat()}) — right was "
                                        "availed and survives.", "critical", accrual, [db.ref]))
            trace.add("default_bail", base + " Right asserted before charge sheet.", db.ref)
        else:
            res.findings.append(Finding("DEFAULT_BAIL_RIGHT_LOST", base + f" Charge sheet filed late "
                                        f"({case.charge_sheet_date.isoformat()}) but no application was made before it — "
                                        "the indefeasible right was not availed and is lost.", "info", accrual, [db.ref]))
            trace.add("default_bail", base + " Right lost (not availed before the late charge sheet).", db.ref)

    # ---- bail granted but not released
    if case.bail_granted_date:
        sr = kb.rule("surety_not_furnished")
        check = case.bail_granted_date + timedelta(days=int(sr["flag_after_days"]))
        if check <= today and tl.in_custody_on(check):
            days = (today - case.bail_granted_date).days
            res.findings.append(Finding(Status.CRITICAL_BAIL_NOT_FURNISHED.value,
                                        f"Bail granted on {case.bail_granted_date.isoformat()} but still in custody {days} day(s) "
                                        "later (surety/bond not furnished). This custody still counts. Refer to the poor-prisoner "
                                        "support scheme and seek modification of bail conditions.", "critical",
                                        case.bail_granted_date, [sr.ref]))
            trace.add("surety", f"Bail granted {case.bail_granted_date.isoformat()}; still detained after "
                      f"{sr['flag_after_days']} days → flagged.", sr.ref)

    # ---- time served vs likely sentence
    rec = most.record if most else None
    if rec and rec.min_imprisonment and rec.min_imprisonment.kind == "term" and res.counted_days >= math.ceil(rec.min_imprisonment.days):
        res.findings.append(Finding("TIME_SERVED_EXCEEDS_MINIMUM", f"Counted detention ({res.counted_days} days) already exceeds "
                                    f"the minimum sentence ({rec.min_imprisonment}) — consider plea bargaining / early disposal.",
                                    "warning", None, [rec.key]))
    elif most and most.term.kind == "term" and res.counted_days * 2 >= math.ceil(most.term.days):
        res.findings.append(Finding("TIME_SERVED_SUBSTANTIAL", f"Counted detention ({res.counted_days} days) is at least half "
                                    f"the maximum ({most.term}) — time served may exceed a likely sentence; consider plea "
                                    "bargaining / early disposal.", "info"))


def _finish(res: CaseResult, status: Status, trace: _Trace, flags: list[Flag], needs: list[str], gate: bool = False) -> CaseResult:
    needs = list(dict.fromkeys(needs))
    if gate and needs:
        trace.add("step9.confidence_gate", f"{len(needs)} input(s) are low-confidence or unverified → downgraded from "
                  f"{status.value} to REVIEW. Check: " + "; ".join(needs))
        flags.append(Flag("DOWNGRADED_TO_REVIEW", f"Would be {status.value}; downgraded pending verification."))
        res.interpretations.setdefault("if_inputs_confirmed", {"status": status.value})
        status = Status.REVIEW
    elif needs and status in (Status.CRITICAL_MUST_RELEASE, Status.CRITICAL_ACQUITTED_DETAINED):
        flags.append(Flag("CRITICAL_NEEDS_VERIFICATION", "Critical result kept visible (liberty first) but some inputs "
                          "need verification: " + "; ".join(needs), "warning"))
    trace.add("step8.note", "Eligibility means eligible to APPLY; the court may order continued detention for recorded reasons.")
    res.status = status
    res.trace = trace.steps
    res.flags = flags
    res.needs_verification = needs
    res.confidence = 1.0 if not needs else 0.5
    return res


# ---------------------------------------------------------------- person

def evaluate_person(person: Person, kb: KnowledgeBase, ctx: ComputeContext) -> PersonResult:
    pending = [c for c in person.cases if c.status.is_pending or
               (c.status == CaseStatus.CONVICTED and any(cv.case_id == c.id and cv.status == ConvictionStatus.SET_ASIDE
                                                         for cv in person.convictions))]
    results = []
    for case in person.cases:
        others = [c for c in pending if c.id != case.id]
        results.append(evaluate_case(person, case, kb, ctx, others))
    flags: list[Flag] = []
    overall = min((r.urgency for r in results), key=urgency_rank) if results else Status.NOT_APPLICABLE.value
    if not results:
        flags.append(Flag("NO_CASES", "No cases linked to this person."))
    confidence = min((r.confidence for r in results), default=1.0)
    return PersonResult(person.id, overall, results, RULE_VERSION, kb.version,
                        ctx.computed_at or datetime.now(timezone.utc), flags, confidence)
