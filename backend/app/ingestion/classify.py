"""Document-type classification: keyword rules first, LLM fallback when ambiguous."""
from __future__ import annotations

import re

from pydantic import BaseModel

from app.core.llm import get_llm

DOC_TYPES = ["fir", "arrest_memo", "remand_order", "charge_sheet", "court_order", "judgment", "bail_order",
             "jail_record", "medical_record", "release_order", "transfer_record", "unknown"]

RULES: dict[str, list[str]] = {
    "fir": [r"first information report", r"\bF\.?I\.?R\b", r"ಪ್ರಥಮ ಮಾಹಿತಿ ವರದಿ", r"प्रथम सूचना रिपोर्ट"],
    "arrest_memo": [r"arrest memo", r"grounds of arrest", r"inspection memo", r"ಬಂಧನ ಪಂಚನಾಮೆ"],
    "remand_order": [r"order on remand", r"remanded to", r"ರಿಮಾಂಡ್ ಆದೇಶ", r"judicial custody"],
    "charge_sheet": [r"charge ?sheet", r"final report", r"u/s 173", r"u/s 193 BNSS", r"ದೋಷಾರೋಪಣ ಪಟ್ಟಿ"],
    "court_order": [r"order sheet", r"call on", r"adjourned"],
    "judgment": [r"\bjudgment\b", r"point(s)? for (my )?consideration", r"in the result", r"is hereby acquitted", r"is convicted"],
    "bail_order": [r"enlarged on bail", r"bail (is )?granted", r"bail application", r"surety"],
    "jail_record": [r"jail admission", r"UTP No", r"prisoner", r"ಕಾರಾಗೃಹ ದಾಖಲೆ", r"ಕೈದಿ ಸಂಖ್ಯೆ"],
    "medical_record": [r"medical examination report", r"MLC", r"injury certificate", r"discharge summary"],
    "release_order": [r"release order", r"order of release", r"released from (the )?(jail|prison|custody)", r"set at liberty",
                      r"release warrant", r"date of release"],
    "transfer_record": [r"transfer of (the )?prisoner", r"jail transfer", r"transfer order", r"date of transfer",
                        r"transferred to"],
}

# What a document of each type must actually contain (fields found by the extractors) before its facts are
# trusted automatically. The type itself comes from the TEXT, never from the filename or the uploader.
REQUIRED_FIELDS: dict[str, list[set[str]]] = {  # every inner set: at least one of these fields must be present
    "fir": [{"fir_number"}, {"offence_datetime", "fir_datetime"}, {"charge"}],
    "arrest_memo": [{"arrest_datetime"}, {"person"}],
    "remand_order": [{"remand_date", "production_datetime"}],
    "charge_sheet": [{"charge_sheet_date"}, {"charge"}],
    "court_order": [{"hearing"}],
    "jail_record": [{"admission_date", "prisoner_number"}],
    "release_order": [{"release_date"}],
    "transfer_record": [{"transfer_date"}],
}


def missing_required(doc_type: str, fields: set[str]) -> list[str]:
    return [" / ".join(sorted(req)) for req in REQUIRED_FIELDS.get(doc_type, []) if not (req & fields)]


class DocTypeLLM(BaseModel):
    doc_type: str
    confidence: float
    reason: str


def classify(text: str) -> tuple[str, float, str]:
    """Return (doc_type, confidence, method)."""
    head = text[:3000]
    scores = {t: sum(1 for p in pats if re.search(p, head, re.I)) for t, pats in RULES.items()}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, top = ranked[0]
    second = ranked[1][1]
    if top >= 2 and top > second:
        return best, min(0.95, 0.6 + 0.15 * top), "rules"
    if top == 1 and second == 0:
        return best, 0.7, "rules"
    res = get_llm().structured("classify_document", DocTypeLLM, text=head, doc_types=", ".join(DOC_TYPES))
    if res.data is not None and res.data.doc_type in DOC_TYPES:  # type: ignore[attr-defined]
        return res.data.doc_type, min(float(res.data.confidence), 0.85), "llm"  # type: ignore[attr-defined]
    if top > 0:
        return best, 0.5, "rules_tie"
    return "unknown", 0.0, "none"
