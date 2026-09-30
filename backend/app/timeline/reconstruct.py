"""Custody timeline reconstruction (deterministic).

Day-counting convention (documented in docs/DECISIONS.md, D-004):
  * Every interval is INCLUSIVE of both its first and last day. Arrested and
    released on the same day = 1 day in custody.
  * The day of release/escape counts as a custody day.
  * Explicit exclusion intervals (on_bail, absconding) remove their days inclusively.
  * An open custody interval ends at the next release/escape after it, else today.

Inputs are normalised into intervals:
  counting intervals  police/judicial custody, hospitalised in custody
  starters            arrest / re-arrest / surrender / transfer open an implicit interval
                      running to the next terminator (or today)
  terminators         released / escaped close open intervals
  exclusions          on_bail / absconding intervals are subtracted
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.domain import (
    COUNTING_INTERVALS, EXCLUSION_INTERVALS, STARTERS, TERMINATORS,
    Case, CustodyEvent, CustodyType, Person, SourceRef,
)

ONE_DAY = timedelta(days=1)


def inclusive_days(start: date, end: date) -> int:
    return (end - start).days + 1 if end >= start else 0


@dataclass
class Interval:
    start: date
    end: date
    kind: str
    explanation: str
    sources: list[SourceRef] = field(default_factory=list)
    case_ids: set[str | None] = field(default_factory=set)
    jails: list[str] = field(default_factory=list)
    explicit: bool = False  # a recorded interval with its own end date (not inferred)

    @property
    def days(self) -> int:
        return inclusive_days(self.start, self.end)


@dataclass
class TimelineFlag:
    code: str
    message: str
    severity: str = "warning"  # info | warning | critical
    sources: list[SourceRef] = field(default_factory=list)


@dataclass
class ArrestDateResolution:
    chosen: date | None
    candidates: list[tuple[date, bool, SourceRef | None]]  # (date, is_primary, source)
    confidence: float
    conflict: bool


@dataclass
class Timeline:
    case_id: str | None
    today: date
    intervals: list[Interval]
    excluded: list[Interval]
    gaps: list[tuple[date, date]]
    flags: list[TimelineFlag]
    arrest: ArrestDateResolution
    custody_days: int
    lenient_custody_days: int | None = None  # includes custody recorded against other cases
    in_custody_today: bool = False
    stop_date: date | None = None  # counting stops (e.g. conviction)
    low_confidence: list[str] = field(default_factory=list)

    def in_custody_on(self, d: date) -> bool:
        return any(i.start <= d <= i.end for i in self.intervals)

    def explanation(self) -> list[str]:
        lines = [f"{i.start.isoformat()} → {i.end.isoformat()}: {i.days} day(s) — {i.explanation}" for i in self.intervals]
        lines += [f"minus {e.start.isoformat()} → {e.end.isoformat()}: {e.days} day(s) — {e.explanation}" for e in self.excluded]
        return lines


def resolve_arrest_date(events: list[CustodyEvent], threshold: float) -> ArrestDateResolution:
    """Pick the earliest arrest date supported by a primary document; flag conflicts."""
    arrests = [e for e in events if e.type == CustodyType.ARREST]
    if not arrests:
        return ArrestDateResolution(None, [], 1.0, False)
    candidates = sorted({(e.start, e.is_primary_source, e.source) for e in arrests}, key=lambda c: (c[0], not c[1]))
    distinct = {c[0] for c in candidates}
    primary = [e for e in arrests if e.is_primary_source]
    pool = primary or arrests
    chosen_event = min(pool, key=lambda e: e.start)
    same_day = [e for e in pool if e.start == chosen_event.start]
    confidence = max(e.confidence for e in same_day)
    if not primary:
        confidence = min(confidence, threshold - 0.01)  # secondary-only → below threshold
    return ArrestDateResolution(chosen_event.start, candidates, confidence, len(distinct) > 1)


def _merge(intervals: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for iv in sorted(intervals, key=lambda i: (i.start, i.end)):
        if out and iv.start <= out[-1].end + ONE_DAY:
            last = out[-1]
            if iv.end > last.end:
                last.end = iv.end
            if iv.explanation not in last.explanation:
                last.explanation += f"; {iv.explanation}"
            last.sources += [s for s in iv.sources if s not in last.sources]
            last.case_ids |= iv.case_ids
            last.jails += [j for j in iv.jails if j not in last.jails]
        else:
            out.append(Interval(iv.start, iv.end, iv.kind, iv.explanation, list(iv.sources), set(iv.case_ids), list(iv.jails)))
    return out


def _subtract(intervals: list[Interval], exclusions: list[Interval]) -> list[Interval]:
    result = intervals
    for ex in exclusions:
        nxt: list[Interval] = []
        for iv in result:
            if ex.end < iv.start or ex.start > iv.end:
                nxt.append(iv)
                continue
            if iv.start < ex.start:
                nxt.append(Interval(iv.start, ex.start - ONE_DAY, iv.kind, iv.explanation, iv.sources, iv.case_ids, iv.jails))
            if iv.end > ex.end:
                nxt.append(Interval(ex.end + ONE_DAY, iv.end, iv.kind, iv.explanation, iv.sources, iv.case_ids, iv.jails))
        result = nxt
    return result


def _clip(intervals: list[Interval], stop: date) -> list[Interval]:
    out = []
    for iv in intervals:
        if iv.start > stop:
            continue
        out.append(Interval(iv.start, min(iv.end, stop), iv.kind, iv.explanation, iv.sources, iv.case_ids, iv.jails))
    return out


def _describe(e: CustodyEvent) -> str:
    where = f" at {e.jail}" if e.jail else ""
    return {
        CustodyType.POLICE_CUSTODY: f"police custody{where}",
        CustodyType.JUDICIAL_CUSTODY: f"judicial custody{where}",
        CustodyType.HOSPITALISED_IN_CUSTODY: f"hospitalised while in custody{where} (counts)",
        CustodyType.ARREST: "from arrest",
        CustodyType.RE_ARREST: "re-arrested",
        CustodyType.SURRENDERED: "surrendered",
        CustodyType.TRANSFER: f"transferred{where}",
        CustodyType.ON_BAIL: "on bail (not custody)",
        CustodyType.ABSCONDING: "absconding/escaped (not custody)",
    }.get(e.type, e.type.value)


def build_intervals(events: list[CustodyEvent], today: date, threshold: float,
                    ) -> tuple[list[Interval], list[Interval], list[TimelineFlag], ArrestDateResolution, list[str]]:
    """Normalise events into (custody intervals, exclusions, flags, arrest resolution, low-confidence notes).
    Does not filter by case — callers pass the event subset they want."""
    flags: list[TimelineFlag] = []
    low: list[str] = []
    arrest = resolve_arrest_date(events, threshold)
    if arrest.conflict:
        flags.append(TimelineFlag(
            "CONFLICTING_ARREST_DATES",
            "Documents disagree on the arrest date: "
            + ", ".join(f"{d.isoformat()} ({'primary' if p else 'secondary'}"
                        f"{', ' + s.label() if s else ''})" for d, p, s in arrest.candidates)
            + f". Using {arrest.chosen.isoformat() if arrest.chosen else 'none'} — earliest date in a primary document.",
            "warning", [s for _, _, s in arrest.candidates if s]))
    if arrest.chosen and arrest.confidence < threshold:
        low.append(f"Arrest date {arrest.chosen.isoformat()} (confidence {arrest.confidence:.2f})")
    primary_dates = sorted({d for d, p, _ in arrest.candidates if p})
    if len(primary_dates) > 1:
        # two PRIMARY documents disagree — picking the earliest is favourable to the prisoner but must be confirmed
        low.append("Primary documents give different arrest dates: " + ", ".join(d.isoformat() for d in primary_dates))

    terminators = sorted((e for e in events if e.type in TERMINATORS), key=lambda e: e.start)

    def close(start: date) -> tuple[date, bool]:
        t = next((e for e in terminators if e.start >= start), None)
        return (t.start, False) if t else (today, True)

    custody: list[Interval] = []
    exclusions: list[Interval] = []
    open_ended = False
    for e in events:
        if e.type == CustodyType.ARREST and e.start != arrest.chosen:
            continue  # superseded conflicting arrest date
        if e.type in COUNTING_INTERVALS or e.type in STARTERS:
            if e.end is not None:
                end, used_today = e.end, False
            else:
                end, used_today = close(e.start)
            open_ended |= used_today
            if e.end is not None and e.end > today:
                flags.append(TimelineFlag("FUTURE_END_DATE", f"Custody record ends in the future ({e.end.isoformat()}); clipped to today.",
                                          "warning", [e.source] if e.source else []))
                end = today
            if e.start > today:
                flags.append(TimelineFlag("FUTURE_START_DATE", f"Custody record starts in the future ({e.start.isoformat()}); ignored.",
                                          "warning", [e.source] if e.source else []))
                low.append(f"{e.type.value} record dated {e.start.isoformat()} is in the future")
                continue
            if end < e.start:
                flags.append(TimelineFlag("END_BEFORE_START", f"Custody record ends ({end.isoformat()}) before it starts "
                                          f"({e.start.isoformat()}); ignored.", "warning", [e.source] if e.source else []))
                low.append(f"{e.type.value} record {e.start.isoformat()} → {end.isoformat()} has its end before its start")
                continue
            custody.append(Interval(e.start, end, "custody", _describe(e), [e.source] if e.source else [], {e.case_id},
                                    [e.jail] if e.jail else [], explicit=e.type in COUNTING_INTERVALS and e.end is not None))
            if e.confidence < threshold:
                low.append(f"{e.type.value} from {e.start.isoformat()} (confidence {e.confidence:.2f})")
        elif e.type in EXCLUSION_INTERVALS:
            end = min(e.end or close(e.start)[0], today)
            if e.start > today or end < e.start:
                # a reversed or future bail/absconding record must not be "subtracted" — a reversed range would
                # otherwise split custody into two overlapping pieces and INFLATE the count
                flags.append(TimelineFlag("INVALID_EXCLUSION_RANGE", f"{_describe(e).capitalize()} record "
                                          f"{e.start.isoformat()} → {(e.end or end).isoformat()} is reversed or in the future; "
                                          "ignored.", "warning", [e.source] if e.source else []))
                low.append(f"{e.type.value} record {e.start.isoformat()} → {(e.end or end).isoformat()} is invalid")
                continue
            exclusions.append(Interval(e.start, end, "excluded", _describe(e), [e.source] if e.source else [], {e.case_id}))
    if open_ended:
        flags.append(TimelineFlag("CURRENT_CUSTODY_USES_TODAY",
                                  f"No release recorded for the latest custody — counted up to today ({today.isoformat()}).", "info"))
    return custody, exclusions, flags, arrest, low


def reconstruct(person: Person, case: Case | None, today: date, threshold: float = 0.8) -> Timeline:
    """Timeline for one case (strict: events tagged with this case or untagged), plus
    the lenient count that also includes custody recorded against other cases."""
    case_id = case.id if case else None
    own = [e for e in person.custody_events if case is None or e.case_id in (case_id, None)]
    custody, exclusions, flags, arrest, low = build_intervals(own, today, threshold)

    stop = None
    if case is not None and case.conviction_date and case.status.value == "convicted":
        stop = case.conviction_date
        flags.append(TimelineFlag("CONVICTED", f"Undertrial counting stops on the conviction date {stop.isoformat()}.", "info"))
    merged = _merge(custody)
    for ex in exclusions:
        for iv in custody:
            if iv.explicit and ex.start <= iv.end and ex.end >= iv.start:
                src = ex.sources + iv.sources
                flags.append(TimelineFlag("CUSTODY_EXCLUSION_OVERLAP",
                                          f"A record shows custody overlapping a non-custody period ({ex.explanation}, "
                                          f"{ex.start.isoformat()}–{ex.end.isoformat()}); the non-custody period is excluded — verify.",
                                          "warning", src))
                break
    counted = _subtract(merged, exclusions)
    if stop:
        counted = _clip(counted, stop)
    counted = _merge(counted)
    gaps = [(a.end + ONE_DAY, b.start - ONE_DAY) for a, b in zip(counted, counted[1:]) if b.start > a.end + ONE_DAY]
    for g0, g1 in gaps:
        explained = any(ex.start <= g1 and ex.end >= g0 for ex in exclusions) or \
            any(e.type in TERMINATORS and g0 - ONE_DAY <= e.start <= g1 for e in own)
        if not explained:
            flags.append(TimelineFlag("UNEXPLAINED_GAP", f"No record explains the gap {g0.isoformat()} → {g1.isoformat()}.", "warning"))
    total = sum(i.days for i in counted)

    tl = Timeline(case_id, today, counted, exclusions, gaps, flags, arrest, total, None,
                  any(i.start <= today <= i.end for i in counted), stop, low)

    if case is not None:
        others = [e for e in person.custody_events if e.case_id not in (case_id, None)]
        if others:
            anchor = case.offence_date or case.fir_date or min((e.start for e in own), default=None)
            lc, lx, _, _, _ = build_intervals(own + others, today, threshold)
            lenient = _merge(_subtract(_merge(lc), lx))
            if stop:
                lenient = _clip(lenient, stop)
            if anchor:
                lenient = [Interval(max(i.start, anchor), i.end, i.kind, i.explanation, i.sources, i.case_ids)
                           for i in lenient if i.end >= anchor]
            tl.lenient_custody_days = sum(i.days for i in lenient)
            if tl.lenient_custody_days != total:
                tl.flags.append(TimelineFlag(
                    "CUSTODY_IN_OTHER_CASE",
                    f"The person was also in custody in another case during this case's pendency. Counting only this "
                    f"case: {total} days; also counting the other case's custody: {tl.lenient_custody_days} days. "
                    f"Whether that custody counts for this case is legally uncertain — review.", "warning"))
    return tl
