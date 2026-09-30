"""Fact extraction = deterministic extractors ⨉ LLM (structured JSON), cross-checked.

* Regex/form extractors run always; they carry exact spans.
* The LLM (if configured) returns facts with an `evidence_quote`; a quote that cannot
  be found verbatim in the document is DROPPED (no fabrication).
* Where both give a value for the same field: agreement raises confidence, disagreement
  keeps the regex value, lowers confidence and records the LLM value for review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel

from app.core.llm import get_llm
from app.extraction.dates import extract_dates
from app.extraction.fields import Field, extract_fields

DATE_FIELDS = {"offence_datetime", "fir_datetime", "arrest_datetime", "production_datetime", "remand_date",
               "charge_sheet_date", "charge_sheet_offence_date", "admission_date", "stated_arrest_date", "release_date",
               "transfer_date"}


class LLMFact(BaseModel):
    field: str
    value: str
    evidence_quote: str
    confidence: float


class LLMExtraction(BaseModel):
    facts: list[LLMFact]


@dataclass
class FactCandidate:
    field: str
    value: object
    start: int
    end: int
    text: str
    method: str
    confidence: float
    notes: list[str] = field(default_factory=list)


def _find(text: str, quote: str) -> tuple[int, int] | None:
    if not quote.strip():
        return None
    i = text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    pat = r"\s+".join(re.escape(p) for p in quote.split())
    m = re.search(pat, text)
    return (m.start(), m.end()) if m else None


def _date_part(v: object) -> str | None:
    return str(v)[:10] if v else None


def extract(text: str, doc_type: str, today: date, use_llm: bool = True) -> tuple[list[FactCandidate], dict]:
    fields: list[Field] = extract_fields(text, today)
    out = [FactCandidate(f.name, f.value, f.start, f.end, f.text, f.method, f.confidence,
                         [f"flag:{x}" for x in f.flags]) for f in fields]
    meta: dict = {"llm": None}
    if not use_llm:
        return out, meta
    res = get_llm().structured("extract_facts", LLMExtraction, document=text[:60000], doc_type=doc_type,
                               today=today.isoformat())
    meta["llm"] = {"model": res.model, "prompt_version": res.prompt_version, "error": res.error,
                   "raw": res.raw[:20000] if res.raw else None}
    if res.data is None:
        return out, meta
    by_field = {c.field: c for c in out if c.field not in ("hearing", "charge")}
    for lf in res.data.facts:  # type: ignore[attr-defined]
        span = _find(text, lf.evidence_quote)
        if span is None:
            meta.setdefault("dropped", []).append({"field": lf.field, "value": lf.value, "reason": "evidence not in document"})
            continue
        existing = by_field.get(lf.field)
        if existing is None:
            value: object = lf.value
            if lf.field in DATE_FIELDS:
                ds = [d for d in extract_dates(lf.value, today) if d.value] or [d for d in extract_dates(lf.evidence_quote, today) if d.value]
                if not ds:
                    continue
                value = ds[0].iso
            out.append(FactCandidate(lf.field, value, span[0], span[1], text[span[0]:span[1]], "llm",
                                     round(min(lf.confidence, 0.75), 2), ["llm-only: confirm"]))
            continue
        if lf.field in DATE_FIELDS:
            agree = _date_part(existing.value) == _date_part(lf.value)
        else:
            agree = str(existing.value).strip().lower() == lf.value.strip().lower()
        if agree:
            existing.method = "regex+llm"
            existing.confidence = round(min(0.99, max(existing.confidence, lf.confidence) + 0.05), 2)
        else:
            existing.confidence = min(existing.confidence, 0.5)
            existing.notes.append(f"DISAGREEMENT: LLM read '{lf.value}' from \"{lf.evidence_quote[:80]}\"")
    return out, meta
