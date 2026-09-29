from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.delays.classifier import classify_reason
from app.models import Hearing, ReviewItem


def attribute_hearings(db: Session, hearings: list[Hearing], use_llm: bool = True) -> int:
    """Classify un-reviewed hearings; queue low-confidence 'accused' calls (they change the
    computation) and all unknowns for review. Returns number queued."""
    queued = 0
    for h in hearings:
        if h.reviewer_verified:
            continue
        a = classify_reason(h.reason_text or h.outcome_text, use_llm)
        h.delay_attribution = a.label
        h.attribution_confidence = a.confidence
        h.attribution_method = a.method
        needs = (a.label == "accused" and a.confidence < settings.confidence_threshold) or a.label == "unknown" and bool(h.reason_text)
        if needs and not db.query(ReviewItem).filter_by(kind="delay_attribution", ref_id=h.id).first():
            db.add(ReviewItem(kind="delay_attribution", ref_id=h.id, confidence=a.confidence,
                              title=f"Adjournment {h.date.isoformat()}: '{(h.reason_text or '')[:80]}'",
                              payload={"hearing_id": h.id, "case_id": h.case_id, "suggested": a.label,
                                       "method": a.method, "notes": a.notes, "reason_text": h.reason_text}))
            queued += 1
    db.flush()
    return queued
