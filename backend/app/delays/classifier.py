"""Delay attribution for adjournments: keyword rules → trained text classifier → LLM fallback.

Labels: accused | prosecution | court | both | other | unknown.
Only `accused` days are excluded from Section 479 detention, so the rules are careful
about look-alikes: an accused "absent" because the jail did not produce them is the
State's delay, not the accused's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from pydantic import BaseModel

from app.core.llm import get_llm

LABELS = ["accused", "prosecution", "court", "both", "other", "unknown"]


@dataclass
class Attribution:
    label: str
    confidence: float
    method: str
    matched: str = ""
    notes: list[str] = field(default_factory=list)


# (pattern, label, confidence, note) — first match wins, most specific first
RULES: list[tuple[str, str, float, str]] = [
    (r"not produced|escort not available|escort not provided|video ?link (not|failed)|jail authorities", "prosecution", 0.95,
     "Accused not produced by jail/police — not the accused's delay"),
    (r"both (sides|counsel|parties)|request of both|joint(ly)? request", "both", 0.93, "Shared request — not subtracted"),
    (r"boycott|abstain|strike|bar resolution|no work", "other", 0.93, "Lawyers' boycott/strike"),
    (r"covid|pandemic|lockdown|proceedings suspended", "other", 0.93, "Court functioning suspended"),
    (r"vacation|presiding officer|\bP\.?O\.? on leave|judge on leave|court (is )?busy|part[- ]heard|time over|"
     r"ನ್ಯಾಯಾಧೀಶರು ರಜೆ|न्यायाधीश अवकाश", "court", 0.92, ""),
    (r"accused (is )?ill|hospital|medical certificate", "accused", 0.6, "Illness of the accused — confirm before subtracting"),
    (r"vakalat|new counsel|counsel changed|change of counsel", "accused", 0.7, "Change of counsel — confirm"),
    (r"\bP\.?P\.? (sought|seeks|requested)|prosecution (sought|to file|witness)|witness(es)? (absent|not present)|"
     r"\bI\.?O\.? (absent|not present)|case diary|fsl|summons|NBW|ಸಾಕ್ಷಿ|ಅಭಿಯೋಜಕ", "prosecution", 0.9, ""),
    (r"(request|instance) of (the )?accused|accused('s)? (counsel )?(sought|seeks|requested)|accused absent|"
     r"exemption petition|defen[cs]e sought|accused counsel (on leave|absent|not present)|counsel for accused not present|"
     r"ಆರೋಪಿಯ ಪರ ವಕೀಲರ ಕೋರಿಕೆ", "accused", 0.93, ""),
    (r"(defen[cs]e|accused) counsel (requested|sought)", "accused", 0.9, ""),
    (r"turned hostile|cross[- ]examin|evidence (recorded|closed)|\bP\.?W\.?[- ]?\d+ (examined|deposed)", "other", 0.85,
     "Trial progressed at this hearing — no party-caused delay"),
    (r"^\s*(adjourned\.?)?\s*$", "unknown", 0.9, "No reason recorded — not subtracted"),
]


class AttributionLLM(BaseModel):
    label: str
    confidence: float
    rationale: str


def rule_attribution(text: str) -> Attribution | None:
    for pat, label, conf, note in RULES:
        m = re.search(pat, text or "", re.I)
        if m:
            return Attribution(label, conf, "rules", m.group(0), [note] if note else [])
    return None


@lru_cache(maxsize=1)
def _model():
    """Char n-gram TF-IDF + logistic regression trained on the synthetic labelled reasons.
    (Re-train on reviewer-verified reasons in production — see ml/train_delay.py.)"""
    import sys
    from pathlib import Path

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "data" / "synthetic"))
    from generate import ADJOURNMENT_REASONS  # noqa: E402

    texts = [t for t, lab in ADJOURNMENT_REASONS if t]
    labels = [lab for t, lab in ADJOURNMENT_REASONS if t]
    clf = make_pipeline(TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True),
                        LogisticRegression(max_iter=2000, C=5.0))
    clf.fit(texts, labels)
    return clf


def classify_reason(text: str, use_llm: bool = True) -> Attribution:
    r = rule_attribution(text)
    if r is not None:
        return r
    clf = _model()
    probs = clf.predict_proba([text])[0]
    best = int(probs.argmax())
    label, p = clf.classes_[best], float(probs[best])
    if p >= 0.7:
        return Attribution(label, round(min(p, 0.85), 3), "classifier")
    if use_llm:
        res = get_llm().structured("delay_attribution", AttributionLLM, reason=text, labels=", ".join(LABELS))
        if res.data is not None and res.data.label in LABELS:  # type: ignore[attr-defined]
            return Attribution(res.data.label, min(float(res.data.confidence), 0.8), "llm",  # type: ignore[attr-defined]
                               notes=[res.data.rationale[:200]])  # type: ignore[attr-defined]
    return Attribution("unknown", round(p, 3), "classifier_low_confidence", notes=[f"best guess {label} ({p:.2f})"])
