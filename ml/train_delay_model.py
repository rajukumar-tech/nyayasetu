"""Case-delay model: probability that a criminal case is still pending HORIZON years after filing,
plus a Cox proportional-hazards model for ranking (C-index).

Data: Development Data Lab eCourts (district courts 2010–2018, CC BY-NC-SA — non-commercial,
attribution, share-alike). See data/external/download_ddl_ecourts.md. Without the files this
script uses a synthetic dataset with the same schema and labels the model DEMO ONLY.

Censoring: undisposed cases are right-censored at the data end date. For the fixed-horizon
classifier, a case censored before the horizon has an unknown label and is excluded from
training (standard fixed-horizon treatment); the Cox model uses all cases with censoring.
Split: temporal — train on filing years ≤ TRAIN_END, test on later years (no leakage).
Fairness: metrics per district and per defendant-gender field; gender, religion and caste
are NEVER model features.

    python ml/train_delay_model.py [--ddl data/external/ddl]
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HORIZON_YEARS = 3
DATA_END = pd.Timestamp("2018-12-31")
TRAIN_END = 2013
FEATURES = ["act_group", "state", "district", "filing_year", "case_type", "n_accused"]
CATEGORICAL = ["act_group", "state", "district", "case_type"]


def synthetic(n: int = 30000, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    states = {"KA": ["Bengaluru Urban", "Mysuru", "Kalaburagi", "Belagavi"], "MH": ["Pune", "Nagpur"], "UP": ["Lucknow", "Agra"]}
    rows = []
    act_effect = {"IPC_property": 0.0, "IPC_hurt": -0.1, "IPC_murder": 0.5, "IPC_women": 0.3, "NDPS": 0.2, "Arms": 0.1,
                  "Minor_acts": -0.6}
    dist_effect = {d: rng.normal(0, 0.35) for s in states.values() for d in s}
    for _ in range(n):
        st = rng.choice(list(states))
        d = rng.choice(states[st])
        act = rng.choice(list(act_effect), p=[0.28, 0.2, 0.05, 0.1, 0.07, 0.05, 0.25])
        fy = int(rng.integers(2010, 2019))
        filing = pd.Timestamp(date(fy, int(rng.integers(1, 13)), int(rng.integers(1, 28))))
        n_acc = int(rng.choice([1, 1, 1, 2, 2, 3, 5]))
        scale_years = 1.6 * np.exp(act_effect[act] + dist_effect[d] + 0.08 * (n_acc - 1) - 0.03 * (fy - 2010))
        dur = rng.weibull(1.3) * scale_years * 365.25
        decision = filing + pd.Timedelta(days=float(dur))
        rows.append({"filing_date": filing, "decision_date": decision if decision <= DATA_END else pd.NaT,
                     "act_group": act, "state": st, "district": d, "filing_year": fy, "case_type": "criminal",
                     "n_accused": n_acc, "female_defendant": int(rng.random() < 0.1)})
    return pd.DataFrame(rows)


def load_ddl(path: Path) -> pd.DataFrame:
    """Map DDL files onto our schema. Column names follow the DDL codebook; verify against the
    version you downloaded (the codebook ships with the data)."""
    frames = [pd.read_csv(f, low_memory=False) for f in sorted(path.glob("cases_*.csv"))]
    df = pd.concat(frames, ignore_index=True)
    acts = pd.read_csv(path / "acts_sections.csv", low_memory=False) if (path / "acts_sections.csv").exists() else None
    out = pd.DataFrame({
        "filing_date": pd.to_datetime(df["date_of_filing"], errors="coerce"),
        "decision_date": pd.to_datetime(df["date_of_decision"], errors="coerce"),
        "state": df["state_code"].astype(str), "district": df["state_code"].astype(str) + "-" + df["dist_code"].astype(str),
        "filing_year": pd.to_datetime(df["date_of_filing"], errors="coerce").dt.year,
        "case_type": df.get("type_name", pd.Series(["criminal"] * len(df))).astype(str),
        "n_accused": 1, "female_defendant": df.get("female_defendant", pd.Series([np.nan] * len(df))),
    })
    if acts is not None and "ddl_case_id" in df:
        first_act = acts.groupby("ddl_case_id")["act"].first()
        out["act_group"] = df["ddl_case_id"].map(first_act).astype(str)
    else:
        out["act_group"] = "unknown"
    return out.dropna(subset=["filing_date"])


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    end = df["decision_date"].fillna(DATA_END)
    df["duration_days"] = (end - df["filing_date"]).dt.days.clip(lower=1)
    df["event"] = df["decision_date"].notna().astype(int)
    h = HORIZON_YEARS * 365.25
    df["label_long"] = np.where(df["duration_days"] > h, 1, np.where(df["event"] == 1, 0, -1))  # -1 = censored before horizon
    return df


def c_index(time: np.ndarray, event: np.ndarray, risk: np.ndarray) -> float:
    from lifelines.utils import concordance_index
    return float(concordance_index(time, -risk, event))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ddl", type=Path, default=ROOT / "data" / "external" / "ddl")
    a = ap.parse_args()
    demo = not (a.ddl.exists() and any(a.ddl.glob("cases_*.csv")))
    df = prepare(synthetic() if demo else load_ddl(a.ddl))
    for c in CATEGORICAL:
        df[c] = df[c].astype("category")
    train = df[df["filing_year"] <= TRAIN_END]
    test = df[df["filing_year"] > TRAIN_END]

    import lightgbm as lgb
    from lifelines import CoxPHFitter
    from sklearn.metrics import brier_score_loss, roc_auc_score

    tr = train[train["label_long"] >= 0]
    te = test[test["label_long"] >= 0]
    clf = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=50, verbose=-1)
    clf.fit(tr[FEATURES], tr["label_long"])
    p = clf.predict_proba(te[FEATURES])[:, 1] if len(te) else np.array([])

    X_cox = pd.get_dummies(train[FEATURES + ["duration_days", "event"]], columns=CATEGORICAL, drop_first=True, dtype=float)
    cph = CoxPHFitter(penalizer=0.05)
    cph.fit(X_cox, duration_col="duration_days", event_col="event")
    Xt = pd.get_dummies(test[FEATURES], columns=CATEGORICAL, drop_first=True, dtype=float).reindex(
        columns=[c for c in X_cox.columns if c not in ("duration_days", "event")], fill_value=0.0)
    risk = cph.predict_partial_hazard(Xt).values

    def calib(y, pr, bins=10):
        q = pd.qcut(pr, bins, duplicates="drop")
        g = pd.DataFrame({"y": y, "p": pr, "b": q}).groupby("b", observed=True)
        return [{"mean_predicted": round(float(x.p.mean()), 3), "observed": round(float(x.y.mean()), 3), "n": int(len(x))}
                for _, x in g]

    report = {
        "data": "SYNTHETIC DEMO (DDL files not found) — do not use for real prioritisation" if demo else "DDL eCourts",
        "horizon_years": HORIZON_YEARS, "train_years": f"<= {TRAIN_END}", "test_years": f"> {TRAIN_END}",
        "n_train": int(len(tr)), "n_test_labelled": int(len(te)), "n_test_all": int(len(test)),
        "auc": round(float(roc_auc_score(te["label_long"], p)), 4) if len(set(te["label_long"])) > 1 else None,
        "brier": round(float(brier_score_loss(te["label_long"], p)), 4) if len(te) else None,
        "cox_c_index_test": round(c_index(test["duration_days"].values, test["event"].values, risk), 4),
        "calibration": calib(te["label_long"].values, p) if len(te) else [],
        "fairness_by_district": {}, "fairness_by_female_defendant": {},
        "features": FEATURES, "excluded_protected_attributes": ["religion", "caste", "gender (used only for evaluation)"],
    }
    te = te.assign(p=p)
    for col, key in (("district", "fairness_by_district"), ("female_defendant", "fairness_by_female_defendant")):
        for val, g in te.groupby(col, observed=True):
            if len(g) >= 50 and g["label_long"].nunique() > 1:
                report[key][str(val)] = {"n": int(len(g)), "auc": round(float(roc_auc_score(g["label_long"], g["p"])), 3),
                                         "mean_predicted": round(float(g["p"].mean()), 3),
                                         "observed_rate": round(float(g["label_long"].mean()), 3)}
    (ROOT / "ml" / "models").mkdir(parents=True, exist_ok=True)
    (ROOT / "ml" / "reports").mkdir(parents=True, exist_ok=True)
    clf.booster_.save_model(str(ROOT / "ml" / "models" / "delay_lgbm.txt"))
    meta = {"features": FEATURES, "categorical": {c: [str(x) for x in df[c].cat.categories] for c in CATEGORICAL},
            "horizon_years": HORIZON_YEARS, "demo": demo}
    (ROOT / "ml" / "models" / "delay_meta.json").write_text(json.dumps(meta, indent=1))
    (ROOT / "ml" / "reports" / "delay_model.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in ("calibration", "fairness_by_district")}, indent=2))


if __name__ == "__main__":
    main()
