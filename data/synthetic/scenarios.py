"""~1,000 SYNTHETIC test scenarios with an independent oracle — NO real prisoner data.

Each scenario is a person in the same format as generate.py (so it is loaded through the real ORM, the delay
classifier and document ingestion), plus:

  tags     categories it exercises (eligible, leap_year, default_bail_late_cs, ...)
  scope    lawyer / jail / district it belongs to (for authorization tests)
  oracle   what the result MUST be, computed HERE from the constructed facts with plain set arithmetic
           (custody days are a set of calendar dates; accused-delay days are a set; thresholds come from the
           statutory fraction of the maximum). The oracle never calls the engine.

    python data/synthetic/scenarios.py --today 2026-09-30 --out data/synthetic/out/scenarios.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

ONE = timedelta(days=1)
BNS_START = date(2024, 7, 1)

DISTRICTS = [("Bengaluru Urban", "Central Prison Parappana Agrahara", "Chief Judicial Magistrate, Bengaluru"),
             ("Mysuru", "Central Prison Mysuru", "Principal Civil Judge & JMFC, Mysuru"),
             ("Kalaburagi", "Central Prison Kalaburagi", "Chief Judicial Magistrate, Kalaburagi")]
# maximum (months) → (IPC section, BNS section) with exactly that maximum in data/legal
BY_MONTHS = {12: ("323", "115(2)"), 24: ("504", "352"), 36: ("379", "303(2)"), 60: ("354", "316(2)"),
             84: ("420", "318(4)"), 120: ("392", "309(4)")}
DEATH_OR_LIFE = [("IPC", "302"), ("IPC", "307"), ("BNS", "103(1)"), ("BNS", "109(1)")]
SPECIAL = [("NDPS", "20(b)(ii)(A)"), ("POCSO", "12"), ("ARMS", "25(1B)(a)"), ("SCST", "3(1)(r)")]
FIRST_NAMES = ["Arun", "Bharath", "Chandru", "Dinesh", "Eshwar", "Ganesh", "Hemanth", "Irfan", "Jagadish", "Kiran",
               "Lokesh", "Mahadev", "Naveen", "Omkar", "Pradeep", "Raghavendra", "Sandeep", "Tejas", "Umesh", "Vinay",
               "Yashwanth", "Zameer", "Anitha", "Bhavya", "Chaitra", "Deepa", "Geetha", "Hema", "Jyothi", "Kusuma"]
SURNAMES = ["Gowda", "Naik", "Shetty", "Rao", "Patil", "Hegde", "Kumar", "Reddy", "Khan", "Pasha", "Achar", "Poojary",
            "Nayak", "Kulkarni", "Desai", "Bhat", "M", "S", "R", "K"]
FATHERS = ["Ramaiah", "Krishnappa", "Hanumanthappa", "Abdul Rahim", "Siddappa", "Nagaraj", "Channabasappa", "Mallesh",
           "Govindappa", "Venkataramanappa", "Shivalingaiah", "Yusuf Khan", "Basappa", "Thimmaiah"]
REASON = {  # canonical order-sheet phrasings the delay classifier labels with high confidence
    "accused": "Adjourned at the request of the accused counsel.",
    "prosecution": "PP sought time to secure witnesses.",
    "court": "Presiding Officer on leave.",
    "both": "Both sides sought time.",
    "other": "Lawyers' boycott; no work.",
    "unknown": "Adjourned.",
    "accused_low": "Accused ill, admitted to hospital; medical certificate filed.",
    "jail_non_production": "Accused not produced by jail authorities. Escort not available.",
}


def span(a: date, b: date) -> set[date]:
    return {a + timedelta(days=k) for k in range((b - a).days + 1)} if b >= a else set()


def max_days(months: int) -> int:
    return math.ceil(Fraction(months * 36525, 1200))


def threshold(months: int, first_time: bool) -> int:
    return math.ceil(Fraction(months * 36525, 1200) * (Fraction(1, 3) if first_time else Fraction(1, 2)))


def nth_day(days: set[date], n: int) -> date | None:
    s = sorted(days)
    return s[n - 1] if 1 <= n <= len(s) else None


@dataclass
class Gen:
    today: date
    rng: random.Random
    people: list[dict] = field(default_factory=list)
    n: int = 0

    def ago(self, k: int) -> date:
        return self.today - timedelta(days=k)

    # ------------------------------------------------------------------ builders
    def person(self, tags: list[str], *, name: str | None = None, father: str | None | bool = True, dob: date | None | bool = True,
               gender: str = "male", district: int | None = None, scope: str | None = None, **extra) -> dict:
        self.n += 1
        sid = f"S{self.n:04d}"
        d_i = self.n % 3 if district is None else district
        dist, jail, court = DISTRICTS[d_i]
        if name is None:
            name = f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(SURNAMES)}"
        if father is True:
            father = self.rng.choice(FATHERS)
        if dob is True:
            dob = self.today - timedelta(days=self.rng.randint(19 * 365, 60 * 365))
        # authorization scope: lawyer A / lawyer B / unassigned, cycling (≈45/45/10 %)
        scope = scope or ("A" if self.n % 20 < 9 else "B" if self.n % 20 < 18 else "unassigned")
        p = {"truth_id": sid, "scenario": "test_scenario", "canonical_name": name, "relative_name": father or None,
             "relation": ("s/o" if gender == "male" else "d/o") if father else None, "gender": gender,
             "dob": dob.isoformat() if dob else None, "district": dist, "jail": jail, "court": court,
             "vulnerability": ["woman"] if gender == "female" else [], "expected_status": None,
             "cases": [], "custody_events": [], "convictions": [], "documents": [], "tags": tags, "scope": scope,
             "oracle": {}, **extra}
        self.people.append(p)
        return p

    def case(self, p: dict, ref: str, charges: list[tuple[str, str]], *, offence: date, status: str = "trial",
             remand: date | None = None, cs: date | None = None, app: date | None = None, bail: date | None = None,
             acquittal: date | None = None, conviction: date | None = None, charge_conf: float = 0.95,
             case_number: str | None = None, cnr: str | None = None) -> dict:
        k = len(self.people) * 10 + len(p["cases"])
        c = {"ref": ref, "case_number": case_number or f"CC {k}/{offence.year}",
             "cnr": cnr or f"KATS{k:08d}{offence.year}"[:32], "fir_number": f"{k % 900 + 1}/{offence.year}",
             "court": p["court"], "district": p["district"], "state": "Karnataka", "police_station": "Test PS",
             "status": status, "offence_date": offence.isoformat(), "fir_date": offence.isoformat(),
             "first_remand_date": remand.isoformat() if remand else None,
             "charge_sheet_date": cs.isoformat() if cs else None,
             "default_bail_application_date": app.isoformat() if app else None,
             "bail_granted_date": bail.isoformat() if bail else None,
             "acquittal_date": acquittal.isoformat() if acquittal else None,
             "conviction_date": conviction.isoformat() if conviction else None,
             "charges": [{"act": a, "section": s, "modifier": None, "offence_date": offence.isoformat(),
                          "confidence": charge_conf} for a, s in charges],
             "hearings": []}
        p["cases"].append(c)
        return c

    def custody(self, p: dict, type_: str, start: date, end: date | None = None, case: dict | None = None, *,
                primary: bool = True, confidence: float = 0.95, jail: str | None = None) -> None:
        p["custody_events"].append({"type": type_, "start": start.isoformat(), "end": end.isoformat() if end else None,
                                    "case_ref": case["ref"] if case else None, "jail": jail or p["jail"],
                                    "confidence": confidence, "is_primary_source": primary,
                                    "doc_type": "arrest_memo" if type_ == "arrest" else "remand_order"})

    def hearing(self, c: dict, d: date, nxt: date | None, kind: str, *, reviewed: str | None = None) -> None:
        h = {"date": d.isoformat(), "next_date": nxt.isoformat() if nxt else None, "reason_text": REASON[kind]}
        if reviewed:
            h["attribution"], h["verified"] = reviewed, True
        c["hearings"].append(h)

    @staticmethod
    def law(offence: date, months: int) -> tuple[str, str]:
        ipc, bns = BY_MONTHS[months]
        return ("IPC", ipc) if offence < BNS_START else ("BNS", bns)

    def expect(self, p: dict, *, status: str | None = None, status_in: list[str] | None = None,
               custody: set[date] | None = None, accused: set[date] | None = None, months: int | None = None,
               first_time: bool = True, findings: list[str] = (), no_findings: list[str] = (), flags: list[str] = (),
               urgency: str | None = None, in_custody: bool = True) -> None:
        """Fill the oracle. With custody/accused/months given, the numbers AND the status are derived here."""
        o = p["oracle"]
        if custody is not None:
            acc = (accused or set()) & custody
            counted = len(custody) - len(acc)
            o.update(custody_days=len(custody), accused_days=len(acc), counted_days=counted)
            if months is not None:
                mx, thr = max_days(months), threshold(months, first_time)
                o.update(max_days=mx, threshold_days=thr)
                countable = custody - acc
                if not in_custody:
                    derived = "NOT_APPLICABLE"
                elif counted >= mx:
                    derived = "CRITICAL_MUST_RELEASE"
                    o.update(eligible_from=nth_day(countable, mx).isoformat(), days_overdue=counted - mx)
                elif counted >= thr:
                    derived = "ELIGIBLE"
                    o.update(eligible_from=nth_day(countable, thr).isoformat(), days_overdue=counted - thr)
                else:
                    derived = "NOT_YET"
                    o.update(projected=(self.today + timedelta(days=thr - counted)).isoformat())
                if status is None and status_in is None:
                    status = derived
        if status:
            o["status"] = status
        if status_in:
            o["status_in"] = status_in
        if urgency:
            o["urgency"] = urgency
        o["findings"] = list(findings)
        o["no_findings"] = list(no_findings)
        o["flags"] = list(flags)
        p["expected_status"] = status


# ====================================================================== families

def f1_threshold_grid(g: Gen) -> None:
    """Custody vs threshold and maximum, exact boundaries, first-time vs repeat, with/without accused delay."""
    for months in (12, 24, 36, 60, 84, 120):
        for first in (True, False):
            thr, mx = threshold(months, first), max_days(months)
            targets = {"thr-200": thr - 200, "thr-30": thr - 30, "thr-1": thr - 1, "thr": thr, "thr+1": thr + 1,
                       "thr+30": thr + 30, "max-1": mx - 1, "max": mx, "max+1": mx + 1}
            for label, counted in targets.items():
                if counted < 1 or (label.startswith("thr+") and counted >= mx):
                    continue
                for k in (0, 15):
                    arrest = g.ago(counted + k - 1)
                    offence = arrest - 2 * ONE
                    tags = ["threshold_grid", f"boundary_{label}", "first_time" if first else "repeat_offender",
                            f"max_{months}m", "accused_delay" if k else "no_delay"]
                    tags.append({"thr-200": "not_eligible", "thr-30": "approaching", "thr-1": "not_eligible"}.get(
                        label, "eligible" if label.startswith("thr") else "critical_beyond_max" if label != "max-1" else "eligible"))
                    if arrest.year < 2019:
                        tags.append("old_case")
                    if (g.today - arrest).days < 120:
                        tags.append("recent_case")
                    p = g.person(tags)
                    remand = arrest + ONE
                    cs = remand + 30 * ONE if remand + 30 * ONE < g.today else None
                    c = g.case(p, "c1", [g.law(offence, months)], offence=offence, remand=remand, cs=cs,
                               status="trial" if cs else "investigation")
                    g.custody(p, "arrest", arrest, case=c)
                    g.custody(p, "judicial_custody", remand, None, case=c)
                    acc: set[date] = set()
                    if k:
                        h0 = arrest + 3 * ONE
                        g.hearing(c, h0, h0 + k * ONE, "accused")
                        acc = span(h0, h0 + (k - 1) * ONE)
                        if h0 + (k + 20) * ONE < g.today:
                            g.hearing(c, h0 + k * ONE, h0 + (k + 20) * ONE, "prosecution")
                    if not first:
                        p["convictions"].append({"case_ref": "prior-1", "date": (arrest - 900 * ONE).isoformat(),
                                                 "status": "final", "offence": "IPC 379"})
                    custody = span(arrest, g.today)
                    # a short investigation that has run past 60 days without a charge sheet also triggers default bail
                    findings = ["URGENT_DEFAULT_BAIL"] if cs is None and (g.today - remand).days >= 60 else []
                    g.expect(p, custody=custody, accused=acc, months=months, first_time=first, findings=findings,
                             no_findings=[] if findings else ["URGENT_DEFAULT_BAIL"])


def f2_custody_shapes(g: Gen) -> None:
    """Bail, absconding, release/re-arrest, transfers, duplicates, overlaps, conflicting arrests, dates."""
    rng = g.rng
    for i in range(14):
        months = rng.choice([36, 60, 84])
        # --- a) bail in the middle, then re-arrest (custody resumes)
        a = g.ago(rng.randint(500, 1400)); b = a + rng.randint(30, 200) * ONE; c_ = b + rng.randint(20, 150) * ONE
        p = g.person(["bail_period", "re_arrest", "custody_resumed"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 40 * ONE)
        g.custody(p, "judicial_custody", a, b, case=c); g.custody(p, "on_bail", b + ONE, c_ - ONE, case=c)
        g.custody(p, "re_arrest", c_, None, case=c)
        g.expect(p, custody=span(a, b) | span(c_, g.today), months=months)
        # --- b) absconding inside an open custody period
        a = g.ago(rng.randint(400, 1300)); x = a + rng.randint(20, 100) * ONE; y = x + rng.randint(5, 60) * ONE
        p = g.person(["absconding"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 40 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c); g.custody(p, "absconding", x, y, case=c)
        g.expect(p, custody=span(a, g.today) - span(x, y), months=months)
        # --- c) release recorded → not in custody
        a = g.ago(rng.randint(300, 900)); b = a + rng.randint(10, 200) * ONE
        p = g.person(["release_recorded"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 40 * ONE)
        g.custody(p, "judicial_custody", a, b, case=c); g.custody(p, "released", b, None, case=c)
        g.expect(p, custody=span(a, b), months=months, in_custody=False)
        # --- d) arrest → released → re-arrested (starter events only)
        a = g.ago(rng.randint(600, 1400)); b = a + rng.randint(30, 200) * ONE; c_ = b + rng.randint(30, 200) * ONE
        p = g.person(["re_arrest", "release_recorded"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a + ONE, cs=a + 40 * ONE)
        g.custody(p, "arrest", a, case=c); g.custody(p, "released", b, case=c); g.custody(p, "re_arrest", c_, case=c)
        g.expect(p, custody=span(a, b) | span(c_, g.today), months=months)
        # --- e) transfer between jails (adjacent and one-day overlap) — no gap, no double count
        a = g.ago(rng.randint(300, 1200)); b = a + rng.randint(10, 250) * ONE
        p = g.person(["custody_transfer", "jail_specific"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 40 * ONE)
        g.custody(p, "judicial_custody", a, b, case=c, jail=DISTRICTS[0][1])
        g.custody(p, "transfer", b + (ONE if i % 2 else 0 * ONE), None, case=c, jail=DISTRICTS[1][1])
        g.expect(p, custody=span(a, g.today), months=months)
        # --- f) duplicate + overlapping custody records
        a = g.ago(rng.randint(300, 1200))
        p = g.person(["duplicate_custody_records", "overlapping_custody"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a + ONE, cs=a + 40 * ONE)
        g.custody(p, "police_custody", a, a + 2 * ONE, case=c)
        g.custody(p, "judicial_custody", a + ONE, None, case=c); g.custody(p, "judicial_custody", a + ONE, None, case=c)
        g.expect(p, custody=span(a, g.today), months=months)
        # --- g) conflicting arrest dates: primary vs secondary (primary wins, flagged, no review)
        a = g.ago(rng.randint(300, 1200))
        p = g.person(["conflicting_arrest_dates", "secondary_source"])
        c = g.case(p, "c1", [g.law(a - 9 * ONE, months)], offence=a - 9 * ONE, remand=a + ONE, cs=a + 40 * ONE)
        g.custody(p, "arrest", a, case=c); g.custody(p, "arrest", a - 5 * ONE, case=c, primary=False)
        g.custody(p, "judicial_custody", a + ONE, None, case=c)
        g.expect(p, custody=span(a, g.today), months=months, flags=["CONFLICTING_ARREST_DATES"])
        # --- h) conflicting arrest dates in two PRIMARY documents → review (or critical kept visible)
        a = g.ago(rng.randint(300, 1200))
        p = g.person(["conflicting_arrest_dates", "contradictory_dates", "review"])
        c = g.case(p, "c1", [g.law(a - 9 * ONE, months)], offence=a - 9 * ONE, remand=a + ONE, cs=a + 40 * ONE)
        g.custody(p, "arrest", a, case=c); g.custody(p, "arrest", a - 5 * ONE, case=c)
        g.custody(p, "judicial_custody", a + ONE, None, case=c)
        cust = span(a - 5 * ONE, g.today)
        g.expect(p, custody=cust, months=months, flags=["CONFLICTING_ARREST_DATES"])
        crit = len(cust) >= max_days(months)
        p["oracle"]["status"] = "CRITICAL_MUST_RELEASE" if crit else "REVIEW"
        p["oracle"].pop("eligible_from", None) if not crit else None
    # --- fixed calendar edge cases (absolute dates)
    fixed = [
        (["leap_year", "leap_day", "release_recorded"], date(2024, 2, 27), date(2024, 3, 2), True),
        (["leap_year", "leap_day"], date(2024, 2, 28), None, False),
        (["leap_year", "leap_day_start"], date(2024, 2, 29), None, False),
        (["crosses_31_december", "crosses_1_january", "year_boundary", "release_recorded"], date(2023, 12, 30), date(2024, 1, 2), True),
        (["crosses_31_december", "crosses_1_january", "year_boundary", "release_recorded"], date(2025, 12, 31), date(2026, 1, 1), True),
        (["month_boundary", "release_recorded"], date(2025, 1, 31), date(2025, 2, 1), True),
        (["month_boundary", "release_recorded"], date(2025, 4, 30), date(2025, 5, 31), True),
        (["same_start_end_date", "one_day_custody", "release_recorded"], date(2025, 6, 10), date(2025, 6, 10), True),
        (["year_boundary", "crosses_31_december"], date(2025, 12, 31), None, False),
        (["very_long_custody", "old_case"], date(2014, 5, 5), None, False),
        (["very_long_custody", "old_case", "leap_year"], date(2016, 2, 29), None, False),
        (["custody_starts_today", "one_day_custody", "very_short_custody", "recent_case"], g.today, None, False),
        (["very_short_custody", "recent_case"], g.today - ONE, None, False),
    ]
    for tags, start, end, released in fixed:
        for months in (36, 84):
            p = g.person(tags)
            c = g.case(p, "c1", [g.law(start - ONE, months)], offence=start - ONE, remand=start,
                       cs=start + 40 * ONE if start + 40 * ONE < g.today else None,
                       status="trial" if start + 40 * ONE < g.today else "investigation")
            g.custody(p, "judicial_custody", start, end, case=c)
            if released:
                g.custody(p, "released", end, None, case=c)
            cust = span(start, end if end else g.today)
            g.expect(p, custody=cust, months=months, in_custody=not released)
    # --- no custody at all / future / reversed / invalid exclusion
    for i in range(6):
        months = 36
        p = g.person(["zero_custody", "no_custody_records"])
        g.case(p, "c1", [g.law(g.ago(100), months)], offence=g.ago(100), remand=None, cs=g.ago(50))
        g.expect(p, status="NOT_APPLICABLE", custody=set())
        p = g.person(["future_custody_date", "impossible_date", "review"])
        c = g.case(p, "c1", [g.law(g.ago(30), months)], offence=g.ago(30), remand=None, status="investigation")
        g.custody(p, "judicial_custody", g.today + (i + 3) * ONE, None, case=c)
        g.expect(p, status="REVIEW", custody=set(), flags=["FUTURE_START_DATE"])
        a = g.ago(400 + i * 17)
        p = g.person(["reversed_date_range", "impossible_date", "review"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 30 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.custody(p, "police_custody", a + 60 * ONE, a + 10 * ONE, case=c)  # ends before it starts
        cust = span(a, g.today)
        g.expect(p, custody=cust, months=months, flags=["END_BEFORE_START"])
        p["oracle"]["status"] = "CRITICAL_MUST_RELEASE" if len(cust) >= max_days(months) else "REVIEW"
        p["oracle"].pop("eligible_from", None); p["oracle"].pop("projected", None); p["oracle"].pop("days_overdue", None)
        a = g.ago(300 + i * 11)
        p = g.person(["reversed_bail_range", "impossible_date", "review"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 30 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.custody(p, "on_bail", a + 90 * ONE, a + 40 * ONE, case=c)  # reversed: must NOT be subtracted or double counted
        cust = span(a, g.today)
        g.expect(p, custody=cust, months=months, flags=["INVALID_EXCLUSION_RANGE"])
        p["oracle"]["status"] = "CRITICAL_MUST_RELEASE" if len(cust) >= max_days(months) else "REVIEW"
        p["oracle"].pop("eligible_from", None); p["oracle"].pop("projected", None); p["oracle"].pop("days_overdue", None)


def f3_delays(g: Gen) -> None:
    """Every delay category, via the real classifier (order-sheet text) and via reviewer decisions."""
    rng = g.rng
    kinds = ["accused", "prosecution", "court", "both", "other", "unknown", "jail_non_production"]
    for rep in range(10):
        for kind in kinds:
            months = rng.choice([36, 60, 84])
            a = g.ago(rng.randint(350, 1100))
            p = g.person([f"delay_{kind}", "delay_attribution"] + (["no_delay"] if kind == "none" else []))
            c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 30 * ONE)
            g.custody(p, "judicial_custody", a, None, case=c)
            h0 = a + 40 * ONE
            k = rng.randint(10, 60)
            g.hearing(c, h0, h0 + k * ONE, kind)
            acc = span(h0, h0 + (k - 1) * ONE) if kind == "accused" else set()
            g.expect(p, custody=span(a, g.today), accused=acc, months=months,
                     flags=["DELAY_ATTRIBUTION_UNCERTAIN"] if kind in ("both", "unknown") else [])
        # no hearings at all
        a = g.ago(rng.randint(350, 1100))
        p = g.person(["no_hearings", "no_delay"])
        c = g.case(p, "c1", [g.law(a - ONE, 36)], offence=a - ONE, remand=a, cs=a + 30 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.expect(p, custody=span(a, g.today), months=36)
    for rep in range(6):
        months = 84
        a = g.ago(rng.randint(600, 1100))
        base = lambda tags: (g.person(tags),)  # noqa: E731
        # low-confidence accused (illness) → REVIEW unless a reviewer confirmed it
        p, = base(["delay_accused_low_confidence", "uncertain_attribution", "review"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 30 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.hearing(c, a + 50 * ONE, a + 80 * ONE, "accused_low")
        cust, acc = span(a, g.today), span(a + 50 * ONE, a + 79 * ONE)
        g.expect(p, custody=cust, accused=acc, months=months)
        crit = len(cust) - 30 >= max_days(months)
        p["oracle"]["status"] = "CRITICAL_MUST_RELEASE" if crit else "REVIEW"
        for k_ in ("eligible_from", "projected", "days_overdue"):
            if not crit:
                p["oracle"].pop(k_, None)
        # same, but reviewer-confirmed → subtracted, no review
        p, = base(["delay_accused_reviewer_confirmed", "reviewer_case"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 30 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.hearing(c, a + 50 * ONE, a + 80 * ONE, "accused_low", reviewed="accused")
        g.expect(p, custody=span(a, g.today), accused=span(a + 50 * ONE, a + 79 * ONE), months=months)
        # duplicate accused hearing records + overlapping accused adjournments → each day once
        p, = base(["duplicate_hearings", "multiple_hearings_same_date", "overlapping_adjournments", "delay_accused"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 30 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.hearing(c, a + 50 * ONE, a + 90 * ONE, "accused", reviewed="accused")
        g.hearing(c, a + 50 * ONE, a + 90 * ONE, "accused", reviewed="accused")
        g.hearing(c, a + 70 * ONE, a + 110 * ONE, "accused", reviewed="accused")
        g.expect(p, custody=span(a, g.today), accused=span(a + 50 * ONE, a + 109 * ONE), months=months,
                 flags=["DUPLICATE_HEARING"])
        # contradictory attributions for the same hearing date → review
        p, = base(["contradictory_hearing_information", "multiple_hearings_same_date", "review"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 30 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.hearing(c, a + 50 * ONE, a + 70 * ONE, "accused", reviewed="accused")
        g.hearing(c, a + 50 * ONE, a + 71 * ONE, "prosecution", reviewed="prosecution")
        cust = span(a, g.today)
        g.expect(p, custody=cust, accused=span(a + 50 * ONE, a + 69 * ONE), months=months,
                 flags=["HEARING_ATTRIBUTION_CONFLICT"])
        crit = len(cust) - 20 >= max_days(months)
        p["oracle"]["status"] = "CRITICAL_MUST_RELEASE" if crit else "REVIEW"
        if not crit:
            for k_ in ("eligible_from", "projected", "days_overdue"):
                p["oracle"].pop(k_, None)
        # hearing whose next date is before it, and accused hearing with no next date, and a future hearing
        p, = base(["missing_hearing_dates", "invalid_hearing_dates", "future_hearing_date"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 30 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.hearing(c, a + 50 * ONE, a + 40 * ONE, "prosecution", reviewed="prosecution")  # reversed, not accused
        g.hearing(c, a + 60 * ONE, None, "accused", reviewed="accused")                  # no next date
        g.hearing(c, g.today + 20 * ONE, g.today + 50 * ONE, "accused", reviewed="accused")  # scheduled, future
        g.expect(p, custody=span(a, g.today), months=months,
                 flags=["HEARING_DATES_INVALID", "ACCUSED_DELAY_NO_NEXT_DATE"])
    # unknown delays that would flip the result → explicit warning (not subtracted, per D-008)
    for rep in range(8):
        months, first = 36, True
        thr = threshold(months, first)
        counted = thr + 5
        a = g.ago(counted - 1)
        p = g.person(["delay_unknown", "uncertain_attribution", "unknown_delay_affects_result", "eligible"])
        c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 30 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.hearing(c, a + 40 * ONE, a + 70 * ONE, "unknown" if rep % 2 else "both")
        g.expect(p, custody=span(a, g.today), months=months, flags=["DELAY_ATTRIBUTION_AFFECTS_RESULT"])


def f4_default_bail(g: Gen) -> None:
    rng = g.rng

    def db_case(tags, *, months=84, law=None, remand_ago, cs_ago=None, app_ago=None, status=None, findings=(),
                no_findings=(), urgency=None, remand_known=True):
        r = g.ago(remand_ago)
        p = g.person(["default_bail"] + tags)
        offence = r - 3 * ONE
        charges = [law] if law else [g.law(offence, months)]
        c = g.case(p, "c1", charges, offence=offence, remand=r if remand_known else None,
                   cs=g.ago(cs_ago) if cs_ago is not None else None, app=g.ago(app_ago) if app_ago is not None else None,
                   status="investigation" if cs_ago is None else "charge_sheet_filed")
        g.custody(p, "arrest", r - ONE, case=c)
        g.custody(p, "judicial_custody", r, None, case=c)
        g.expect(p, status_in=status or None, findings=list(findings), no_findings=list(no_findings), urgency=urgency,
                 custody=span(r - ONE, g.today))
        return p

    for rep in range(8):
        j = rng.randint(0, 5)
        # 60-day offences (7-year maximum)
        db_case(["default_bail_not_yet", "no_default_bail"], remand_ago=20 + j, no_findings=["URGENT_DEFAULT_BAIL", "DEFAULT_BAIL_WINDOW_SOON"])
        db_case(["default_bail_window_soon"], remand_ago=54 + (j % 6), findings=["DEFAULT_BAIL_WINDOW_SOON"])
        db_case(["default_bail_exact_accrual_day"], remand_ago=60, findings=["URGENT_DEFAULT_BAIL"], urgency="URGENT_DEFAULT_BAIL")
        db_case(["default_bail_day_before_accrual"], remand_ago=59, findings=["DEFAULT_BAIL_WINDOW_SOON"], no_findings=["URGENT_DEFAULT_BAIL"])
        db_case(["default_bail_urgent", "no_charge_sheet"], remand_ago=61 + j * 7, findings=["URGENT_DEFAULT_BAIL"], urgency="URGENT_DEFAULT_BAIL")
        db_case(["default_bail_right_asserted", "application_pending"], remand_ago=80 + j, app_ago=5,
                findings=["DEFAULT_BAIL_RIGHT_ASSERTED"], no_findings=["URGENT_DEFAULT_BAIL"])
        db_case(["default_bail_premature_application", "no_charge_sheet"], remand_ago=80 + j, app_ago=70 + j,
                findings=["URGENT_DEFAULT_BAIL"])
        db_case(["default_bail_cs_within_time", "no_default_bail"], remand_ago=200 + j, cs_ago=200 + j - 50,
                no_findings=["URGENT_DEFAULT_BAIL", "DEFAULT_BAIL_RIGHT_LOST", "DEFAULT_BAIL_RIGHT_ASSERTED", "DEFAULT_BAIL_REVIEW"])
        db_case(["default_bail_cs_on_last_day", "no_default_bail"], remand_ago=200 + j, cs_ago=200 + j - 59,
                no_findings=["URGENT_DEFAULT_BAIL", "DEFAULT_BAIL_RIGHT_LOST"])
        db_case(["default_bail_cs_late_no_application", "right_not_invoked"], remand_ago=200 + j, cs_ago=200 + j - 75,
                findings=["DEFAULT_BAIL_RIGHT_LOST"], no_findings=["URGENT_DEFAULT_BAIL"])
        db_case(["default_bail_cs_late_on_accrual_day"], remand_ago=200 + j, cs_ago=200 + j - 60,
                findings=["DEFAULT_BAIL_RIGHT_LOST"])
        db_case(["default_bail_applied_before_late_cs", "right_invoked"], remand_ago=200 + j, cs_ago=200 + j - 90,
                app_ago=200 + j - 70, findings=["DEFAULT_BAIL_RIGHT_ASSERTED"])
        db_case(["default_bail_application_same_day_as_cs", "review"], remand_ago=200 + j, cs_ago=200 + j - 90,
                app_ago=200 + j - 90, findings=["DEFAULT_BAIL_REVIEW"], no_findings=["DEFAULT_BAIL_RIGHT_LOST", "DEFAULT_BAIL_RIGHT_ASSERTED"])
        db_case(["default_bail_premature_application_late_cs", "review"], remand_ago=200 + j, cs_ago=200 + j - 90,
                app_ago=200 + j - 30, findings=["DEFAULT_BAIL_REVIEW"], no_findings=["DEFAULT_BAIL_RIGHT_LOST"])
        db_case(["default_bail_cs_before_remand", "contradictory_dates", "review"], remand_ago=200 + j, cs_ago=210 + j,
                findings=["DEFAULT_BAIL_REVIEW"])
        db_case(["default_bail_missing_remand", "incomplete_records", "review"], remand_ago=40 + j, remand_known=False,
                findings=["DEFAULT_BAIL_REVIEW"])
        # 90-day offences (death/life) — Section 479 excluded, default bail still computed
        db_case(["default_bail_90_day", "death_or_life"], law=DEATH_OR_LIFE[j % 4], remand_ago=75,
                no_findings=["URGENT_DEFAULT_BAIL"], status=["EXCLUDED_479"])
        db_case(["default_bail_90_day", "death_or_life"], law=DEATH_OR_LIFE[j % 4], remand_ago=95 + j,
                findings=["URGENT_DEFAULT_BAIL"], status=["EXCLUDED_479"], urgency="URGENT_DEFAULT_BAIL")
        # exactly 10-year maximum: 60 vs 90 days contested → review between day 60 and day 90
        db_case(["default_bail_10_year_boundary", "review"], months=120, remand_ago=70 + j,
                findings=["DEFAULT_BAIL_REVIEW"], no_findings=["URGENT_DEFAULT_BAIL"])
        db_case(["default_bail_10_year_boundary"], months=120, remand_ago=95 + j, findings=["URGENT_DEFAULT_BAIL"])
    # bail granted but surety not furnished
    for rep in range(6):
        a = g.ago(300 + rep * 13)
        for bail_ago, found in ((30, True), (3, False)):
            p = g.person(["bail_not_furnished" if found else "bail_granted_recently", "bail_granted"])
            c = g.case(p, "c1", [g.law(a - ONE, 84)], offence=a - ONE, remand=a, cs=a + 30 * ONE, bail=g.ago(bail_ago))
            g.custody(p, "judicial_custody", a, None, case=c)
            g.expect(p, custody=span(a, g.today), months=84,
                     findings=["CRITICAL_BAIL_NOT_FURNISHED"] if found else [],
                     no_findings=[] if found else ["CRITICAL_BAIL_NOT_FURNISHED"])


def f5_outcomes(g: Gen) -> None:
    rng = g.rng
    for rep in range(10):
        a = g.ago(rng.randint(300, 900)); acq = g.ago(rng.randint(3, 40))
        p = g.person(["acquitted_still_in_custody", "critical"])
        c = g.case(p, "c1", [g.law(a - ONE, 36)], offence=a - ONE, remand=a, cs=a + 30 * ONE, status="acquitted", acquittal=acq)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.expect(p, status="CRITICAL_ACQUITTED_DETAINED", custody=span(a, g.today))
        p = g.person(["acquitted_released", "release_recorded"])
        c = g.case(p, "c1", [g.law(a - ONE, 36)], offence=a - ONE, remand=a, cs=a + 30 * ONE, status="acquitted", acquittal=acq)
        g.custody(p, "judicial_custody", a, acq, case=c); g.custody(p, "released", acq, case=c)
        g.expect(p, status="NOT_APPLICABLE", custody=span(a, acq))
        p = g.person(["convicted"])
        c = g.case(p, "c1", [g.law(a - ONE, 36)], offence=a - ONE, remand=a, cs=a + 30 * ONE, status="convicted", conviction=acq)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.expect(p, status="NOT_APPLICABLE", custody=span(a, acq))
        p = g.person(["discharged", "release_recorded"])
        c = g.case(p, "c1", [g.law(a - ONE, 36)], offence=a - ONE, remand=a, cs=a + 30 * ONE, status="discharged", acquittal=acq)
        g.custody(p, "judicial_custody", a, acq, case=c); g.custody(p, "released", acq, case=c)
        g.expect(p, status="NOT_APPLICABLE", custody=span(a, acq))
        p = g.person(["conviction_set_aside", "reassessed_as_undertrial"])
        c = g.case(p, "c1", [g.law(a - ONE, 36)], offence=a - ONE, remand=a, cs=a + 30 * ONE, status="convicted", conviction=acq)
        g.custody(p, "judicial_custody", a, None, case=c)
        p["convictions"].append({"case_ref": "c1-self", "date": acq.isoformat(), "status": "set_aside", "offence": "IPC 379"})
        p["oracle_fix_conviction_case"] = True  # the loader links this conviction to the case id
        g.expect(p, custody=span(a, g.today), months=36, flags=["CONVICTION_SET_ASIDE_REASSESS"])


def f6_legal(g: Gen) -> None:
    rng = g.rng
    for rep in range(8):
        a = g.ago(rng.randint(300, 1500))
        p = g.person(["death_or_life", "excluded_479"])
        c = g.case(p, "c1", [DEATH_OR_LIFE[rep % 4]], offence=a - ONE, remand=a, cs=a + 50 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.expect(p, status="EXCLUDED_479", custody=span(a, g.today))
        p = g.person(["special_law", "review"])
        c = g.case(p, "c1", [SPECIAL[rep % 4]], offence=a - ONE, remand=a, cs=a + 50 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.expect(p, status_in=["REVIEW", "CRITICAL_MUST_RELEASE"], custody=span(a, g.today), flags=["SPECIAL_LAW"])
        p = g.person(["missing_legal_data", "unknown_section", "review"])
        c = g.case(p, "c1", [("IPC", "999Z")], offence=a - ONE, remand=a, cs=a + 50 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.expect(p, status="REVIEW", custody=span(a, g.today), flags=["MISSING_LEGAL_DATA"])
        p = g.person(["multiple_offences", "review"])
        c = g.case(p, "c1", [g.law(a - ONE, 36), g.law(a - ONE, 84)], offence=a - ONE, remand=a, cs=a + 50 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.expect(p, status_in=["REVIEW", "CRITICAL_MUST_RELEASE"], custody=span(a, g.today))
        p = g.person(["multiple_cases", "review", "same_person_multiple_cases"])
        c1 = g.case(p, "c1", [g.law(a - ONE, 36)], offence=a - ONE, remand=a, cs=a + 50 * ONE)
        c2 = g.case(p, "c2", [g.law(a - 5 * ONE, 36)], offence=a - 5 * ONE, remand=a + 2 * ONE, cs=a + 60 * ONE)
        g.custody(p, "judicial_custody", a, None, case=None)
        g.expect(p, status_in=["REVIEW_MULTIPLE_CASES", "CRITICAL_MUST_RELEASE"], custody=span(a, g.today))
        p = g.person(["uncertain_extraction", "low_confidence_charge", "review"])
        c = g.case(p, "c1", [g.law(a - ONE, 84)], offence=a - ONE, remand=a, cs=a + 50 * ONE, charge_conf=0.55)
        g.custody(p, "judicial_custody", a, None, case=c)
        cust = span(a, g.today)
        g.expect(p, custody=cust, months=84)
        crit = len(cust) >= max_days(84)
        p["oracle"]["status"] = "CRITICAL_MUST_RELEASE" if crit else "REVIEW"
        if not crit:
            for k_ in ("eligible_from", "projected", "days_overdue"):
                p["oracle"].pop(k_, None)
        p = g.person(["no_charges", "incomplete_records", "review"])
        c = g.case(p, "c1", [], offence=a - ONE, remand=a, cs=a + 50 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.expect(p, status="REVIEW", custody=span(a, g.today), flags=["NO_CHARGES"])
        p = g.person(["low_confidence_custody_record", "uncertain_extraction", "review"])
        c = g.case(p, "c1", [g.law(a - ONE, 84)], offence=a - ONE, remand=a, cs=a + 50 * ONE)
        g.custody(p, "judicial_custody", a, None, case=c, confidence=0.5)
        cust = span(a, g.today)
        g.expect(p, custody=cust, months=84)
        crit = len(cust) >= max_days(84)
        p["oracle"]["status"] = "CRITICAL_MUST_RELEASE" if crit else "REVIEW"
        if not crit:
            for k_ in ("eligible_from", "projected", "days_overdue"):
                p["oracle"].pop(k_, None)
    # prior-conviction kinds → fraction
    for rep in range(6):
        for kind, first in (("final", False), ("under_appeal", False), ("set_aside", True), ("juvenile", True)):
            months = 84
            thr_first, thr_rep = threshold(months, True), threshold(months, False)
            counted = (thr_first + thr_rep) // 2  # eligible only as a first-time offender
            a = g.ago(counted - 1 + rep)
            p = g.person([f"prior_conviction_{kind}", "first_time" if first else "repeat_offender"])
            c = g.case(p, "c1", [g.law(a - ONE, months)], offence=a - ONE, remand=a, cs=a + 50 * ONE)
            g.custody(p, "judicial_custody", a, None, case=c)
            p["convictions"].append({"case_ref": "old", "date": (a - 1500 * ONE).isoformat(), "status": kind, "offence": "IPC 379"})
            g.expect(p, custody=span(a, g.today), months=months, first_time=first)


def f7_records(g: Gen) -> None:
    """Documents vs records, duplicates, incomplete personal data, long values."""
    rng = g.rng
    for rep in range(12):
        a = g.ago(rng.randint(300, 1000)); cs = a + 45 * ONE
        # consistent documents → no conflict
        p = g.person(["documents_consistent", "source_traceability"])
        c = g.case(p, "c1", [g.law(a - 2 * ONE, 84)], offence=a - 2 * ONE, remand=a, cs=cs)
        g.custody(p, "arrest", a - ONE, case=c); g.custody(p, "judicial_custody", a, None, case=c)
        p["documents"] += [_doc_remand(p, c, a), _doc_chargesheet(p, c, cs, a - 2 * ONE), _doc_arrest(p, c, a - ONE)]
        g.expect(p, custody=span(a - ONE, g.today), months=84)
        # charge-sheet document disagrees with the record → review
        p = g.person(["document_record_conflict", "contradictory_dates", "review"])
        c = g.case(p, "c1", [g.law(a - 2 * ONE, 84)], offence=a - 2 * ONE, remand=a, cs=cs)
        g.custody(p, "arrest", a - ONE, case=c); g.custody(p, "judicial_custody", a, None, case=c)
        p["documents"] += [_doc_chargesheet(p, c, cs + 20 * ONE, a - 2 * ONE)]
        _review_unless_critical(g, p, span(a - ONE, g.today), 84, flags=["DOCUMENT_RECORD_CONFLICT"])
        # arrest memo earlier than the custody record → custody may be under-counted → review
        p = g.person(["document_record_conflict", "contradictory_arrest_dates", "review"])
        c = g.case(p, "c1", [g.law(a - 9 * ONE, 84)], offence=a - 9 * ONE, remand=a, cs=cs)
        g.custody(p, "judicial_custody", a, None, case=c)
        p["documents"] += [_doc_arrest(p, c, a - 6 * ONE)]
        _review_unless_critical(g, p, span(a, g.today), 84, flags=["DOCUMENT_RECORD_CONFLICT"])
        # the same document uploaded twice → stored once
        p = g.person(["duplicate_documents"])
        c = g.case(p, "c1", [g.law(a - 2 * ONE, 84)], offence=a - 2 * ONE, remand=a, cs=cs)
        g.custody(p, "judicial_custody", a, None, case=c)
        d = _doc_remand(p, c, a)
        p["documents"] += [d, dict(d)]
        p["oracle_documents"] = 1
        g.expect(p, custody=span(a, g.today), months=84)
        # missing documents entirely
        p = g.person(["missing_documents", "no_documents"])
        c = g.case(p, "c1", [g.law(a - 2 * ONE, 84)], offence=a - 2 * ONE, remand=a, cs=cs)
        g.custody(p, "judicial_custody", a, None, case=c)
        p["oracle_documents"] = 0
        g.expect(p, custody=span(a, g.today), months=84)
        # incomplete personal data
        p = g.person(["missing_father_name", "missing_dob", "missing_age", "missing_address", "incomplete_records"],
                     father=None, dob=None)
        c = g.case(p, "c1", [g.law(a - 2 * ONE, 36)], offence=a - 2 * ONE, remand=a, cs=cs)
        g.custody(p, "judicial_custody", a, None, case=c)
        g.expect(p, custody=span(a, g.today), months=36)
        # very long name and case number
        long_name = "Venkata Subramanya Lakshmi Narasimha Sheshadri Srinivasa Raghavendra Prasanna " * 2
        p = g.person(["very_long_prisoner_name", "very_long_case_number"], name=long_name.strip())
        c = g.case(p, "c1", [g.law(a - 2 * ONE, 36)], offence=a - 2 * ONE, remand=a, cs=cs,
                   case_number="Spl. C.C. No. " + "/".join(str(1000 + k) for k in range(40)))
        g.custody(p, "judicial_custody", a, None, case=c)
        g.expect(p, custody=span(a, g.today), months=36)


def _review_unless_critical(g: Gen, p: dict, cust: set[date], months: int, flags: list[str]) -> None:
    g.expect(p, custody=cust, months=months, flags=flags)
    if len(cust) >= max_days(months):
        p["oracle"]["status"] = "CRITICAL_MUST_RELEASE"
    else:
        p["oracle"]["status"] = "REVIEW"
        for k_ in ("eligible_from", "projected", "days_overdue"):
            p["oracle"].pop(k_, None)


def _doc_remand(p: dict, c: dict, remand: date) -> dict:
    text = (f"ORDER ON REMAND\nIn the Court of {c['court']}\nCrime No. {c['fir_number']} of {c['police_station']}\n"
            f"Accused: {p['canonical_name']}\nAccused produced before Magistrate on: {remand.strftime('%d/%m/%Y')} at 11:00 hrs\n"
            f"Remanded to judicial custody from {remand.strftime('%d/%m/%Y')}\nReasons: Investigation pending.\n")
    return {"doc_type": "remand_order", "language": "en", "text": text, "case_ref": c["ref"]}


def _doc_chargesheet(p: dict, c: dict, filed: date, offence: date) -> dict:
    secs = ", ".join(f"{x['section']} {x['act']}" for x in c["charges"])
    text = (f"FINAL REPORT (CHARGE SHEET) u/s 193 BNSS\nFIR No.: {c['fir_number']}  Police Station: {c['police_station']}\n"
            f"Date of filing: {filed.strftime('%d/%m/%Y')}\nAccused: {p['canonical_name']}\n"
            f"Date of offence: {offence.strftime('%d/%m/%Y')}\nSections: {secs}\nWitnesses cited: CW-1, CW-2\n")
    return {"doc_type": "charge_sheet", "language": "en", "text": text, "case_ref": c["ref"]}


def _doc_arrest(p: dict, c: dict, arrest: date) -> dict:
    text = (f"ARREST MEMO\nFIR No.: {c['fir_number']}   Police Station: {c['police_station']}\n"
            f"Name of arrested person: {p['canonical_name']}\nDate and time of arrest: {arrest.strftime('%d/%m/%Y')} 10:00 hrs\n"
            "Grounds of arrest communicated: Yes\nRelative/friend informed: Yes\nMemo attested by witness: Yes\n"
            "Medical examination: Done\n")
    return {"doc_type": "arrest_memo", "language": "en", "text": text, "case_ref": c["ref"]}


def f8_identity(g: Gen) -> None:
    """Same person under variant names vs different people with similar names. Each record is a separate
    prisoner; the harness runs the identity scan and checks what is proposed — nothing may be auto-merged."""
    rng = g.rng
    groups = [
        ("Ravi Shankar", ["RAVI SHANKAR", "Ravishankar", "Ravi Shankar @ Ravi"], "Ramaiah", "Ramayya"),
        ("Mohammed Irfan", ["Md. Irfan", "Mohd Irfan", "Mohammad Irfan"], "Yusuf Khan", "Yousuf Khan"),
        ("Basavaraju", ["Basavaraj", "Basavraj", "BASAVARAJU"], "Siddappa", "Siddapa"),
        ("Lakshmamma", ["Lakshmi", "Laxmamma", "Smt. Lakshmamma"], "Krishnappa", "Krishnapa"),
        ("Venkatesh Naik", ["Venkatesha Naik", "Venkatesh Nayak", "Venkatesh @ Venki"], "Mallesh", "Mallesha"),
        ("Shivakumar", ["Shiva Kumar", "SHIVAKUMAR", "Shivakumara"], "Nagaraj", "Nagaraja"),
        ("Prakash Hegde", ["Prakasha Hegde", "Prakash Hegade", "P. Hegde"], "Basappa", "Basappa"),
        ("Imran Pasha", ["Imraan Pasha", "Imran @ Pappu", "Imran Pasa"], "Abdul Rahim", "Abdul Raheem"),
        ("Girish Gowda", ["Girisha Gowda", "Girish Gouda", "GIRISH GOWDA"], "Thimmaiah", "Thimmayya"),
        ("Manjula", ["Manjula R", "Manjulamma", "Smt Manjula"], "Govindappa", "Govindapa"),
    ]
    for gi, (name, variants, father, fvar) in enumerate(groups):
        gender = "female" if name in ("Lakshmamma", "Manjula") else "male"
        dob = g.today - timedelta(days=rng.randint(25, 50) * 365)
        dist = gi % 3
        for vi, nm in enumerate([name] + variants[:2]):
            a = g.ago(rng.randint(200, 900))
            p = g.person(["identity_same_person", "aliases" if "@" in nm else "spelling_variation",
                          "transliteration_variation"], name=nm, father=father if vi % 2 == 0 else fvar, dob=dob,
                         gender=gender, district=dist, identity_group=f"G{gi}")
            c = g.case(p, "c1", [g.law(a - ONE, 36)], offence=a - ONE, remand=a, cs=a + 40 * ONE)
            g.custody(p, "judicial_custody", a, None, case=c)
            g.expect(p, custody=span(a, g.today), months=36)
        # look-alikes: same name, different father AND age far apart → must not be linked
        for li in range(2):
            a = g.ago(rng.randint(200, 900))
            other_father = rng.choice([f for f in FATHERS if f not in (father, fvar)])
            p = g.person(["identity_different_person", "same_name_different_father", "same_name_different_age",
                          "similar_names_different_people"], name=name, father=other_father,
                         dob=dob - timedelta(days=(18 + li * 7) * 365), gender=gender, district=dist,
                         identity_group=f"G{gi}-other{li}")
            c = g.case(p, "c1", [g.law(a - ONE, 36)], offence=a - ONE, remand=a, cs=a + 40 * ONE)
            g.custody(p, "judicial_custody", a, None, case=c)
            g.expect(p, custody=span(a, g.today), months=36)


def generate_scenarios(today: date, seed: int = 11, target: int = 1000) -> list[dict]:
    g = Gen(today, random.Random(seed))
    for fam in (f1_threshold_grid, f2_custody_shapes, f3_delays, f4_default_bail, f5_outcomes, f6_legal, f7_records,
                f8_identity):
        fam(g)
    # top up with randomised threshold cases (different lengths, districts, assignments) to reach the target
    rng = g.rng
    while len(g.people) < target:
        months = rng.choice(list(BY_MONTHS))
        first = rng.random() < 0.75
        counted = rng.randint(1, max_days(months) + 400)
        k = rng.choice([0, 0, 0, 7, 30])
        arrest = g.ago(counted + k - 1)
        p = g.person(["random_topup", "first_time" if first else "repeat_offender", f"max_{months}m"])
        remand = arrest + ONE
        cs = remand + 45 * ONE if remand + 45 * ONE < g.today else None
        c = g.case(p, "c1", [g.law(arrest - ONE, months)], offence=arrest - ONE, remand=remand, cs=cs,
                   status="trial" if cs else "investigation")
        g.custody(p, "arrest", arrest, case=c)
        g.custody(p, "judicial_custody", remand, None, case=c)
        acc: set[date] = set()
        if k and arrest + (3 + k) * ONE < g.today:
            h0 = arrest + 3 * ONE
            g.hearing(c, h0, h0 + k * ONE, "accused")
            acc = span(h0, h0 + (k - 1) * ONE)
        if not first:
            p["convictions"].append({"case_ref": "prior", "date": (arrest - 700 * ONE).isoformat(), "status": "final",
                                     "offence": "IPC 379"})
        findings = ["URGENT_DEFAULT_BAIL"] if cs is None and (g.today - remand).days >= 60 else []
        g.expect(p, custody=span(arrest, g.today), accused=acc, months=months, first_time=first, findings=findings)
    return g.people


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", type=date.fromisoformat, default=date(2026, 9, 30))
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "out" / "scenarios.json")
    a = ap.parse_args()
    people = generate_scenarios(a.today, a.seed)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(people, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(people)} scenarios -> {a.out}")


if __name__ == "__main__":
    main()
