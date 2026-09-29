"""Lawyer priority score. Uses the case-delay model ONLY as a rough historical pattern for
ordering work — never as an input to eligibility, never shown as a prediction for this case."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.eligibility.engine import urgency_rank

MODEL_DIR = Path(__file__).resolve().parents[3] / "ml" / "models"
LABEL = "Rough historical pattern for similar cases — not a prediction for this case."

ACT_GROUP = {"302": "IPC_murder", "307": "IPC_murder", "376": "IPC_women", "354": "IPC_women", "498A": "IPC_women",
             "509": "IPC_women", "323": "IPC_hurt", "324": "IPC_hurt", "325": "IPC_hurt", "326": "IPC_hurt"}


@lru_cache(maxsize=1)
def _model():
    try:
        import lightgbm as lgb
        meta = json.loads((MODEL_DIR / "delay_meta.json").read_text())
        return lgb.Booster(model_file=str(MODEL_DIR / "delay_lgbm.txt")), meta
    except Exception:  # noqa: BLE001 — model is optional
        return None, None


def act_group(act: str, section: str) -> str:
    if act == "NDPS":
        return "NDPS"
    if act == "ARMS":
        return "Arms"
    if act in ("IPC", "BNS"):
        return ACT_GROUP.get(section, "IPC_property")
    return "Minor_acts"


def long_pending_probability(act: str, section: str, state: str, district: str, filing_year: int) -> float | None:
    booster, meta = _model()
    if booster is None:
        return None
    import pandas as pd
    row = {"act_group": act_group(act, section), "state": state, "district": district, "filing_year": filing_year,
           "case_type": "criminal", "n_accused": 1}
    df = pd.DataFrame([row])
    for c, cats in meta["categorical"].items():
        df[c] = pd.Categorical(df[c], categories=cats)
    return float(booster.predict(df[meta["features"]])[0])


def priority_score(urgency_code: str, vulnerability: list[str], p_long: float | None, days_overdue: int | None) -> float:
    """0–100. Eligibility urgency dominates; the delay pattern and vulnerability only break ties."""
    base = 100 - urgency_rank(urgency_code) * 10
    bonus = 4 * len(vulnerability) + (min(days_overdue, 365) / 365 * 6 if days_overdue else 0)
    return round(min(100.0, base + bonus + (p_long or 0) * 5), 1)
