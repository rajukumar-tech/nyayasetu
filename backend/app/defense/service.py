from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.defense.engine import attach_judgments, detect
from app.defense.retrieval import get_index
from app.domain import ComputeContext
from app.eligibility.engine import evaluate_person
from app.legal_kb.kb import KnowledgeBase
from app.models import DefenseInsight, Document, ExtractedFact, Person
from app.services.eligibility import load_kb
from app.services.mapping import to_domain_person


def fact_rows(db: Session, person: Person, case_id: str) -> list[dict]:
    q = (select(ExtractedFact, Document.doc_type).join(Document, Document.id == ExtractedFact.document_id)
         .where(ExtractedFact.person_id == person.id)
         .where((ExtractedFact.case_id == case_id) | (ExtractedFact.case_id.is_(None)) | (Document.case_id == case_id)))
    rows = []
    for f, doc_type in db.execute(q):
        rows.append({"id": f.id, "document_id": f.document_id, "doc_type": doc_type, "field": f.field, "value": f.value,
                     "corrected_value": f.corrected_value, "review_status": f.review_status, "page": f.page,
                     "span_start": f.span_start, "span_end": f.span_end, "span_text": f.span_text, "confidence": f.confidence})
    return rows


def refresh_insights(db: Session, person: Person, kb: KnowledgeBase | None = None) -> list[DefenseInsight]:
    """Recompute insights; keeps the lawyer's accept/reject decisions for insights that still apply."""
    kb = kb or load_kb(db)
    dp = to_domain_person(person)
    result = evaluate_person(dp, kb, ComputeContext(settings.today(), settings.confidence_threshold))
    by_case = {c.case_id: c for c in result.cases}
    index = get_index()
    age = None
    if person.dob:
        age = int((settings.today() - person.dob).days / 365.25)
    existing = {(i.case_id, i.code): i for i in db.scalars(select(DefenseInsight).where(DefenseInsight.person_id == person.id))}
    seen = set()
    for case in dp.cases:
        if not case.status.is_pending:
            continue
        insights = detect(dp, case, fact_rows(db, person, case.id), by_case.get(case.id), kb, settings.today(), age)
        attach_judgments(insights, index)
        for ins in insights:
            key = (case.id, ins.code)
            seen.add(key)
            row = existing.get(key) or DefenseInsight(person_id=person.id, case_id=case.id, code=ins.code)
            row.category, row.severity, row.title = ins.category, ins.severity, ins.title
            row.explanation, row.next_steps = ins.explanation, ins.next_steps
            row.evidence = [asdict(e) for e in ins.evidence]
            row.legal_basis, row.judgments, row.rank_score = ins.legal_basis, ins.judgments, ins.rank_score
            if key not in existing:
                db.add(row)
    for key, row in existing.items():
        if key not in seen and row.status == "new":
            db.delete(row)
    db.commit()
    return list(db.scalars(select(DefenseInsight).where(DefenseInsight.person_id == person.id)
                           .order_by(DefenseInsight.rank_score.desc())))
