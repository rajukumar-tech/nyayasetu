"""HTTP API. Every endpoint is RBAC-checked and every view/edit/decision is audit-logged."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import settings
from app.core.rbac import Perm, Role, can_see_insights, can_see_person, ensure_person_access, has_perm, require
from app.core.security import create_token, current_user, hash_password, verify_password
from app.db import get_db
from app.defense.service import refresh_insights
from app.delays.service import attribute_hearings
from app.drafting.export import to_docx, to_pdf
from app.drafting.service import create_draft
from app.eligibility.engine import urgency_rank
from app.ingestion.ocr import IngestError
from app.ingestion.pipeline import ingest
from app.models import (
    Alert, AuditLog, Case, DefenseInsight, Document, Draft, ExtractedFact, Hearing, LegalVerification, MergeEvent,
    Person, ReviewItem, User,
)
from app.monitoring.alerts import alerts_for, run_nightly
from app.prediction.priority import LABEL as PRIORITY_LABEL, long_pending_probability, priority_score
from app.resolution.matcher import PairModel, resolve, score_pair
from app.resolution.merge import merge_persons, person_record, unmerge
from app.schemas import (
    AssignIn, DraftCreate, DraftPatch, FactPatch, InsightPatch, LoginIn, MergeIn, ReviewResolve, TokenOut, UserCreate,
    VerifyIn,
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
    if u is None or not u.active or not verify_password(body.password, u.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    audit(db, u, "login", "user", u.id)
    return TokenOut(access_token=create_token(u), user=_user(u))


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


def _summary(db: Session, p: Person, with_priority: bool = False) -> dict:
    r = current_result(db, p.id)
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
                     for c in p.cases], "assigned_lawyer_id": p.assigned_lawyer_id}
    if with_priority:
        ch = next((ch for c in p.cases if c.status in ("investigation", "charge_sheet_filed", "trial") for ch in c.charges), None)
        pl = long_pending_probability(ch.act, ch.section, "KA", p.district or "", p.cases[0].fir_year or 2024) if ch and p.cases else None
        out["priority"] = priority_score(urgency, p.vulnerability, pl, r.days_overdue if r else None)
        out["delay_pattern"] = {"p_pending_3y": round(pl, 2) if pl is not None else None, "label": PRIORITY_LABEL}
    return out


@router.get("/persons")
def list_persons(user: User = Depends(require(Perm.VIEW_PRISONER)), db: Session = Depends(get_db),
                 q: str | None = None, status_filter: str | None = Query(None, alias="status")) -> list[dict]:
    persons = _scoped_persons(db, user)
    if q:
        from app.resolution.normalise import phonetic_key
        k = phonetic_key(q)
        persons = [p for p in persons if q.lower() in p.canonical_name.lower() or (k and k in phonetic_key(p.canonical_name))]
    rows = [_summary(db, p, with_priority=True) for p in persons]
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter or r["urgency"] == status_filter]
    rows.sort(key=lambda r: (urgency_rank(r["urgency"]), -(r.get("priority") or 0)))
    audit(db, user, "list", "person", None, detail=f"{len(rows)} rows")
    return rows


@router.get("/persons/{pid}")
def get_person(pid: str, user: User = Depends(require(Perm.VIEW_PRISONER)), db: Session = Depends(get_db)) -> dict:
    p = ensure_person_access(user, db.get(Person, pid))
    r = current_result(db, p.id) or compute_for_person(db, p).row
    docs = db.scalars(select(Document).where(Document.person_id == p.id).order_by(Document.created_at)).all()
    facts = db.scalars(select(ExtractedFact).where(ExtractedFact.person_id == p.id)).all()
    kb = load_kb(db)
    audit(db, user, "view", "person", p.id)
    return {
        **_summary(db, p), "dob": p.dob.isoformat() if p.dob else None, "name_variants": p.name_variants,
        "identifiers": {k: v for k, v in p.identifiers.items() if k not in ("expected_status",)},
        "can_see_insights": can_see_insights(user, p), "can_draft": has_perm(user, Perm.CREATE_DRAFTS),
        "eligibility": r.result, "rule_version": r.rule_version, "legal_data_version": r.legal_data_version,
        "computed_at": r.computed_at.isoformat(),
        "case_details": [{
            "id": c.id, "cnr": c.cnr, "case_numbers": c.case_numbers, "court": c.court, "status": c.status,
            "fir_number": c.fir_number, "police_station": c.police_station, "offence_date": _iso(c.offence_date),
            "first_remand_date": _iso(c.first_remand_date), "charge_sheet_date": _iso(c.charge_sheet_date),
            "bail_granted_date": _iso(c.bail_granted_date),
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
    p = ensure_person_access(user, db.get(Person, pid))
    out = compute_for_person(db, p)
    audit(db, user, "recompute", "eligibility", p.id, after={"status": out.row.status, "changed": out.changed})
    return {"status": out.row.status, "changed": out.changed}


@router.post("/persons/{pid}/assign")
def assign(pid: str, body: AssignIn, user: User = Depends(require(Perm.ASSIGN_LAWYERS)), db: Session = Depends(get_db)) -> dict:
    p = ensure_person_access(user, db.get(Person, pid))
    lawyer = db.get(User, body.lawyer_id)
    if lawyer is None or lawyer.role != Role.LAWYER:
        raise HTTPException(400, "Not a legal-aid lawyer")
    before = p.assigned_lawyer_id
    p.assigned_lawyer_id = lawyer.id
    audit(db, user, "assign_lawyer", "person", p.id, before=before, after=lawyer.id)
    return {"ok": True}


# ------------------------------------------------------------------ documents & facts
@router.post("/persons/{pid}/documents")
async def upload(pid: str, file: UploadFile = File(...), case_id: str | None = Form(None),
                 user: User = Depends(require(Perm.UPLOAD_DOCUMENTS)), db: Session = Depends(get_db)) -> dict:
    p = ensure_person_access(user, db.get(Person, pid))
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
        raise HTTPException(404, "Document not found")
    if not has_perm(user, Perm.REVIEW_QUEUE):
        ensure_person_access(user, db.get(Person, d.person_id) if d.person_id else None)
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
        raise HTTPException(404, "Fact not found")
    p = db.get(Person, f.person_id) if f.person_id else None
    if Role(user.role) == Role.LAWYER:
        ensure_person_access(user, p)
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
        refresh_insights(db, p)
    return _fact(f)


# ------------------------------------------------------------------ defense insights (lawyer-only)
@router.get("/persons/{pid}/insights")
def insights(pid: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    p = db.get(Person, pid)
    if p is None:
        raise HTTPException(404, "Prisoner record not found")
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
        raise HTTPException(404, "Insight not found")
    if not can_see_insights(user, db.get(Person, i.person_id)):
        raise HTTPException(403, "Defense Insights are visible only to the assigned lawyer")
    before = i.status
    i.status = body.status
    audit(db, user, f"insight_{body.status}", "defense_insight", i.id, before=before, after=body.status, detail=body.note)
    return {"id": i.id, "status": i.status}


# ------------------------------------------------------------------ drafts
@router.post("/persons/{pid}/drafts")
def new_draft(pid: str, body: DraftCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    p = ensure_person_access(user, db.get(Person, pid))
    case = db.get(Case, body.case_id)
    if case is None or case not in p.cases:
        raise HTTPException(404, "Case not found for this prisoner")
    lawyer = has_perm(user, Perm.CREATE_DRAFTS) and can_see_insights(user, p)
    superintendent = has_perm(user, Perm.SUPERINTENDENT_APPLICATION) and body.type == "section_479"
    if not (lawyer or superintendent):
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
            "versions": d.versions, "created_at": d.created_at.isoformat()}


def _draft_access(db: Session, user: User, did: str) -> Draft:
    d = db.get(Draft, did)
    if d is None:
        raise HTTPException(404, "Draft not found")
    ensure_person_access(user, db.get(Person, d.person_id))
    return d


@router.get("/persons/{pid}/drafts")
def list_drafts(pid: str, user: User = Depends(require(Perm.VIEW_PRISONER)), db: Session = Depends(get_db)) -> list[dict]:
    p = ensure_person_access(user, db.get(Person, pid))
    rows = db.scalars(select(Draft).where(Draft.person_id == p.id).order_by(Draft.created_at.desc())).all()
    if not can_see_insights(user, p):
        rows = [r for r in rows if not any(src["type"] == "insight" for s in r.grounding for src in s["sources"])]
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
        raise HTTPException(403, "Only the assigned lawyer can edit this draft")
    if body.content is not None and body.content != d.content:
        d.versions = d.versions + [{"at": datetime.now(timezone.utc).isoformat(), "by": user.id, "content": d.content}]
        d.content = body.content
        d.verifier_report = {**d.verifier_report, "lawyer_edited": True}
    if body.status:
        d.status = body.status
    audit(db, user, "edit_draft", "draft", d.id, after={"status": d.status, "edited": body.content is not None})
    return _draft(d)


@router.get("/drafts/{did}/export")
def export_draft(did: str, format: str = "docx", user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    d = _draft_access(db, user, did)
    paras = d.content.split("\n\n")
    title = d.verifier_report.get("title", d.type)
    disc = d.verifier_report.get("disclaimer", "")
    audit(db, user, "export_draft", "draft", d.id, detail=format)
    if format == "pdf":
        return Response(to_pdf(title, paras, disc, d.language), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{d.type}_{d.language}.pdf"'})
    return Response(to_docx(title, paras, disc, d.language),
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{d.type}_{d.language}.docx"'})


# ------------------------------------------------------------------ review queue
@router.get("/review")
def review_queue(user: User = Depends(require(Perm.REVIEW_QUEUE)), db: Session = Depends(get_db), kind: str | None = None) -> list[dict]:
    q = select(ReviewItem).where(ReviewItem.status == "open").order_by(ReviewItem.confidence, ReviewItem.created_at)
    if kind:
        q = q.where(ReviewItem.kind == kind)
    rows = db.scalars(q.limit(300)).all()
    audit(db, user, "list", "review_queue", None, detail=f"{len(rows)} items")
    return [{"id": r.id, "kind": r.kind, "ref_id": r.ref_id, "title": r.title, "payload": r.payload, "confidence": r.confidence,
             "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/review/{rid}/resolve")
def resolve_item(rid: str, body: ReviewResolve, user: User = Depends(require(Perm.REVIEW_QUEUE)), db: Session = Depends(get_db)) -> dict:
    item = db.get(ReviewItem, rid)
    if item is None or item.status != "open":
        raise HTTPException(404, "Review item not found or already resolved")
    person = None
    if item.kind == "extraction" and body.action in ("confirm", "correct", "reject"):
        f = db.get(ExtractedFact, item.ref_id)
        if f:
            f.review_status = {"confirm": "confirmed", "correct": "corrected", "reject": "rejected"}[body.action]
            f.corrected_value = body.value if body.action == "correct" else f.corrected_value
            f.reviewer_id, f.confidence = user.id, 1.0 if body.action != "reject" else f.confidence
            person = db.get(Person, f.person_id) if f.person_id else None
    elif item.kind == "delay_attribution":
        h = db.get(Hearing, item.ref_id)
        if h:
            h.delay_attribution = body.value if body.action == "set_attribution" else item.payload.get("suggested", "unknown")
            h.reviewer_verified, h.attribution_confidence, h.attribution_method = True, 1.0, "reviewer"
            case = db.get(Case, h.case_id)
            person = case.persons[0] if case and case.persons else None
    elif item.kind == "identity_match" and body.action in ("link", "not_same"):
        a, b = db.get(Person, item.payload["a"]), db.get(Person, item.payload["b"])
        if body.action == "link" and a and b and not a.merged_into_id and not b.merged_into_id:
            merge_persons(db, a, b, user, item.confidence)
            person = a
    item.status, item.resolved_by = "resolved", user.id
    item.resolution = {"action": body.action, "value": body.value, "note": body.note}
    audit(db, user, "review_resolve", item.kind, item.ref_id, after=item.resolution)
    if person is not None:
        out = compute_for_person(db, person)
        alerts_for(db, person, out, settings.today(), reason="document")
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
        raise HTTPException(404, "Person not found")
    ev = merge_persons(db, keep, other, user, body.score or score_pair(person_record(keep), person_record(other), PairModel()).p)
    compute_for_person(db, keep)
    return {"merge_event": ev.id}


@router.post("/resolution/unmerge/{eid}")
def do_unmerge(eid: str, user: User = Depends(require(Perm.MERGE_PERSONS)), db: Session = Depends(get_db)) -> dict:
    ev = db.get(MergeEvent, eid)
    if ev is None:
        raise HTTPException(404, "Merge event not found")
    other = unmerge(db, ev, user)
    compute_for_person(db, other)
    compute_for_person(db, db.get(Person, ev.kept_person_id))
    return {"restored": other.id}


@router.get("/resolution/merges")
def merges(user: User = Depends(require(Perm.MERGE_PERSONS)), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": m.id, "kept": m.kept_person_id, "merged": m.merged_person_id, "score": m.score, "undone": m.undone,
             "created_at": m.created_at.isoformat()} for m in db.scalars(select(MergeEvent).order_by(MergeEvent.created_at.desc()))]


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
             "severity": a.severity, "message": a.message, "created_at": a.created_at.isoformat(), "escalated": a.escalated,
             "acknowledged_at": _iso(a.acknowledged_at)} for a in rows]


@router.post("/alerts/{aid}/ack")
def ack(aid: str, user: User = Depends(require(Perm.ACK_ALERTS)), db: Session = Depends(get_db)) -> dict:
    a = db.get(Alert, aid)
    if a is None:
        raise HTTPException(404, "Alert not found")
    ensure_person_access(user, db.get(Person, a.person_id))
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
    for p in persons:
        s = _summary(db, p)
        d = by_district.setdefault(p.district or "Unknown", {"district": p.district, "prisoners": 0, "overdue": 0, "critical": 0,
                                                            "review": 0, "urgent_default_bail": 0, "detention_days": [],
                                                            "vulnerable": 0, "women": 0})
        d["prisoners"] += 1
        d["overdue"] += int(s["status"] == "ELIGIBLE")
        d["critical"] += int(s["urgency"].startswith("CRITICAL"))
        d["review"] += int(s["status"] in ("REVIEW", "REVIEW_MULTIPLE_CASES"))
        d["urgent_default_bail"] += int(s["urgency"] == "URGENT_DEFAULT_BAIL")
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
              limit: int = 200) -> list[dict]:
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    return [{"id": a.id, "ts": a.ts.isoformat(), "user_id": a.user_id, "role": a.role, "action": a.action,
             "entity_type": a.entity_type, "entity_id": a.entity_id, "detail": a.detail} for a in db.scalars(q)]


@router.get("/admin/users")
def users(user: User = Depends(require(Perm.MANAGE_USERS)), db: Session = Depends(get_db)) -> list[dict]:
    return [_user(u) for u in db.scalars(select(User))]


@router.post("/admin/users")
def create_user(body: UserCreate, user: User = Depends(require(Perm.MANAGE_USERS)), db: Session = Depends(get_db)) -> dict:
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "A user with this email exists")
    u = User(email=body.email.lower(), name=body.name, role=body.role, jail=body.jail, district=body.district,
             hashed_password=hash_password(body.password))
    db.add(u)
    db.flush()
    audit(db, user, "create_user", "user", u.id, after={"email": u.email, "role": u.role})
    return _user(u)


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
