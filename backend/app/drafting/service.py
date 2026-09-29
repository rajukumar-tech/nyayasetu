from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import settings
from app.drafting.drafter import build, polish_with_llm, to_dict, verify
from app.models import Case, DefenseInsight, Document, Draft, ExtractedFact, Person, User
from app.services.eligibility import compute_for_person, load_kb


def draft_context(db: Session, person: Person, case: Case) -> dict:
    out = compute_for_person(db, person)
    case_res = next((c for c in out.row.result["cases"] if c["case_id"] == case.id), {})
    facts: dict[str, dict] = {}
    q = (select(ExtractedFact).join(Document, Document.id == ExtractedFact.document_id)
         .where(ExtractedFact.person_id == person.id, ExtractedFact.review_status != "rejected")
         .order_by(ExtractedFact.confidence.desc()))
    for f in db.scalars(q):
        if f.case_id in (None, case.id) and f.field not in facts and f.confidence >= settings.confidence_threshold:
            facts[f.field] = {"id": f.id, "value": f.effective_value, "span_text": f.span_text}
    insights = [i for i in db.scalars(select(DefenseInsight).where(DefenseInsight.person_id == person.id,
                                                                    DefenseInsight.case_id == case.id,
                                                                    DefenseInsight.status == "accepted"))]
    judgments = []
    for i in insights:
        for j in i.judgments:
            if j["id"] not in {x["id"] for x in judgments}:
                judgments.append(j)
    ps = next((f.span_text for f in db.scalars(select(ExtractedFact).where(ExtractedFact.person_id == person.id,
                                                                            ExtractedFact.field == "police_station"))), None)
    return {
        "person": {"id": person.id, "name": person.canonical_name, "relation": person.relation,
                   "relative": (person.relative_name_variants or [None])[0], "jail": person.jail},
        "case": {"id": case.id, "court": case.court, "case_number": (case.case_numbers or [""])[0], "cnr": case.cnr,
                 "fir": case.fir_number, "ps": case.police_station or ps,
                 "charges": [f"{c.section} {c.act}" for c in case.charges if c.dropped_on is None],
                 "first_remand_date": case.first_remand_date.isoformat() if case.first_remand_date else None,
                 "bail_granted_date": case.bail_granted_date.isoformat() if case.bail_granted_date else None},
        "eligibility": case_res, "facts": facts,
        "insights": [{"id": i.id, "title": i.title, "explanation": i.explanation, "evidence": i.evidence} for i in insights],
        "judgments": judgments,
        "rule_refs": [r.ref for r in load_kb(db).rules.values() if r.ref],
    }


def create_draft(db: Session, person: Person, case: Case, draft_type: str, language: str, user: User | None,
                 use_llm: bool = True) -> Draft:
    today = settings.today()
    ctx = draft_context(db, person, case)
    doc = build(draft_type, language, ctx, today)
    report = verify(doc, today)
    if use_llm:
        report["llm_polished_sentences"] = polish_with_llm(doc, today)
        report.update({k: v for k, v in verify(doc, today).items() if k != "llm_polished_sentences"})
    d = to_dict(doc)
    row = Draft(person_id=person.id, case_id=case.id, type=draft_type, language=language, content=doc.text,
                grounding=[{"id": s["id"], "text": s["text"], "sources": s["sources"], "status": s["status"],
                            "problems": s["problems"]} for s in d["sentences"]],
                verifier_report={**report, "notes": doc.notes, "disclaimer": doc.disclaimer, "title": doc.title},
                status="draft" if report["rejected"] == 0 else "needs_attention", created_by=user.id if user else None)
    db.add(row)
    db.flush()
    audit(db, user, "create_draft", "draft", row.id, after={"type": draft_type, "language": language,
                                                           "rejected_sentences": report["rejected"]})
    return row
