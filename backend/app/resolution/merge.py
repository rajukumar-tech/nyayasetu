"""Merge / un-merge person records with a full snapshot and audit trail, and case dedupe by CNR."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.models import Case, Conviction, CustodyEvent, Document, ExtractedFact, MergeEvent, Person, User, case_persons
from app.resolution.matcher import Record


def person_record(p: Person) -> Record:
    return Record(p.id, p.canonical_name, (p.relative_name_variants or [None])[0], p.age_at_offence,
                  p.district, next((c.police_station for c in p.cases if c.police_station), None),
                  (p.addresses or [None])[0], [], [c.cnr for c in p.cases if c.cnr])


def merge_persons(db: Session, keep: Person, other: Person, user: User | None, score: float | None = None) -> MergeEvent:
    """Move everything from `other` into `keep`. `other` is kept (merged_into_id set) so it can be restored."""
    if keep.id == other.id or other.merged_into_id:
        raise ValueError("Cannot merge a record into itself or merge an already-merged record")
    snapshot = {
        "case_ids": [c.id for c in other.cases],
        "moved_case_ids": [c.id for c in other.cases if c not in keep.cases],
        "custody_ids": [e.id for e in other.custody_events],
        "conviction_ids": [c.id for c in other.convictions],
        "document_ids": list(db.scalars(select(Document.id).where(Document.person_id == other.id))),
        "fact_ids": list(db.scalars(select(ExtractedFact.id).where(ExtractedFact.person_id == other.id))),
        "keep_before": {"name_variants": list(keep.name_variants), "relative_name_variants": list(keep.relative_name_variants),
                        "identifiers": dict(keep.identifiers), "assigned_lawyer_id": keep.assigned_lawyer_id},
    }
    for c in list(other.cases):
        if c not in keep.cases:
            keep.cases.append(c)
        other.cases.remove(c)
    for e in list(other.custody_events):
        e.person_id = keep.id
    for cv in list(other.convictions):
        cv.person_id = keep.id
    db.flush()
    db.expire(other)
    db.expire(keep)
    for d in db.scalars(select(Document).where(Document.person_id == other.id)):
        d.person_id = keep.id
    for f in db.scalars(select(ExtractedFact).where(ExtractedFact.person_id == other.id)):
        f.person_id = keep.id
    keep.name_variants = sorted(set(keep.name_variants) | set(other.name_variants) | {other.canonical_name} - {keep.canonical_name})
    keep.relative_name_variants = sorted(set(keep.relative_name_variants) | set(other.relative_name_variants))
    keep.identifiers = {**other.identifiers, **keep.identifiers}
    keep.assigned_lawyer_id = keep.assigned_lawyer_id or other.assigned_lawyer_id
    other.merged_into_id = keep.id
    ev = MergeEvent(kept_person_id=keep.id, merged_person_id=other.id, snapshot=snapshot, score=score,
                    performed_by=user.id if user else None)
    db.add(ev)
    db.flush()
    audit(db, user, "merge_persons", "person", keep.id, before=None,
          after={"merged": other.id, "merge_event": ev.id, "score": score}, commit=False)
    db.commit()
    return ev


def unmerge(db: Session, event: MergeEvent, user: User | None) -> Person:
    """Restore the merged person exactly as recorded in the snapshot."""
    if event.undone:
        raise ValueError("Merge already undone")
    s = event.snapshot
    keep = db.get(Person, event.kept_person_id)
    other = db.get(Person, event.merged_person_id)
    for cid in s["case_ids"]:
        c = db.get(Case, cid)
        if c is not None:
            if c not in other.cases:
                other.cases.append(c)
            if c in keep.cases and cid in s["moved_case_ids"]:
                keep.cases.remove(c)
    for eid in s["custody_ids"]:
        e = db.get(CustodyEvent, eid)
        if e is not None:
            e.person_id = other.id
    for cid in s["conviction_ids"]:
        cv = db.get(Conviction, cid)
        if cv is not None:
            cv.person_id = other.id
    for did in s["document_ids"]:
        d = db.get(Document, did)
        if d is not None:
            d.person_id = other.id
    for fid in s["fact_ids"]:
        f = db.get(ExtractedFact, fid)
        if f is not None:
            f.person_id = other.id
    kb = s["keep_before"]
    keep.name_variants = kb["name_variants"]
    keep.relative_name_variants = kb["relative_name_variants"]
    keep.identifiers = kb["identifiers"]
    keep.assigned_lawyer_id = kb["assigned_lawyer_id"]
    other.merged_into_id = None
    event.undone = True
    audit(db, user, "unmerge_persons", "person", keep.id, before={"merge_event": event.id},
          after={"restored": other.id}, commit=False)
    db.commit()
    return other


def dedupe_cases_by_cnr(db: Session, user: User | None = None) -> list[tuple[str, str]]:
    """A case transferred between courts can arrive twice with different case numbers but the same CNR.
    Fold duplicates into one case, keeping all case numbers."""
    merged: list[tuple[str, str]] = []
    rows = db.scalars(select(Case).where(Case.cnr.is_not(None)).order_by(Case.cnr, Case.id)).all()
    by_cnr: dict[str, list[Case]] = {}
    for c in rows:
        by_cnr.setdefault(c.cnr, []).append(c)
    for cnr, cases in by_cnr.items():
        keep, *dups = cases
        for d in dups:
            keep.case_numbers = sorted(set(keep.case_numbers) | set(d.case_numbers))
            keep.court = d.court if d.court and (d.first_remand_date or d.charge_sheet_date) else keep.court
            for f in ("offence_date", "fir_date", "first_remand_date", "charge_sheet_date", "default_bail_application_date",
                      "bail_granted_date", "conviction_date", "acquittal_date"):
                if getattr(keep, f) is None and getattr(d, f) is not None:
                    setattr(keep, f, getattr(d, f))
            existing = {(ch.act, ch.section, ch.modifier) for ch in keep.charges}
            for ch in list(d.charges):
                if (ch.act, ch.section, ch.modifier) not in existing:
                    ch.case_id = keep.id
            for h in list(d.hearings):
                h.case_id = keep.id
            for p in list(d.persons):
                if p not in keep.persons:
                    keep.persons.append(p)
            db.flush()
            for e in db.scalars(select(CustodyEvent).where(CustodyEvent.case_id == d.id)):
                e.case_id = keep.id
            for doc in db.scalars(select(Document).where(Document.case_id == d.id)):
                doc.case_id = keep.id
            db.execute(case_persons.delete().where(case_persons.c.case_id == d.id))
            db.flush()
            db.expire(d)
            db.delete(d)
            merged.append((keep.id, d.id))
            audit(db, user, "dedupe_case", "case", keep.id, after={"folded": d.id, "cnr": cnr}, commit=False)
    db.commit()
    return merged
