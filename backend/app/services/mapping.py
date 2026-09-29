"""ORM rows → pure domain objects for the engines, and dataclasses → JSON."""
from __future__ import annotations

import dataclasses
from datetime import date, datetime
from enum import Enum
from typing import Any

from app import domain as d
from app import models as m


def source_from(raw: dict | None) -> d.SourceRef | None:
    if not raw:
        return None
    return d.SourceRef(raw.get("document_id", ""), raw.get("page", 1), raw.get("start", 0), raw.get("end", 0),
                       raw.get("text", ""), raw.get("doc_type", ""))


def to_domain_person(p: m.Person) -> d.Person:
    cases = []
    for c in p.cases:
        cases.append(d.Case(
            id=c.id, status=d.CaseStatus(c.status), cnr=c.cnr or "",
            charges=[d.Charge(act=ch.act, section=ch.section, modifier=d.Modifier(ch.modifier) if ch.modifier else None,
                              offence_date=ch.offence_date or c.offence_date, added_on=ch.added_on, dropped_on=ch.dropped_on,
                              confidence=ch.confidence, source=source_from(ch.source), aggravated=ch.aggravated, id=ch.id)
                     for ch in c.charges],
            hearings=[d.Hearing(date=h.date, next_date=h.next_date, reason_text=h.reason_text or h.outcome_text,
                                attribution=d.Attribution(h.delay_attribution), attribution_confidence=h.attribution_confidence,
                                reviewer_verified=h.reviewer_verified, source=source_from(h.source), id=h.id)
                      for h in c.hearings],
            offence_date=c.offence_date, fir_date=c.fir_date, first_remand_date=c.first_remand_date,
            charge_sheet_date=c.charge_sheet_date, default_bail_application_date=c.default_bail_application_date,
            bail_granted_date=c.bail_granted_date, conviction_date=c.conviction_date, acquittal_date=c.acquittal_date,
            status_confidence=c.status_confidence))
    return d.Person(
        id=p.id, name=p.canonical_name, cases=cases, dob=p.dob, gender=p.gender,
        custody_events=[d.CustodyEvent(type=d.CustodyType(e.type), start=e.start, end=e.end, case_id=e.case_id, jail=e.jail,
                                       confidence=e.confidence, is_primary_source=e.is_primary_source,
                                       source=source_from(e.source), id=e.id) for e in p.custody_events],
        convictions=[d.Conviction(case_id=cv.case_id, date=cv.date, status=d.ConvictionStatus(cv.status), offence=cv.offence,
                                  source=source_from(cv.source), id=cv.id) for cv in p.convictions],
    )


def jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        items = [jsonable(v) for v in obj]
        return sorted(items, key=str) if isinstance(obj, set) else items
    return obj
