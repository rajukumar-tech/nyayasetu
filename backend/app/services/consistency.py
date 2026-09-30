"""Cross-check document facts against the structured case record.

Structured case/custody records are what the engine computes on; extracted document facts are the evidence
behind them. A fact never silently changes a calculation. Instead:

* a fact a reviewer REJECTED is ignored;
* a fact that contradicts the record on a date the calculation depends on routes the case to REVIEW — also when
  the fact is not yet confirmed (a low-confidence or unverified-document reading is still evidence that someone
  must look at). An ambiguous date (dd/mm vs mm/dd) conflicts only if EVERY reading of it disagrees with the
  record; if one reading matches, the record corroborates that reading;
* contradictions that do not change the numbers (offence date, hearings, transfers) are shown as notes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Document, ExtractedFact, Person


@dataclass
class CaseConflicts:
    blocking: list[str] = field(default_factory=list)  # change the calculation → REVIEW
    notes: list[str] = field(default_factory=list)     # shown, do not change the status


def _as_date(v) -> date | None:
    if isinstance(v, dict):
        v = v.get("date")
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _readings(f: ExtractedFact) -> list[date]:
    d = _as_date(f.effective_value)
    if d is None:
        return []
    out = [d]
    ambiguous = f.review_status not in ("confirmed", "corrected") and any("AMBIGU" in n for n in f.notes or [])
    if ambiguous and d.day <= 12 and d.day != d.month:
        try:
            out.append(date(d.year, d.day, d.month))
        except ValueError:
            pass
    return out


def _confirmed(f: ExtractedFact) -> bool:
    return f.review_status in ("confirmed", "corrected") or f.confidence >= settings.confidence_threshold


MANUAL = "manual_entry"
EVIDENCE_PREFIX = "Entered by hand — no document supports it yet: "


def _manual(src: dict | None) -> bool:
    return bool(src) and src.get("doc_type") == MANUAL


def _require_evidence_for_manual_entries(person: Person, facts, out: dict[str, CaseConflicts]) -> None:
    """A record typed in by hand (a new prisoner) is not evidence. Until a confirmed-or-confident document fact
    supports the arrest/custody start, the first remand and each charge, the case stays in REVIEW — the numbers
    are shown as provisional, never as a definite result."""
    # support = an EXACT match of the document's own (day-first) reading with the typed value. A low-confidence reading
    # that independently gives the same date corroborates it; a rejected fact, or any fact from a document held as
    # unverified (wrong person / wrong case / content not matching its type), never does.
    usable = [f for f in facts if f.review_status != "rejected"
              and not any(str(n).startswith("UNVERIFIED_DOCUMENT") for n in (f.notes or []))]

    def dates(*fields: str, case_id: str | None = None) -> set[date]:
        return {d for f in usable if f.field in fields and (case_id is None or f.case_id in (case_id, None))
                for d in [_as_date(f.effective_value)] if d}

    for case in person.cases:
        res = out[case.id]
        manual_custody = [e for e in person.custody_events if e.case_id in (case.id, None) and _manual(e.source)
                          and e.type in ("arrest", "judicial_custody", "police_custody")]
        if manual_custody:
            starts = {e.start for e in manual_custody}
            seen = dates("arrest_datetime", "remand_date", "admission_date", "production_datetime", "stated_arrest_date",
                         case_id=case.id)
            if not starts & seen:
                res.blocking.append(EVIDENCE_PREFIX + "custody from " + ", ".join(sorted(d.isoformat() for d in starts))
                                    + " (upload the arrest memo, remand order or jail admission record).")
        if case.first_remand_date and manual_custody and case.first_remand_date not in dates("remand_date", case_id=case.id):
            res.blocking.append(EVIDENCE_PREFIX + f"first remand {case.first_remand_date.isoformat()} (upload the remand order).")
        charged = {(str(f.effective_value.get("act", "")).upper(), str(f.effective_value.get("section", "")))
                   for f in usable if f.field == "charge" and isinstance(f.effective_value, dict)
                   and f.case_id in (case.id, None)}
        for ch in case.charges:
            if _manual(ch.source) and (ch.act.upper(), ch.section) not in charged:
                res.blocking.append(EVIDENCE_PREFIX + f"charge {ch.act} {ch.section} (upload the FIR or charge sheet).")


def record_conflicts(db: Session, person: Person) -> dict[str, CaseConflicts]:
    out: dict[str, CaseConflicts] = {c.id: CaseConflicts() for c in person.cases}
    if not person.cases:
        return out
    facts = db.scalars(select(ExtractedFact).where(ExtractedFact.person_id == person.id,
                                                   ExtractedFact.review_status != "rejected")).all()
    # a document held as unverified (another person, another case, content not matching its type) is already in the
    # reviewer's queue; until a reviewer confirms its facts it neither supports nor contradicts this prisoner's record
    facts = [f for f in facts if f.review_status in ("confirmed", "corrected")
             or not any(str(n).startswith("UNVERIFIED_DOCUMENT") for n in (f.notes or []))]
    if not facts:
        _require_evidence_for_manual_entries(person, [], out)
        return out
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.person_id == person.id))}
    only_case = person.cases[0].id if len(person.cases) == 1 else None
    by_id = {c.id: c for c in person.cases}
    for f in facts:
        cid = f.case_id or only_case
        case = by_id.get(cid) if cid else None
        readings = _readings(f)
        if case is None or not readings:
            continue
        doc = docs.get(f.document_id)
        where = f"{doc.doc_type if doc else 'document'} {doc.filename if doc else f.document_id}, p.{f.page}"
        if not _confirmed(f):
            where += "; reading not yet confirmed"
        d = readings[0]
        res = out[case.id]

        def conflicts(bad, matches=None) -> bool:
            """The day-first reading governs (Indian records); an alternative reading of an ambiguous date only
            clears the conflict when it matches the record EXACTLY."""
            return bad(readings[0]) and not any((matches or (lambda _x: False))(x) for x in readings[1:])

        if f.field == "charge_sheet_date":
            if case.charge_sheet_date is None:
                res.blocking.append(f"A charge sheet dated {d.isoformat()} is in the documents ({where}) but the case "
                                    "record has no charge-sheet date — affects default bail.")
            elif conflicts(lambda x: x != case.charge_sheet_date, lambda x: x == case.charge_sheet_date):
                res.blocking.append(f"Charge-sheet date differs: record {case.charge_sheet_date.isoformat()}, "
                                    f"document {d.isoformat()} ({where}).")
        elif f.field == "remand_date":
            if case.first_remand_date is None:
                res.blocking.append(f"Remand order dated {d.isoformat()} ({where}) but no first-remand date on the case record.")
            elif conflicts(lambda x: x < case.first_remand_date, lambda x: x == case.first_remand_date):
                res.blocking.append(f"A remand order dated {d.isoformat()} ({where}) is earlier than the recorded first "
                                    f"remand {case.first_remand_date.isoformat()} — affects the default-bail window.")
        elif f.field == "arrest_datetime":
            starts = [e.start for e in person.custody_events if e.case_id in (case.id, None)]
            if starts and conflicts(lambda x: x < min(starts), lambda x: x in starts):
                res.blocking.append(f"Arrest memo gives arrest on {d.isoformat()} ({where}) but recorded custody starts "
                                    f"{min(starts).isoformat()} — custody may be under-counted.")
        elif f.field == "release_date":
            def recorded(x: date) -> bool:
                return any(e.type in ("released", "escaped") and e.start == x for e in person.custody_events)

            def continues(x: date) -> bool:
                return any(e.case_id in (case.id, None) and e.type not in ("released", "escaped", "on_bail", "absconding")
                           and e.start <= x and (e.end is None or e.end > x) for e in person.custody_events)
            if conflicts(lambda x: not recorded(x) and continues(x), recorded):
                res.blocking.append(f"A release document gives release on {d.isoformat()} ({where}) but the custody "
                                    "record continues after that date — confirm and record the release, or reject the document.")
        elif f.field == "offence_datetime" and case.offence_date and conflicts(lambda x: x != case.offence_date,
                                                                                 lambda x: x == case.offence_date):
            res.notes.append(f"FIR gives offence date {d.isoformat()} ({where}); case record has {case.offence_date.isoformat()}.")
        elif f.field == "transfer_date" and conflicts(lambda x: not any(e.type == "transfer" and e.start == x
                                                                         for e in person.custody_events)):
            res.notes.append(f"A transfer document dated {d.isoformat()} ({where}) is not in the custody record.")
        elif f.field == "hearing" and case.hearings and conflicts(lambda x: x not in {h.date for h in case.hearings},
                                                                  lambda x: x in {h.date for h in case.hearings}):
            res.notes.append(f"Order sheet lists a hearing on {d.isoformat()} ({where}) that is not in the hearing record.")
    _require_evidence_for_manual_entries(person, facts if facts else [], out)
    for res in out.values():
        res.blocking = list(dict.fromkeys(res.blocking))
        res.notes = list(dict.fromkeys(res.notes))
    return out
