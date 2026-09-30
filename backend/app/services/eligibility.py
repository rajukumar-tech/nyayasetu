from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain import ComputeContext
from app.eligibility.engine import RULE_VERSION, PersonResult, evaluate_person
from app.legal_kb.kb import KnowledgeBase
from app.models import EligibilityResult, LegalVerification, Person
from app.services.consistency import record_conflicts
from app.services.mapping import jsonable, to_domain_person


def load_kb(db: Session) -> KnowledgeBase:
    overlay = {v.record_key: {"verified": v.verified, "verified_by": v.verified_by}
               for v in db.scalars(select(LegalVerification))}
    return KnowledgeBase.load(settings.legal_data_dir, overlay)


@dataclass
class ComputeOutcome:
    row: EligibilityResult
    result: PersonResult
    changed: bool
    previous_status: str | None


def compute_for_person(db: Session, person: Person, kb: KnowledgeBase | None = None, commit: bool = True) -> ComputeOutcome:
    """Run the deterministic engine and store the result. Idempotent: identical inputs
    (facts + legal data version + rule version + date) reuse the current row."""
    kb = kb or load_kb(db)
    today = settings.today()
    dp = to_domain_person(person, record_conflicts(db, person))
    result = evaluate_person(dp, kb, ComputeContext(today=today, confidence_threshold=settings.confidence_threshold))
    payload = json.dumps({"p": jsonable(dp), "kb": kb.version, "rv": RULE_VERSION, "today": today.isoformat()},
                         sort_keys=True, default=str)
    input_hash = hashlib.sha256(payload.encode()).hexdigest()
    current = db.scalar(select(EligibilityResult).where(EligibilityResult.person_id == person.id,
                                                        EligibilityResult.is_current.is_(True)))
    if current is not None and current.input_hash == input_hash:
        return ComputeOutcome(current, result, False, current.status)
    previous = current.status if current else None
    if current is not None:
        current.is_current = False
    data = jsonable(result)
    data["as_of"] = today.isoformat()  # the date the day-counts are valid for; older rows are recomputed before display
    for c in data["cases"]:
        tl = c.get("timeline") or {}
        c["timeline_explanation"] = [f"{i['start']} → {i['end']}: {inclusive(i)} day(s) — {i['explanation']}"
                                     for i in tl.get("intervals", [])]
    row = EligibilityResult(person_id=person.id, rule_version=RULE_VERSION, legal_data_version=kb.version,
                            status=result.overall_status, eligible_from_date=result.eligible_from_date,
                            days_overdue=result.days_overdue, confidence=result.confidence, input_hash=input_hash,
                            result=data, is_current=True)
    db.add(row)
    if commit:
        db.commit()
    return ComputeOutcome(row, result, True, previous)


def inclusive(i: dict) -> int:
    from datetime import date
    return (date.fromisoformat(i["end"]) - date.fromisoformat(i["start"])).days + 1


def current_result(db: Session, person_id: str) -> EligibilityResult | None:
    return db.scalar(select(EligibilityResult).where(EligibilityResult.person_id == person_id,
                                                     EligibilityResult.is_current.is_(True)))
