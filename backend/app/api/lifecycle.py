"""Record lifecycle: new prisoners, custody changes (transfer / release), case outcomes, and lawyer accounts.

Same rules as the rest of the API: every endpoint is permission-checked, record scope is enforced on the
server, out-of-scope records get the same 404 as missing ones, and every change is audit-logged.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import settings
from app.core.rbac import Perm, Role, ensure_person_access, has_perm, not_found, require
from app.core.security import hash_password
from app.db import get_db
from app.defense.service import refresh_insights
from app.models import Case, Charge, CustodyEvent, Person, ReviewItem, User
from app.monitoring.alerts import alerts_for
from app.resolution.matcher import PairModel, score_pair
from app.resolution.merge import person_record
from app.schemas import CasePatch, LawyerCreate, PasswordReset, PersonCreate, ReleaseIn, TransferIn
from app.services import accounts
from app.services.eligibility import compute_for_person

router = APIRouter(prefix="/api")


def _recompute(db: Session, p: Person, reason: str) -> dict:
    # rows added with db.add() are not in relationships that were already loaded (autoflush is off): write them
    # and reload the person, or the engine would compute on the OLD custody history
    db.flush()
    db.refresh(p)
    out = compute_for_person(db, p, commit=False)
    alerts_for(db, p, out, settings.today(), reason=reason)
    refresh_insights(db, p)
    db.commit()
    return {"status": out.row.status, "changed": out.changed, "previous_status": out.previous_status}


def assignable_person(db: Session, user: User, pid: str) -> Person:
    """The admin assigns across the whole register; the DLSA only within its district."""
    p = db.get(Person, pid)
    if Role(user.role) == Role.SYSTEM_ADMIN:
        if p is None or p.merged_into_id:
            raise not_found()
        return p
    return ensure_person_access(user, p, db)


def _not_future(d: date | None, what: str) -> None:
    if d is not None and d > settings.today():
        raise HTTPException(422, f"The {what} ({d.isoformat()}) is in the future.")


def _name_keys(name: str | None) -> set[str]:
    """Spelling-tolerant keys: 'Mahesh Gowda' = 'MAHESH GOWDA' = 'Mahesh Gouda'; 'Ravi Kumar' = 'Ravikumar'."""
    import re
    from app.resolution.normalise import phonetic_key, phonetic_token, to_latin
    if not name or not name.strip():
        return set()
    lat = re.sub(r"[^a-z ]", "", to_latin(name).lower())
    return {k for k in (phonetic_key(name), phonetic_token(lat.replace(" ", ""))) if k}


def _norm(v: str | None) -> str:
    return "".join(ch for ch in (v or "").upper() if ch.isalnum())


def find_existing(db: Session, body: PersonCreate) -> tuple[Person, str] | None:
    """The same prisoner must not be added twice. Blocks on hard identifiers only:
    the same CNR; the same FIR number at the same police station; or the same name AND father's name (spelling-
    tolerant) AND date of birth. Mere look-alikes (same name, different father/age) are allowed and go to the
    reviewer as identity matches — two different people can share a name."""
    c = body.case
    name_k, father_k = _name_keys(body.name), _name_keys(body.relative_name)
    for p in db.scalars(select(Person).where(Person.merged_into_id.is_(None))):
        for case in p.cases:
            if c.cnr and case.cnr and _norm(c.cnr) == _norm(case.cnr):
                return p, f"same CNR {case.cnr}"
            if (c.fir_number and case.fir_number and _norm(c.fir_number) == _norm(case.fir_number)
                    and c.police_station and case.police_station and _norm(c.police_station) == _norm(case.police_station)):
                return p, f"same FIR {case.fir_number} at {case.police_station}"
        if name_k & (_name_keys(p.canonical_name) | {k for v in p.name_variants or [] for k in _name_keys(v)}):
            same_father = bool(father_k) and bool(father_k & {k for v in p.relative_name_variants or [] for k in _name_keys(v)})
            if same_father and body.dob and p.dob and body.dob == p.dob:
                return p, "same name, father's name and date of birth"
    return None


def _known_district(db: Session, jail: str) -> str | None:
    return db.scalar(select(Person.district).where(Person.jail == jail, Person.district.is_not(None)).limit(1))


# ------------------------------------------------------------------ new prisoner
@router.post("/persons")
def create_person(body: PersonCreate, user: User = Depends(require(Perm.CREATE_PRISONER)),
                  db: Session = Depends(get_db)) -> dict:
    """Create a prisoner with a first case. The record starts UNASSIGNED: no lawyer sees it until the DLSA/admin
    assigns one. Eligibility is computed immediately; alerts are raised; possible duplicates go to the reviewer."""
    c = body.case
    if len(body.name.strip()) < 2 or not c.court.strip() or any(not ch.section.strip() or not ch.act.strip() for ch in c.charges):
        raise HTTPException(422, "Name, court and every section must be filled in (not just spaces)")
    if Role(user.role) == Role.JAIL_STAFF:
        if body.jail and body.jail != user.jail:
            raise HTTPException(403, "Jail staff can add prisoners only to their own jail")
        jail = user.jail
    else:
        jail = (body.jail or "").strip() or None
    if not jail:
        raise HTTPException(422, "The jail is required")
    district = (body.district or "").strip() or _known_district(db, jail)
    if not district:
        raise HTTPException(422, "The district is required for a jail not yet in the system")
    for d, what in ((body.dob, "date of birth"), (c.offence_date, "offence date"), (c.arrest_date, "arrest date"),
                    (c.first_remand_date, "first remand date"), (c.charge_sheet_date, "charge-sheet date"),
                    (c.status_change_date, "bail/release date")):
        _not_future(d, what)
    if c.offence_date and c.offence_date > c.arrest_date:
        raise HTTPException(422, "The offence date is after the arrest date")
    if c.first_remand_date and c.first_remand_date < c.arrest_date:
        raise HTTPException(422, "The first remand date is before the arrest date")
    if c.custody_status != "in_custody":
        if c.status_change_date is None:
            raise HTTPException(422, "Give the date of bail/release")
        if c.status_change_date < c.arrest_date:
            raise HTTPException(422, "The bail/release date is before the arrest date")
    dup = find_existing(db, body)
    if dup is not None:
        existing, why = dup
        audit(db, user, "duplicate_blocked", "person", existing.id, detail=why, commit=True)
        if existing.jail and existing.jail == user.jail:
            raise HTTPException(409, f"This prisoner already exists: {existing.canonical_name} ({existing.jail}) — {why}. "
                                     "Open the existing record instead of adding a new one.")
        raise HTTPException(409, f"A prisoner with these details already exists ({why}). Ask the DLSA or the jail "
                                 "holding that record to transfer or update it.")
    p = Person(canonical_name=body.name.strip(), relative_name_variants=[body.relative_name.strip()] if body.relative_name else [],
               relation=body.relation, gender=body.gender, dob=body.dob, addresses=[body.address] if body.address else [],
               jail=jail, district=district, state="Karnataka", vulnerability=["woman"] if body.gender == "female" else [],
               identifiers={"created_by_role": user.role, "intake": "pending_review"}, assigned_lawyer_id=None)
    db.add(p)
    db.flush()
    case = Case(cnr=c.cnr, case_numbers=[c.case_number] if c.case_number else [], court=c.court, district=district,
                state="Karnataka", fir_number=c.fir_number, police_station=c.police_station,
                fir_year=c.offence_date.year if c.offence_date else None,
                status="charge_sheet_filed" if c.charge_sheet_date else "investigation",
                offence_date=c.offence_date, fir_date=c.offence_date, first_remand_date=c.first_remand_date,
                charge_sheet_date=c.charge_sheet_date)
    case.persons.append(p)
    for ch in c.charges:
        case.charges.append(Charge(act=ch.act.strip().upper(), section=ch.section.strip(), offence_date=c.offence_date,
                                   confidence=1.0, source={"doc_type": "manual_entry", "text": f"entered by {user.role}"}))
    db.add(case)
    db.flush()
    src = {"document_id": "", "doc_type": "manual_entry", "text": f"entered by {user.role}"}
    db.add(CustodyEvent(person_id=p.id, case_id=case.id, type="arrest", start=c.arrest_date, jail=jail, source=src))
    if c.first_remand_date:
        end = c.status_change_date if c.custody_status != "in_custody" else None
        db.add(CustodyEvent(person_id=p.id, case_id=case.id, type="judicial_custody", start=c.first_remand_date, end=end,
                            jail=jail, source=src))
    if c.custody_status == "released":
        db.add(CustodyEvent(person_id=p.id, case_id=case.id, type="released", start=c.status_change_date, source=src))
    elif c.custody_status == "on_bail":
        case.bail_granted_date = c.status_change_date
        db.add(CustodyEvent(person_id=p.id, case_id=case.id, type="released", start=c.status_change_date, source=src))
        db.add(CustodyEvent(person_id=p.id, case_id=case.id, type="on_bail", start=c.status_change_date, source=src))
    db.flush()
    db.refresh(p)
    # possible duplicates → reviewer (the creator is told only how many, never who: no cross-scope leak)
    queued = 0
    rec = person_record(p)
    model = PairModel()
    for other in db.scalars(select(Person).where(Person.merged_into_id.is_(None), Person.id != p.id)):
        s = score_pair(rec, person_record(other), model)
        if s.decision in ("link", "review"):
            a, b = sorted((p.id, other.id))
            if db.scalar(select(ReviewItem).where(ReviewItem.kind == "identity_match", ReviewItem.ref_id == f"{a}:{b}")) is None:
                db.add(ReviewItem(kind="identity_match", ref_id=f"{a}:{b}", confidence=s.p,
                                  title=f"Same person? {p.canonical_name} ↔ {other.canonical_name} (new record, score {s.p:.2f})",
                                  payload={"a": a, "b": b, "features": s.features, "vetoes": s.vetoes, "decision": s.decision}))
                queued += 1
    # intake review: a reviewer checks what was entered before any lawyer can be assigned
    db.add(ReviewItem(kind="new_prisoner", ref_id=p.id, confidence=0.0,
                      title=f"New prisoner: {p.canonical_name} ({jail}) — verify the entered details",
                      payload={"person_id": p.id, "name": p.canonical_name, "relative_name": body.relative_name,
                               "relation": body.relation, "gender": body.gender,
                               "dob": body.dob.isoformat() if body.dob else None, "jail": jail, "district": district,
                               "court": c.court, "case_number": c.case_number, "cnr": c.cnr, "fir_number": c.fir_number,
                               "police_station": c.police_station, "charges": [f"{x.act.upper()} {x.section}" for x in c.charges],
                               "offence_date": c.offence_date.isoformat() if c.offence_date else None,
                               "arrest_date": c.arrest_date.isoformat(),
                               "first_remand_date": c.first_remand_date.isoformat() if c.first_remand_date else None,
                               "charge_sheet_date": c.charge_sheet_date.isoformat() if c.charge_sheet_date else None,
                               "custody_status": c.custody_status, "created_by": user.name}))
    audit(db, user, "create_prisoner", "person", p.id, after={"name": p.canonical_name, "jail": jail, "district": district,
                                                               "case": case.id, "assigned": None, "intake": "pending_review"},
          commit=False)
    res = _recompute(db, p, "created")
    return {"id": p.id, "case_id": case.id, "status": res["status"], "assigned_lawyer_id": None,
            "intake": "pending_review", "possible_duplicates_queued": queued}


def intake_status(p: Person) -> str:
    """pending_review | verified | returned. Records loaded before intake review existed count as verified."""
    return (p.identifiers or {}).get("intake", "verified")


# ------------------------------------------------------------------ prisoner register (admin)
@router.get("/register")
def register(user: User = Depends(require(Perm.VIEW_REGISTER)), db: Session = Depends(get_db)) -> list[dict]:
    """Who is in the DLSA's district, intake-review state, headline status and lawyer — enough to assign a lawyer.
    No case details, documents, facts, insights or drafts."""
    from app.api.routes import _fresh_result
    from app.eligibility.engine import urgency_rank
    lawyers = {u.id: u.name for u in db.scalars(select(User).where(User.role == Role.LAWYER))}
    rows = []
    q = select(Person).where(Person.merged_into_id.is_(None))
    if Role(user.role) == Role.DLSA_ADMIN:
        q = q.where(Person.district == user.district)
    for p in db.scalars(q):
        r = _fresh_result(db, p)
        rows.append({"id": p.id, "name": p.canonical_name, "jail": p.jail, "district": p.district,
                     "status": r.status if r else None, "intake": intake_status(p),
                     "assigned_lawyer_id": p.assigned_lawyer_id, "assigned_lawyer": lawyers.get(p.assigned_lawyer_id),
                     "demo_label": (p.identifiers or {}).get("demo_label"), "created_at": p.created_at.isoformat()})
    rows.sort(key=lambda x: ({"pending_review": 0, "returned": 1}.get(x["intake"], 2), x["assigned_lawyer_id"] is not None,
                             urgency_rank(x["status"] or ""), x["name"]))
    audit(db, user, "list", "register", None, detail=f"{len(rows)} rows")
    return rows


# ------------------------------------------------------------------ custody changes
@router.post("/persons/{pid}/transfer")
def transfer(pid: str, body: TransferIn, user: User = Depends(require(Perm.CUSTODY_EVENTS)), db: Session = Depends(get_db)) -> dict:
    p = ensure_person_access(user, db.get(Person, pid), db)
    _not_future(body.on, "transfer date")
    if body.to_jail == p.jail:
        raise HTTPException(422, "The prisoner is already in this jail")
    starts = [e.start for e in p.custody_events]
    if starts and body.on < min(starts):
        raise HTTPException(422, "The transfer date is before the prisoner's custody began")
    before = {"jail": p.jail, "district": p.district}
    # a transfer is a custody STARTER at the new jail: it merges with the running custody interval, so it can
    # neither open a gap nor double-count a day (the timeline merges overlapping/adjacent intervals)
    db.add(CustodyEvent(person_id=p.id, case_id=None, type="transfer", start=body.on, jail=body.to_jail,
                        source={"document_id": "", "doc_type": "jail_transfer_record", "text": body.note or f"transfer to {body.to_jail}"}))
    p.jail = body.to_jail
    p.district = (body.to_district or "").strip() or _known_district(db, body.to_jail) or p.district
    audit(db, user, "transfer_prisoner", "person", p.id, before=before,
          after={"jail": p.jail, "district": p.district, "date": body.on.isoformat()}, commit=False)
    return _recompute(db, p, "transfer") | {"jail": p.jail, "district": p.district}


@router.post("/persons/{pid}/release")
def release(pid: str, body: ReleaseIn, user: User = Depends(require(Perm.CUSTODY_EVENTS)), db: Session = Depends(get_db)) -> dict:
    p = ensure_person_access(user, db.get(Person, pid), db)
    _not_future(body.on, "release date")
    if body.case_id and not any(c.id == body.case_id for c in p.cases):
        raise HTTPException(422, "The selected case does not belong to this prisoner")
    starts = [e.start for e in p.custody_events if e.type not in ("on_bail", "absconding", "released", "escaped")]
    if not starts:
        raise HTTPException(422, "There is no custody on record to close")
    if body.on < max(starts):
        raise HTTPException(422, "The release date is before the latest recorded custody start")
    if any(e.type in ("released", "escaped") and e.start == body.on and e.case_id == body.case_id for e in p.custody_events):
        raise HTTPException(409, "A release on this date is already recorded")
    db.add(CustodyEvent(person_id=p.id, case_id=body.case_id, type="released", start=body.on,
                        source={"document_id": "", "doc_type": "release_order", "text": body.note or "release recorded"}))
    audit(db, user, "record_release", "person", p.id, after={"date": body.on.isoformat(), "case_id": body.case_id},
          detail=body.note, commit=False)
    return _recompute(db, p, "release")


@router.patch("/cases/{cid}")
def update_case(cid: str, body: CasePatch, user: User = Depends(require(Perm.UPDATE_CASE)), db: Session = Depends(get_db)) -> dict:
    """Record a case outcome or procedural date. Only THIS case changes — other cases of the prisoner are untouched."""
    case = db.get(Case, cid)
    if case is None or not case.persons:
        raise not_found()
    for p in case.persons:
        ensure_person_access(user, p, db, "case", case.id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if isinstance(v, date):
            _not_future(v, k.replace("_", " "))
    if changes.get("status") == "acquitted" and not (changes.get("acquittal_date") or case.acquittal_date):
        raise HTTPException(422, "Give the acquittal date")
    if changes.get("status") == "convicted" and not (changes.get("conviction_date") or case.conviction_date):
        raise HTTPException(422, "Give the conviction date")
    before = {k: (getattr(case, k).isoformat() if isinstance(getattr(case, k), date) else getattr(case, k)) for k in changes}
    for k, v in changes.items():
        setattr(case, k, v)
    audit(db, user, "update_case", "case", case.id, before=before,
          after={k: (v.isoformat() if isinstance(v, date) else v) for k, v in changes.items()}, commit=False)
    out = {}
    for p in case.persons:
        out[p.id] = _recompute(db, p, "case_update")["status"]
    return {"case_id": case.id, "statuses": out}


@router.post("/persons/{pid}/unassign")
def unassign(pid: str, user: User = Depends(require(Perm.ASSIGN_LAWYERS)), db: Session = Depends(get_db)) -> dict:
    p = assignable_person(db, user, pid)
    before = p.assigned_lawyer_id
    p.assigned_lawyer_id = None
    audit(db, user, "unassign_lawyer", "person", p.id, before=before, after=None)
    return {"ok": True}


# ------------------------------------------------------------------ lawyer accounts (DLSA / admin)
def _lawyer_view(db: Session, u: User) -> dict:
    n = db.scalar(select(func.count(Person.id)).where(Person.assigned_lawyer_id == u.id, Person.merged_into_id.is_(None)))
    return {"id": u.id, "name": u.name, "email": u.email, "active": u.active,
            "status": "active" if u.active else ("pending_approval" if u.approved_at is None else "deactivated"),
            "prisoners": n}


def _lawyer(db: Session, uid: str) -> User:
    u = db.get(User, uid)
    if u is None or u.role != Role.LAWYER:
        raise not_found()
    return u


@router.get("/lawyers")
def list_lawyers(user: User = Depends(require(Perm.ASSIGN_LAWYERS)), db: Session = Depends(get_db)) -> list[dict]:
    return [_lawyer_view(db, u) for u in db.scalars(select(User).where(User.role == Role.LAWYER).order_by(User.name))]


@router.post("/lawyers")
def create_lawyer(body: LawyerCreate, user: User = Depends(require(Perm.MANAGE_LAWYERS)), db: Session = Depends(get_db)) -> dict:
    """A new lawyer starts with ZERO prisoners. Without `approve` the account waits for approval and cannot sign in."""
    email = body.email.lower().strip()
    if "@" not in email:
        raise HTTPException(422, "A valid email is required")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "A user with this email exists")
    u = User(email=email, name=body.name.strip(), role=Role.LAWYER, hashed_password=hash_password(body.password),
             active=False, created_by=user.id)
    db.add(u)
    db.flush()
    audit(db, user, "create_user", "user", u.id, after={"email": u.email, "role": u.role, "status": "pending_approval"})
    if body.approve:
        accounts.activate(db, user, u)
    return _lawyer_view(db, u)


@router.post("/lawyers/{uid}/approve")
@router.post("/lawyers/{uid}/activate")
def activate_lawyer(uid: str, user: User = Depends(require(Perm.MANAGE_LAWYERS)), db: Session = Depends(get_db)) -> dict:
    u = _lawyer(db, uid)
    if u.active:
        raise HTTPException(409, "The account is already active")
    accounts.activate(db, user, u)
    return _lawyer_view(db, u)


@router.post("/lawyers/{uid}/deactivate")
def deactivate_lawyer(uid: str, user: User = Depends(require(Perm.MANAGE_LAWYERS)), db: Session = Depends(get_db)) -> dict:
    u = _lawyer(db, uid)
    if not u.active:
        raise HTTPException(409, "The account is already inactive")
    moved = accounts.deactivate(db, user, u, reason="lawyer left / deactivated")
    return _lawyer_view(db, u) | {"unassigned_prisoners": len(moved)}


@router.post("/admin/users/{uid}/password")
def reset_password(uid: str, body: PasswordReset, user: User = Depends(require(Perm.MANAGE_USERS)),
                   db: Session = Depends(get_db)) -> dict:
    u = db.get(User, uid)
    if u is None:
        raise not_found()
    from datetime import datetime, timezone
    u.hashed_password = hash_password(body.password)
    u.password_changed_at = datetime.now(timezone.utc)  # every session opened before the reset is signed out
    audit(db, user, "reset_password", "user", u.id)  # the password itself is never logged
    return {"ok": True}


__all__ = ["router", "has_perm"]
