"""HTTP API. Every endpoint is RBAC-checked and every view/edit/decision is audit-logged."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import settings
from app.core.rbac import (
    Perm, Role, can_see_insights, can_see_person, ensure_person_access, has_perm, not_found, require,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import create_token, current_user, hash_password, token_claims, verify_password
from app.db import get_db
from app.defense.service import refresh_insights
from app.delays.service import attribute_hearings
from app.domain import Attribution
from app.drafting.export import to_docx, to_pdf
from app.drafting.service import create_draft
from app.eligibility.engine import RULE_VERSION, urgency_rank
from app.ingestion.ocr import IngestError
from app.ingestion.pipeline import ingest
from app.models import (
    Alert, AuditLog, Case, DefenseInsight, Document, Draft, ExtractedFact, Hearing, LegalVerification, MergeEvent,
    Person, ReviewItem, RevokedToken, User,
)
from app.monitoring.alerts import alerts_for, run_nightly
from app.prediction.priority import LABEL as PRIORITY_LABEL, long_pending_probability, priority_score
from app.resolution.matcher import PairModel, resolve, score_pair
from app.resolution.merge import merge_persons, person_record, unmerge
from app.schemas import (
    AssignIn, DraftCreate, DraftPatch, FactPatch, InsightPatch, LoginIn, MergeIn, ReviewResolve, TokenOut, UserCreate,
    UserPatch, VerifyIn,
)
from app.services.eligibility import compute_for_person, current_result, load_kb

router = APIRouter(prefix="/api")


def _user(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "jail": u.jail, "district": u.district,
            "language": u.language}


# ------------------------------------------------------------------ auth & health
@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(select(1))
    return {"status": "ok", "today": settings.today().isoformat(), "demo_mode": settings.demo_mode,
            "llm": settings.llm_provider}


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    u = db.scalar(select(User).where(User.email == body.email.lower().strip()))
    if u is not None and _recent_failures(db, u.id) >= LOCKOUT_ATTEMPTS:
        audit(db, None, "login_locked", "user", u.id, detail=f"{LOCKOUT_ATTEMPTS}+ failures in {LOCKOUT_MINUTES} min",
              role="anonymous")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Too many failed sign-in attempts. Try again in {LOCKOUT_MINUTES} minutes.")
    if u is None or not u.active or not verify_password(body.password, u.hashed_password):
        # the password is never logged; the attempted account is recorded only if it exists
        reason = "unknown account" if u is None else "account disabled" if not u.active else "wrong password"
        audit(db, None, "login_failed", "user", u.id if u else None, detail=reason, role="anonymous")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    audit(db, u, "login", "user", u.id)
    # the id of this login's audit entry lets the admin screen show "this session" (entries after it)
    session_audit_id = db.scalar(select(func.max(AuditLog.id)).where(AuditLog.entity_id == u.id, AuditLog.action == "login"))
    return TokenOut(access_token=create_token(u), user=_user(u) | {"session_audit_id": session_audit_id})


LOCKOUT_ATTEMPTS, LOCKOUT_MINUTES = 5, 15


def _recent_failures(db: Session, uid: str) -> int:
    since = datetime.now(timezone.utc) - timedelta(minutes=LOCKOUT_MINUTES)
    last_ok = db.scalar(select(func.max(AuditLog.id)).where(AuditLog.entity_id == uid, AuditLog.action == "login"))
    q = select(func.count(AuditLog.id)).where(AuditLog.entity_id == uid, AuditLog.action == "login_failed",
                                              AuditLog.ts >= since)
    if last_ok:
        q = q.where(AuditLog.id > last_ok)
    return db.scalar(q) or 0


@router.post("/auth/logout")
def logout(creds: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
           user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    jti = token_claims(creds).get("jti")
    if jti and db.get(RevokedToken, jti) is None:
        db.add(RevokedToken(jti=jti, user_id=user.id))  # this token is refused from now on, even before it expires
    audit(db, user, "logout", "user", user.id)
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return _user(user)


# ------------------------------------------------------------------ prisoners
def _scoped_persons(db: Session, user: User) -> list[Person]:
    q = select(Person).where(Person.merged_into_id.is_(None))
    role = Role(user.role)
    if role == Role.LAWYER:
        q = q.where(Person.assigned_lawyer_id == user.id)
    elif role == Role.JAIL_STAFF:
        q = q.where(Person.jail == user.jail)
    elif role == Role.DLSA_ADMIN:
        q = q.where(Person.district == user.district)
    elif role != Role.SYSTEM_ADMIN:
        return []
    return list(db.scalars(q))


def _fresh_result(db: Session, p: Person, kb=None):
    """The stored result, recomputed first if it was computed for an earlier date or an older
    legal-data version — a stale result is never shown as current."""
    r = current_result(db, p.id)
    if r is not None and r.result.get("as_of") == settings.today().isoformat() and r.rule_version == RULE_VERSION:
        kb = kb or load_kb(db)
        if r.legal_data_version == kb.version:
            return r
    return compute_for_person(db, p, kb).row


def _summary(db: Session, p: Person, with_priority: bool = False, kb=None) -> dict:
    r = _fresh_result(db, p, kb)
    cases = r.result["cases"] if r else []
    urgency = min((c.get("urgency") or c["status"] for c in cases), key=urgency_rank, default="NOT_APPLICABLE") if cases else "NOT_APPLICABLE"
    for c in cases:
        for f in c.get("findings", []):
            if urgency_rank(f["code"]) < urgency_rank(urgency):
                urgency = f["code"]
    out = {"id": p.id, "name": p.canonical_name, "relative": (p.relative_name_variants or [None])[0], "relation": p.relation,
           "gender": p.gender, "jail": p.jail, "district": p.district, "vulnerability": p.vulnerability,
           "status": r.status if r else None, "urgency": urgency, "eligible_from_date": r.eligible_from_date.isoformat()
           if r and r.eligible_from_date else None, "days_overdue": r.days_overdue if r else None,
           "custody_days": max((c.get("custody_days", 0) for c in cases), default=0),
           "needs_verification": sum(len(c.get("needs_verification", [])) for c in cases),
           "cases": [{"id": c.id, "cnr": c.cnr, "status": c.status, "charges": [f"{ch.act} {ch.section}" for ch in c.charges]}
                     for c in p.cases], "assigned_lawyer_id": p.assigned_lawyer_id,
           "demo_label": (p.identifiers or {}).get("demo_label"), "as_of": r.result.get("as_of") if r else None,
           "intake": (p.identifiers or {}).get("intake", "verified")}
    if with_priority:
        ch = next((ch for c in p.cases if c.status in ("investigation", "charge_sheet_filed", "trial") for ch in c.charges), None)
        pl = long_pending_probability(ch.act, ch.section, "KA", p.district or "", p.cases[0].fir_year or 2024) if ch and p.cases else None
        out["priority"] = priority_score(urgency, p.vulnerability, pl, r.days_overdue if r else None)
        out["delay_pattern"] = {"p_pending_3y": round(pl, 2) if pl is not None else None, "label": PRIORITY_LABEL}
    return out


@router.get("/persons")
def list_persons(response: Response, user: User = Depends(require(Perm.VIEW_PRISONER)), db: Session = Depends(get_db),
                 q: str | None = Query(None, max_length=200), status_filter: str | None = Query(None, alias="status"),
                 limit: int | None = Query(None, ge=1, le=1000), offset: int = Query(0, ge=0)) -> list[dict]:
    # Scope is applied FIRST (in SQL); search, filters and pagination only ever narrow that scoped set.
    persons = _scoped_persons(db, user)
    q = (q or "").strip() or None
    if q:
        from app.resolution.normalise import phonetic_key
        k = phonetic_key(q)
        persons = [p for p in persons if q.lower() in p.canonical_name.lower()
                   or any(q.lower() in v.lower() for v in p.name_variants or [])
                   or (len(k) >= 3 and k in phonetic_key(p.canonical_name))]
    kb = load_kb(db)
    rows = [_summary(db, p, with_priority=True, kb=kb) for p in persons]
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter or r["urgency"] == status_filter]
    rows.sort(key=lambda r: (urgency_rank(r["urgency"]), -(r.get("priority") or 0), r["name"], r["id"]))
    response.headers["X-Total-Count"] = str(len(rows))
    total = len(rows)
    rows = rows[offset: offset + limit if limit else None]
    if q or status_filter:
        audit(db, user, "search", "person", None, detail=f"query={q!r} status={status_filter!r}: {total} match(es)")
    else:
        audit(db, user, "list", "person", None, detail=f"{total} rows")
    return rows


@router.get("/persons/{pid}")
def get_person(pid: str, user: User = Depends(require(Perm.VIEW_PRISONER)), db: Session = Depends(get_db)) -> dict:
    p = ensure_person_access(user, db.get(Person, pid), db)
    r = _fresh_result(db, p)
    docs = db.scalars(select(Document).where(Document.person_id == p.id).order_by(Document.created_at)).all()
    facts = db.scalars(select(ExtractedFact).where(ExtractedFact.person_id == p.id)).all()
    kb = load_kb(db)
    audit(db, user, "view", "person", p.id)
    lawyer = db.get(User, p.assigned_lawyer_id) if p.assigned_lawyer_id else None
    return {
        **_summary(db, p, kb=kb), "dob": p.dob.isoformat() if p.dob else None, "name_variants": p.name_variants,
        "assigned_lawyer": lawyer.name if lawyer else None, "addresses": p.addresses,
        "identifiers": {k: v for k, v in p.identifiers.items() if k not in ("expected_status",)},
        "can_see_insights": can_see_insights(user, p), "can_draft": has_perm(user, Perm.CREATE_DRAFTS),
        "eligibility": r.result, "rule_version": r.rule_version, "legal_data_version": r.legal_data_version,
        "computed_at": _ts(r.computed_at),
        "case_details": [{
            "id": c.id, "cnr": c.cnr, "case_numbers": c.case_numbers, "court": c.court, "status": c.status,
            "fir_number": c.fir_number, "police_station": c.police_station, "offence_date": _iso(c.offence_date),
            "first_remand_date": _iso(c.first_remand_date), "charge_sheet_date": _iso(c.charge_sheet_date),
            "bail_granted_date": _iso(c.bail_granted_date), "fir_date": _iso(c.fir_date),
            "default_bail_application_date": _iso(c.default_bail_application_date),
            "acquittal_date": _iso(c.acquittal_date), "conviction_date": _iso(c.conviction_date),
            "charges": [{"act": ch.act, "section": ch.section, "modifier": ch.modifier, "confidence": ch.confidence,
                         "record": _record_view(kb, ch.act, ch.section)} for ch in c.charges],
            "hearings": [{"id": h.id, "date": _iso(h.date), "next_date": _iso(h.next_date), "reason": h.reason_text,
                          "attribution": h.delay_attribution, "confidence": h.attribution_confidence,
                          "method": h.attribution_method, "verified": h.reviewer_verified} for h in c.hearings],
        } for c in p.cases],
        "custody_events": [{"id": e.id, "type": e.type, "start": _iso(e.start), "end": _iso(e.end), "case_id": e.case_id,
                            "jail": e.jail, "confidence": e.confidence, "primary": e.is_primary_source} for e in
                           sorted(p.custody_events, key=lambda e: e.start)],
        "convictions": [{"case_id": cv.case_id, "date": _iso(cv.date), "status": cv.status, "offence": cv.offence}
                        for cv in p.convictions],
        "documents": [{"id": d.id, "filename": d.filename, "doc_type": d.doc_type, "language": d.language,
                       "status": d.status, "warnings": d.warnings, "case_id": d.case_id} for d in docs],
        "facts": [_fact(f) for f in facts],
    }


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def _ts(dt: datetime | None) -> str | None:
    """Timestamps are stored in UTC; SQLite drops the zone, so re-attach it before sending (otherwise the
    browser would read them as local time and show them 5½ hours off in India)."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _record_view(kb, act: str, section: str) -> dict | None:
    rec = kb.get(act, section)
    if rec is None:
        return None
    return {"key": rec.key, "title": rec.title, "max": str(rec.effective_max) if rec.kind == "offence" else None,
            "verified": rec.verified, "verified_by": rec.verified_by, "source": rec.source, "compoundable": rec.compoundable,
            "bailable": rec.bailable, "special_law": rec.special_law}


def _fact(f: ExtractedFact) -> dict:
    return {"id": f.id, "document_id": f.document_id, "case_id": f.case_id, "field": f.field, "value": f.effective_value,
            "original_value": f.value, "page": f.page, "span_start": f.span_start, "span_end": f.span_end,
            "span_text": f.span_text, "method": f.method, "confidence": f.confidence, "review_status": f.review_status,
            "notes": f.notes}


@router.post("/persons/{pid}/recompute")
def recompute(pid: str, user: User = Depends(require(Perm.VIEW_PRISONER)), db: Session = Depends(get_db)) -> dict:
    p = ensure_person_access(user, db.get(Person, pid), db)
    out = compute_for_person(db, p, commit=False)
    alerts_for(db, p, out, settings.today(), reason="recompute")
    audit(db, user, "recompute", "eligibility", p.id,
          after={"status": out.row.status, "changed": out.changed, "previous": out.previous_status})
    return {"status": out.row.status, "changed": out.changed, "previous_status": out.previous_status,
            "computed_at": _ts(out.row.computed_at)}


@router.post("/persons/{pid}/assign")
def assign(pid: str, body: AssignIn, user: User = Depends(require(Perm.ASSIGN_LAWYERS)), db: Session = Depends(get_db)) -> dict:
    from app.api.lifecycle import assignable_person, intake_status
    p = assignable_person(db, user, pid)
    if intake_status(p) != "verified":
        raise HTTPException(409, "This prisoner's details are still waiting for the reviewer's verification — "
                                 "assign a lawyer after the review.")
    lawyer = db.get(User, body.lawyer_id)
    if lawyer is None or lawyer.role != Role.LAWYER or not lawyer.active:
        raise HTTPException(400, "Not an active legal-aid lawyer")
    before = p.assigned_lawyer_id
    if before == lawyer.id:
        return {"ok": True, "unchanged": True}
    p.assigned_lawyer_id = lawyer.id
    # the previous lawyer loses access on their very next request (scope is checked per request, not cached)
    audit(db, user, "reassign_lawyer" if before else "assign_lawyer", "person", p.id, before=before, after=lawyer.id)
    return {"ok": True}


# ------------------------------------------------------------------ documents & facts
@router.post("/persons/{pid}/documents")
async def upload(pid: str, file: UploadFile = File(...), case_id: str | None = Form(None),
                 user: User = Depends(require(Perm.UPLOAD_DOCUMENTS)), db: Session = Depends(get_db)) -> dict:
    p = ensure_person_access(user, db.get(Person, pid), db)
    if Role(user.role) == Role.LAWYER and p.assigned_lawyer_id != user.id:  # (already implied by scope; explicit)
        raise not_found()
    if case_id and not any(c.id == case_id for c in p.cases):
        raise HTTPException(422, "The selected case does not belong to this prisoner.")
    data = await file.read()
    try:
        doc, created = ingest(db, data, file.filename or "upload.bin", user, p, case_id,
                              use_llm=settings.llm_provider != "none")
    except IngestError as e:
        raise HTTPException(422, str(e))
    if not created:
        return {"id": doc.id, "duplicate": True, "message": "This exact file was already uploaded for this prisoner."}
    out = compute_for_person(db, p)
    alerts_for(db, p, out, settings.today(), reason="document")
    refresh_insights(db, p)
    db.commit()
    return {"id": doc.id, "duplicate": False, "doc_type": doc.doc_type, "warnings": doc.warnings,
            "status": out.row.status, "result_changed": out.changed and out.previous_status != out.row.status}


@router.get("/documents/{did}")
def get_document(did: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    d = db.get(Document, did)
    if d is None:
        raise not_found()
    if not has_perm(user, Perm.REVIEW_QUEUE):  # reviewers read documents through the review queue
        ensure_person_access(user, db.get(Person, d.person_id) if d.person_id else None, db, "document", d.id)
    facts = db.scalars(select(ExtractedFact).where(ExtractedFact.document_id == d.id)).all()
    audit(db, user, "view", "document", d.id)
    return {"id": d.id, "filename": d.filename, "doc_type": d.doc_type, "doc_type_confidence": d.doc_type_confidence,
            "language": d.language, "scripts": d.scripts, "warnings": d.warnings, "text": d.text,
            "pages": [{"page": pg["page"], "confidence": pg["confidence"], "warnings": pg.get("warnings", [])} for pg in d.pages],
            "facts": [_fact(f) for f in facts]}


@router.patch("/facts/{fid}")
def patch_fact(fid: str, body: FactPatch, user: User = Depends(require(Perm.CORRECT_FACTS)), db: Session = Depends(get_db)) -> dict:
    f = db.get(ExtractedFact, fid)
    if f is None:
        raise not_found()
    p = db.get(Person, f.person_id) if f.person_id else None
    if Role(user.role) == Role.LAWYER:
        ensure_person_access(user, p, db, "fact", f.id)
    if body.action == "correct" and (body.value is None or str(body.value).strip() == ""):
        raise HTTPException(422, "A corrected value is required.")
    before = {"value": f.effective_value, "status": f.review_status}
    f.review_status = {"confirm": "confirmed", "correct": "corrected", "reject": "rejected"}[body.action]
    if body.action == "correct":
        f.corrected_value = body.value
    f.reviewer_id = user.id
    f.confidence = 1.0 if body.action != "reject" else f.confidence
    if body.note:
        f.notes = f.notes + [f"{user.role}: {body.note}"]
    item = db.scalar(select(ReviewItem).where(ReviewItem.kind == "extraction", ReviewItem.ref_id == f.id))
    if item:
        item.status, item.resolved_by, item.resolution = "resolved", user.id, {"action": body.action, "value": body.value}
    audit(db, user, f"fact_{body.action}", "fact", f.id, before=before, after={"value": f.effective_value, "status": f.review_status})
    if p:
        out = compute_for_person(db, p, commit=False)  # a corrected/rejected fact can change what needs verification
        alerts_for(db, p, out, settings.today(), reason="review")
        refresh_insights(db, p)
    db.commit()
    return _fact(f)


# ------------------------------------------------------------------ defense insights (lawyer-only)
@router.get("/persons/{pid}/insights")
def insights(pid: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    p = db.get(Person, pid)
    if p is None or p.merged_into_id or (not can_see_person(user, p) and not can_see_insights(user, p)):
        if p is not None:
            audit(db, user, "denied", "defense_insights", p.id, detail="outside assignment/scope")
        raise not_found()
    if not has_perm(user, Perm.VIEW_DEFENSE_INSIGHTS) or not can_see_insights(user, p):
        audit(db, user, "denied", "defense_insights", p.id)
        raise HTTPException(403, "Defense Insights are visible only to the assigned lawyer")
    rows = db.scalars(select(DefenseInsight).where(DefenseInsight.person_id == p.id).order_by(DefenseInsight.rank_score.desc())).all()
    audit(db, user, "view", "defense_insights", p.id, detail=f"{len(rows)} insights")
    return {"disclaimer": "Decision support for a qualified lawyer. Not legal advice. Verify all sections and citations.",
            "insights": [{"id": i.id, "case_id": i.case_id, "code": i.code, "category": i.category, "severity": i.severity,
                          "title": i.title, "explanation": i.explanation, "next_steps": i.next_steps, "evidence": i.evidence,
                          "legal_basis": i.legal_basis, "judgments": i.judgments, "rank_score": i.rank_score,
                          "status": i.status} for i in rows]}


@router.patch("/insights/{iid}")
def decide_insight(iid: str, body: InsightPatch, user: User = Depends(require(Perm.DECIDE_DEFENSE_INSIGHTS)),
                   db: Session = Depends(get_db)) -> dict:
    i = db.get(DefenseInsight, iid)
    if i is None:
        raise not_found()
    if not can_see_insights(user, db.get(Person, i.person_id)):
        audit(db, user, "denied", "defense_insight", i.id)
        raise not_found()
    before = i.status
    i.status = body.status
    audit(db, user, f"insight_{body.status}", "defense_insight", i.id, before=before, after=body.status, detail=body.note)
    return {"id": i.id, "status": i.status}


# ------------------------------------------------------------------ drafts
@router.post("/persons/{pid}/drafts")
def new_draft(pid: str, body: DraftCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    p = ensure_person_access(user, db.get(Person, pid), db, "draft")
    case = db.get(Case, body.case_id)
    if case is None or case not in p.cases:
        raise HTTPException(404, "Case not found for this prisoner")
    lawyer = has_perm(user, Perm.CREATE_DRAFTS) and can_see_insights(user, p)
    superintendent = has_perm(user, Perm.SUPERINTENDENT_APPLICATION) and body.type == "section_479"
    if not (lawyer or superintendent):
        audit(db, user, "denied", "draft", p.id, detail=f"create {body.type}")
        raise HTTPException(403, "Your role cannot create this draft")
    d = create_draft(db, p, case, body.type, body.language, user, use_llm=body.use_llm and settings.llm_provider != "none")
    if not lawyer:  # superintendent's application must never carry privileged strategy
        d.grounding = [s for s in d.grounding if not any(src["type"] == "insight" for src in s["sources"])]
        d.content = "\n\n".join(s["text"] for s in d.grounding)
    db.commit()
    return _draft(d)


def _draft(d: Draft) -> dict:
    return {"id": d.id, "person_id": d.person_id, "case_id": d.case_id, "type": d.type, "language": d.language,
            "content": d.content, "grounding": d.grounding, "verifier_report": d.verifier_report, "status": d.status,
            "versions": d.versions, "created_at": _ts(d.created_at)}


def _draft_visible(db: Session, user: User, person: Person, d: Draft) -> bool:
    """The assigned lawyer (and admin) see every draft. Anyone else in scope (jail staff, DLSA) sees only
    drafts that were NOT prepared by a lawyer and carry no privileged Defense-Insight grounding."""
    if can_see_insights(user, person):
        return True
    author = db.get(User, d.created_by) if d.created_by else None
    lawyer_work = author is not None and author.role in (Role.LAWYER, Role.SYSTEM_ADMIN)
    privileged = any(src["type"] == "insight" for s in d.grounding for src in s["sources"])
    return not lawyer_work and not privileged


def _draft_access(db: Session, user: User, did: str) -> Draft:
    d = db.get(Draft, did)
    if d is None:
        raise not_found()
    p = ensure_person_access(user, db.get(Person, d.person_id), db, "draft", d.id)
    if not _draft_visible(db, user, p, d):
        audit(db, user, "denied", "draft", d.id, detail="privileged lawyer draft")
        raise not_found()
    return d


@router.get("/persons/{pid}/drafts")
def list_drafts(pid: str, user: User = Depends(require(Perm.VIEW_PRISONER)), db: Session = Depends(get_db)) -> list[dict]:
    p = ensure_person_access(user, db.get(Person, pid), db, "draft")
    rows = db.scalars(select(Draft).where(Draft.person_id == p.id).order_by(Draft.created_at.desc())).all()
    rows = [r for r in rows if _draft_visible(db, user, p, r)]
    audit(db, user, "list", "draft", p.id)
    return [_draft(r) for r in rows]


@router.get("/drafts/{did}")
def get_draft(did: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    d = _draft_access(db, user, did)
    audit(db, user, "view", "draft", d.id)
    return _draft(d)


@router.patch("/drafts/{did}")
def edit_draft(did: str, body: DraftPatch, user: User = Depends(require(Perm.EDIT_DRAFTS)), db: Session = Depends(get_db)) -> dict:
    d = _draft_access(db, user, did)
    if not can_see_insights(user, db.get(Person, d.person_id)):
        audit(db, user, "denied", "draft", d.id, detail="edit")
        raise HTTPException(403, "Only the assigned lawyer can edit this draft")
    before = {"status": d.status}
    edited = body.content is not None and body.content != d.content
    if edited:
        if not body.content.strip():
            raise HTTPException(422, "A draft cannot be empty.")
        d.versions = d.versions + [{"at": datetime.now(timezone.utc).isoformat(), "by": user.id, "content": d.content}]
        d.content = body.content
        d.verifier_report = {**d.verifier_report, "lawyer_edited": True}
        audit(db, user, "edit_draft", "draft", d.id, before=before, after={"status": d.status, "edited": True}, commit=False)
    if body.status and body.status != d.status:
        d.status = body.status
        audit(db, user, {"approved": "approve_draft", "rejected": "reject_draft"}.get(body.status, "reopen_draft"), "draft",
              d.id, before=before, after={"status": d.status}, commit=False)
    db.commit()
    return _draft(d)


@router.get("/drafts/{did}/export")
def export_draft(did: str, format: str = Query("docx", pattern="^(docx|pdf)$"), user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> Response:
    d = _draft_access(db, user, did)
    paras = d.content.split("\n\n")
    title = d.verifier_report.get("title", d.type)
    disc = d.verifier_report.get("disclaimer", "")
    audit(db, user, "export_draft", "draft", d.id, detail=format)
    if format == "pdf":
        return Response(to_pdf(title, paras, disc, d.language), media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{d.type}_{d.language}.pdf"'})
    return Response(to_docx(title, paras, disc, d.language),
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'inline; filename="{d.type}_{d.language}.docx"'})


# ------------------------------------------------------------------ review queue
@router.get("/review")
def review_queue(user: User = Depends(require(Perm.REVIEW_QUEUE)), db: Session = Depends(get_db), kind: str | None = None) -> list[dict]:
    q = select(ReviewItem).where(ReviewItem.status == "open").order_by(ReviewItem.confidence, ReviewItem.created_at)
    if kind:
        q = q.where(ReviewItem.kind == kind)
    rows = db.scalars(q.limit(300)).all()
    audit(db, user, "list", "review_queue", None, detail=f"{len(rows)} items")
    return [{"id": r.id, "kind": r.kind, "ref_id": r.ref_id, "title": r.title, "payload": r.payload, "confidence": r.confidence,
             "created_at": _ts(r.created_at), "context": _review_context(db, r)} for r in rows]


def _review_context(db: Session, r: ReviewItem) -> dict:
    """Plain facts the reviewer needs to understand an item: whose record, which document, which value."""
    ctx: dict = {}
    doc = person = None
    if r.kind == "extraction":
        f = db.get(ExtractedFact, r.ref_id)
        if f is not None:
            ctx.update(field=f.field, value=f.value, page=f.page, span_text=f.span_text, notes=list(f.notes or []))
            doc = db.get(Document, f.document_id)
            person = db.get(Person, f.person_id) if f.person_id else None
    elif r.kind in ("document", "document_type", "document_mismatch"):
        doc = db.get(Document, r.ref_id)
        person = db.get(Person, doc.person_id) if doc is not None and doc.person_id else None
    elif r.kind == "delay_attribution":
        h = db.get(Hearing, r.ref_id)
        if h is not None:
            ctx.update(hearing_date=h.date.isoformat(), next_date=h.next_date.isoformat() if h.next_date else None)
            case = db.get(Case, h.case_id)
            names = [x.canonical_name for x in (case.persons if case else [])]
            if names:
                ctx["person"] = ", ".join(names)
    elif r.kind == "new_prisoner":
        person = db.get(Person, r.ref_id)
    elif r.kind == "identity_match":
        a, b = db.get(Person, r.payload.get("a")), db.get(Person, r.payload.get("b"))
        ctx["pair"] = [{"name": x.canonical_name, "relative": ", ".join(x.relative_name_variants or []), "jail": x.jail,
                        "dob": x.dob.isoformat() if x.dob else None} for x in (a, b) if x is not None]
    if doc is not None:
        ctx.update(filename=doc.filename, doc_type=doc.doc_type)
    if person is not None:
        ctx.update(person=person.canonical_name, jail=person.jail)
    return ctx


@router.post("/review/{rid}/resolve")
def resolve_item(rid: str, body: ReviewResolve, user: User = Depends(require(Perm.REVIEW_QUEUE)), db: Session = Depends(get_db)) -> dict:
    item = db.get(ReviewItem, rid)
    if item is None or item.status != "open":
        raise HTTPException(404, "Review item not found or already resolved")
    allowed = {"extraction": {"confirm", "correct", "reject"}, "delay_attribution": {"confirm", "set_attribution"},
               "identity_match": {"link", "not_same"}, "new_prisoner": {"confirm", "reject"}}.get(item.kind, {"confirm", "reject"})
    if body.action not in allowed:
        raise HTTPException(422, f"Action '{body.action}' does not apply to a {item.kind.replace('_', ' ')} item")
    if body.action == "set_attribution" and body.value not in {a.value for a in Attribution}:
        raise HTTPException(422, "Attribution must be one of: " + ", ".join(a.value for a in Attribution))
    if body.action == "correct" and (body.value is None or str(body.value).strip() == ""):
        raise HTTPException(422, "A corrected value is required.")
    persons: list[Person] = []
    if item.kind == "extraction" and body.action in ("confirm", "correct", "reject"):
        f = db.get(ExtractedFact, item.ref_id)
        if f:
            f.review_status = {"confirm": "confirmed", "correct": "corrected", "reject": "rejected"}[body.action]
            f.corrected_value = body.value if body.action == "correct" else f.corrected_value
            f.reviewer_id, f.confidence = user.id, 1.0 if body.action != "reject" else f.confidence
            persons = [db.get(Person, f.person_id)] if f.person_id else []
    elif item.kind == "delay_attribution":
        h = db.get(Hearing, item.ref_id)
        if h:
            before_attr = h.delay_attribution
            h.delay_attribution = body.value if body.action == "set_attribution" else item.payload.get("suggested", "unknown")
            h.reviewer_verified, h.attribution_confidence, h.attribution_method = True, 1.0, "reviewer"
            audit(db, user, "set_delay_attribution", "hearing", h.id, before=before_attr, after=h.delay_attribution,
                  commit=False)
            case = db.get(Case, h.case_id)
            persons = list(case.persons) if case else []  # every co-accused on the case is recomputed
    elif item.kind == "new_prisoner":
        p = db.get(Person, item.ref_id)
        if p is not None:
            state = "verified" if body.action == "confirm" else "returned"
            p.identifiers = {**(p.identifiers or {}), "intake": state}
            audit(db, user, "verify_intake" if state == "verified" else "return_intake", "person", p.id,
                  after={"intake": state}, detail=body.note, commit=False)
    elif item.kind == "identity_match" and body.action in ("link", "not_same"):
        a, b = db.get(Person, item.payload["a"]), db.get(Person, item.payload["b"])
        if body.action == "link":
            if not (a and b) or a.merged_into_id or b.merged_into_id:
                raise HTTPException(409, "One of these records was already merged; refresh the queue.")
            merge_persons(db, a, b, user, item.confidence)
            persons = [a]
    item.status, item.resolved_by = "resolved", user.id
    item.resolution = {"action": body.action, "value": body.value, "note": body.note}
    audit(db, user, "review_resolve", item.kind, item.ref_id, after=item.resolution)
    for person in persons:
        if person is None:
            continue
        out = compute_for_person(db, person, commit=False)
        alerts_for(db, person, out, settings.today(), reason="review")
        refresh_insights(db, person)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ entity resolution
@router.post("/resolution/scan")
def scan_duplicates(user: User = Depends(require(Perm.MERGE_PERSONS)), db: Session = Depends(get_db)) -> dict:
    persons = db.scalars(select(Person).where(Person.merged_into_id.is_(None))).all()
    res = resolve([person_record(p) for p in persons], PairModel())
    queued = 0
    for s in res.review + res.links:  # links are ALSO queued in the product: persons are never auto-merged silently
        a, b = sorted((s.a, s.b))
        if db.scalar(select(ReviewItem).where(ReviewItem.kind == "identity_match", ReviewItem.ref_id == f"{a}:{b}")) is None:
            pa, pb = db.get(Person, a), db.get(Person, b)
            db.add(ReviewItem(kind="identity_match", ref_id=f"{a}:{b}", confidence=s.p,
                              title=f"Same person? {pa.canonical_name} ↔ {pb.canonical_name} (score {s.p:.2f})",
                              payload={"a": a, "b": b, "features": s.features, "vetoes": s.vetoes, "decision": s.decision}))
            queued += 1
    audit(db, user, "resolution_scan", "person", None, detail=f"{queued} candidate pairs")
    return {"candidates": queued, "auto_link_candidates": len(res.links), "review": len(res.review)}


@router.post("/resolution/merge")
def merge(body: MergeIn, user: User = Depends(require(Perm.MERGE_PERSONS)), db: Session = Depends(get_db)) -> dict:
    keep, other = db.get(Person, body.keep_id), db.get(Person, body.other_id)
    if keep is None or other is None:
        raise not_found()
    try:
        ev = merge_persons(db, keep, other, user,
                           body.score or score_pair(person_record(keep), person_record(other), PairModel()).p)
    except ValueError as e:
        raise HTTPException(409, str(e))
    compute_for_person(db, keep)
    return {"merge_event": ev.id}


@router.post("/resolution/unmerge/{eid}")
def do_unmerge(eid: str, user: User = Depends(require(Perm.MERGE_PERSONS)), db: Session = Depends(get_db)) -> dict:
    ev = db.get(MergeEvent, eid)
    if ev is None:
        raise not_found()
    try:
        other = unmerge(db, ev, user)
    except ValueError as e:
        raise HTTPException(409, str(e))
    compute_for_person(db, other)
    compute_for_person(db, db.get(Person, ev.kept_person_id))
    return {"restored": other.id}


@router.get("/resolution/merges")
def merges(user: User = Depends(require(Perm.MERGE_PERSONS)), db: Session = Depends(get_db)) -> list[dict]:
    names = {p.id: p.canonical_name for p in db.scalars(select(Person))}
    return [{"id": m.id, "kept": m.kept_person_id, "merged": m.merged_person_id, "kept_name": names.get(m.kept_person_id),
             "merged_name": names.get(m.merged_person_id), "score": m.score, "undone": m.undone,
             "created_at": _ts(m.created_at)} for m in db.scalars(select(MergeEvent).order_by(MergeEvent.created_at.desc()))]


# ------------------------------------------------------------------ alerts
@router.get("/alerts")
def list_alerts(user: User = Depends(require(Perm.ACK_ALERTS)), db: Session = Depends(get_db), open_only: bool = True) -> list[dict]:
    ids = {p.id: p for p in _scoped_persons(db, user)}
    q = select(Alert).where(Alert.person_id.in_(ids)).order_by(Alert.created_at.desc())
    if open_only:
        q = q.where(Alert.acknowledged_at.is_(None))
    rows = db.scalars(q).all()
    audit(db, user, "list", "alert", None, detail=f"{len(rows)} alerts")
    return [{"id": a.id, "person_id": a.person_id, "person": ids[a.person_id].canonical_name, "kind": a.kind,
             "severity": a.severity, "message": a.message, "created_at": _ts(a.created_at), "escalated": a.escalated,
             "acknowledged_at": _ts(a.acknowledged_at)} for a in rows]


@router.post("/alerts/{aid}/ack")
def ack(aid: str, user: User = Depends(require(Perm.ACK_ALERTS)), db: Session = Depends(get_db)) -> dict:
    a = db.get(Alert, aid)
    if a is None:
        raise not_found()
    ensure_person_access(user, db.get(Person, a.person_id), db, "alert", a.id)
    a.acknowledged_at, a.acknowledged_by = datetime.now(timezone.utc), user.id
    audit(db, user, "ack_alert", "alert", a.id)
    return {"ok": True}


# ------------------------------------------------------------------ dashboards
@router.get("/dashboard/dlsa")
def dlsa_dashboard(user: User = Depends(require(Perm.DISTRICT_DASHBOARD)), db: Session = Depends(get_db)) -> dict:
    persons = db.scalars(select(Person).where(Person.merged_into_id.is_(None))).all()
    if Role(user.role) == Role.DLSA_ADMIN:
        persons = [p for p in persons if p.district == user.district]
    by_district: dict[str, dict[str, Any]] = {}
    lawyers: dict[str, int] = {}
    kb = load_kb(db)
    for p in persons:
        s = _summary(db, p, kb=kb)
        d = by_district.setdefault(p.district or "Unknown", {"district": p.district, "prisoners": 0, "overdue": 0, "critical": 0,
                                                            "review": 0, "urgent_default_bail": 0, "detention_days": [],
                                                            "vulnerable": 0, "women": 0})
        d["prisoners"] += 1
        d["overdue"] += int(s["status"] == "ELIGIBLE")
        d["critical"] += int(s["urgency"].startswith("CRITICAL"))
        d["review"] += int(s["status"] in ("REVIEW", "REVIEW_MULTIPLE_CASES"))
        d["urgent_default_bail"] += int(s["urgency"] == "URGENT_DEFAULT_BAIL")
        d["unassigned"] = d.get("unassigned", 0) + int(not p.assigned_lawyer_id)
        d["detention_days"].append(s["custody_days"])
        d["vulnerable"] += int(bool(p.vulnerability))
        d["women"] += int(p.gender == "female")
        if p.assigned_lawyer_id:
            lawyers[p.assigned_lawyer_id] = lawyers.get(p.assigned_lawyer_id, 0) + 1
    for d in by_district.values():
        days = d.pop("detention_days")
        d["avg_detention_days"] = round(sum(days) / len(days)) if days else 0
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(lawyers)))}
    audit(db, user, "view", "dashboard_dlsa", user.district)
    open_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.acknowledged_at.is_(None),
                                                                 Alert.person_id.in_([p.id for p in persons])))
    escalated = db.scalar(select(func.count(Alert.id)).where(Alert.escalated.is_(True),
                                                              Alert.person_id.in_([p.id for p in persons])))
    return {"districts": sorted(by_district.values(), key=lambda d: -d["overdue"] - d["critical"]),
            "lawyer_workload": [{"lawyer": names.get(k, k), "prisoners": v} for k, v in sorted(lawyers.items(), key=lambda x: -x[1])],
            "open_alerts": open_alerts, "escalated_alerts": escalated,
            "lawyers": [{"id": u.id, "name": u.name} for u in db.scalars(select(User).where(User.role == "legal_aid_lawyer"))]}


@router.get("/dashboard/reviewer")
def reviewer_dashboard(user: User = Depends(require(Perm.REVIEW_QUEUE)), db: Session = Depends(get_db)) -> dict:
    counts = dict(db.execute(select(ReviewItem.kind, func.count()).where(ReviewItem.status == "open").group_by(ReviewItem.kind)).all())
    return {"open": counts, "resolved": db.scalar(select(func.count()).where(ReviewItem.status == "resolved"))}


# ------------------------------------------------------------------ legal data (admin)
@router.get("/legal/records")
def legal_records(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    kb = load_kb(db)
    recs = [{"key": r.key, "act": r.act, "section": r.section, "title": r.title, "punishment_summary": r.punishment_summary,
             "max": str(r.effective_max) if r.kind == "offence" else None, "kind": r.kind, "verified": r.verified,
             "verified_by": r.verified_by, "source": r.source, "notes": r.notes, "special_law": r.special_law,
             "compoundable": r.compoundable, "categories": r.offence_categories} for r in kb.records.values()]
    rules = [{"key": f"rule:{r.name}", "ref": r.ref, "verified": r.verified} for r in kb.rules.values()]
    demo = db.scalar(select(func.count()).select_from(LegalVerification).where(
        LegalVerification.verified.is_(True), LegalVerification.verified_by.like("DEMO SEED%")))
    return {"version": kb.version, "records": recs, "rules": rules, "demo_verified_only": demo,
            "unverified": sum(1 for r in recs if not r["verified"]) + sum(1 for r in rules if not r["verified"])}


@router.post("/legal/records/{key}/verify")
def verify_record(key: str, body: VerifyIn, user: User = Depends(require(Perm.MANAGE_LEGAL_DATA)), db: Session = Depends(get_db)) -> dict:
    kb = load_kb(db)
    if key not in kb.records and not (key.startswith("rule:") and key[5:] in kb.rules):
        raise HTTPException(404, "Unknown legal record")
    row = db.get(LegalVerification, key) or LegalVerification(record_key=key)
    before = {"verified": row.verified, "by": row.verified_by} if row.record_key and row.verified is not None else None
    row.verified, row.verified_by, row.note = body.verified, f"{user.name} <{user.email}>", body.note
    row.verified_at = datetime.now(timezone.utc)
    db.merge(row)
    audit(db, user, "verify_legal_record", "legal_record", key, before=before, after={"verified": body.verified, "note": body.note})
    return {"key": key, "verified": body.verified, "legal_data_version": load_kb(db).version}


# ------------------------------------------------------------------ admin
@router.get("/admin/audit")
def audit_log(user: User = Depends(require(Perm.VIEW_AUDIT)), db: Session = Depends(get_db), entity_id: str | None = None,
              action: str | None = None, user_id: str | None = None, entity_type: str | None = None,
              after_id: int | None = Query(None, ge=0), limit: int = Query(200, ge=1, le=1000)) -> list[dict]:
    """Newest first. `after_id` returns only entries newer than a known id (e.g. "this session")."""
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    if action:
        q = q.where(AuditLog.action == action)
    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if after_id is not None:
        q = q.where(AuditLog.id > after_id)
    rows = list(db.scalars(q))
    people = {u.id: u for u in db.scalars(select(User).where(User.id.in_({a.user_id for a in rows if a.user_id})))}
    # reading the audit log is itself audited, but AFTER the query so the entry does not pollute this page
    audit(db, user, "view", "audit_log", None, detail=f"{len(rows)} entries")
    return [{"id": a.id, "ts": _ts(a.ts), "user_id": a.user_id, "user_name": people[a.user_id].name if a.user_id in people else None,
             "user_email": people[a.user_id].email if a.user_id in people else None, "role": a.role, "action": a.action,
             "entity_type": a.entity_type, "entity_id": a.entity_id, "detail": a.detail, "before": a.before, "after": a.after,
             "outcome": "denied" if a.action in ("denied", "access_denied", "login_failed") else "ok"} for a in rows]


@router.get("/admin/users")
def users(user: User = Depends(require(Perm.MANAGE_USERS)), db: Session = Depends(get_db)) -> list[dict]:
    return [_user(u) | {"active": u.active} for u in db.scalars(select(User))]


@router.post("/admin/users")
def create_user(body: UserCreate, user: User = Depends(require(Perm.MANAGE_USERS)), db: Session = Depends(get_db)) -> dict:
    if "@" not in body.email or not body.name.strip():
        raise HTTPException(422, "A valid email and name are required")
    if body.role == Role.LAWYER:
        raise HTTPException(422, "Lawyer accounts are added and approved by the DLSA (Lawyers page)")
    if body.role == Role.JAIL_STAFF and not (body.jail or "").strip():
        raise HTTPException(422, "Jail staff accounts need a jail")
    if body.role == Role.DLSA_ADMIN and not (body.district or "").strip():
        raise HTTPException(422, "DLSA accounts need a district")
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "A user with this email exists")
    u = User(email=body.email.lower(), name=body.name, role=body.role, jail=body.jail, district=body.district,
             hashed_password=hash_password(body.password), approved_at=datetime.now(timezone.utc), created_by=user.id)
    db.add(u)
    db.flush()
    audit(db, user, "create_user", "user", u.id, after={"email": u.email, "role": u.role})
    return _user(u)


@router.patch("/admin/users/{uid}")
def update_user(uid: str, body: UserPatch, user: User = Depends(require(Perm.MANAGE_USERS)), db: Session = Depends(get_db)) -> dict:
    u = db.get(User, uid)
    if u is None:
        raise not_found()
    if u.id == user.id and (body.active is False or (body.role and body.role != u.role)):
        raise HTTPException(409, "You cannot deactivate your own account or change your own role")
    from app.services import accounts
    if body.role == Role.LAWYER and u.role != Role.LAWYER:
        raise HTTPException(422, "Lawyer accounts are added and approved by the DLSA (Lawyers page)")
    if body.active is False and u.active:
        accounts.deactivate(db, user, u, reason="deactivated by admin")
    elif body.active is True and not u.active:
        accounts.activate(db, user, u)
    before = {"role": u.role, "jail": u.jail, "district": u.district}
    if body.role and body.role != u.role and u.role == Role.LAWYER:
        for p in db.scalars(select(Person).where(Person.assigned_lawyer_id == u.id)):  # a non-lawyer keeps no assignments
            p.assigned_lawyer_id = None
            audit(db, user, "unassign_lawyer", "person", p.id, before=u.id, after=None, detail="role changed", commit=False)
    for k in ("role", "jail", "district"):
        v = getattr(body, k)
        if v is not None:
            setattr(u, k, v)
    after = {"role": u.role, "jail": u.jail, "district": u.district}
    if after != before:
        audit(db, user, "change_role" if before["role"] != u.role else "update_user", "user", u.id, before=before, after=after)
    db.commit()
    return _user(u) | {"active": u.active}


@router.post("/admin/run-nightly")
def nightly(user: User = Depends(require(Perm.MANAGE_LEGAL_DATA)), db: Session = Depends(get_db)) -> dict:
    from dataclasses import asdict
    rep = run_nightly(db)
    audit(db, user, "run_nightly", "system", None, after=asdict(rep))
    return asdict(rep)


@router.post("/admin/reclassify-delays")
def reclassify(user: User = Depends(require(Perm.MANAGE_LEGAL_DATA)), db: Session = Depends(get_db)) -> dict:
    n = attribute_hearings(db, list(db.scalars(select(Hearing))), use_llm=settings.llm_provider != "none")
    audit(db, user, "reclassify_delays", "system", None, detail=f"{n} queued")
    return {"queued_for_review": n}


__all__ = ["router", "can_see_person"]
