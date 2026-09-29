"""Train the entity-resolution pairwise model on synthetic labelled records and evaluate
on a held-out seed. Writes ml/models/er_model.json (plain weights, no pickle) and
ml/reports/er_eval.json.

    python ml/train_er.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "data" / "synthetic")]

import numpy as np  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

from generate import generate  # noqa: E402
from app.resolution.matcher import (  # noqa: E402
    AUTO_LINK, FEATURES, PairModel, Record, blocks, features, pairwise_metrics, resolve,
)

TRAIN_SEEDS = [1, 2, 3, 4, 5, 6]
EVAL_SEED = 7


def to_records(er: list[dict]) -> tuple[list[Record], dict[str, str]]:
    recs = [Record(r["record_id"], r["name"], r["relative_name"], r["age"], r["district"], r["police_station"],
                   r["address"], r["co_accused"], [r["cnr"]] if r["cnr"] else []) for r in er]
    return recs, {r["record_id"]: r["truth_id"] for r in er}


def pairs(recs: list[Record], truth: dict[str, str]):
    X, y, seen = [], [], set()
    for blk in blocks(recs).values():
        for i, a in enumerate(blk):
            for b in blk[i + 1:]:
                key = tuple(sorted((a.id, b.id)))
                if key in seen:
                    continue
                seen.add(key)
                f, _ = features(a, b)
                X.append([f[k] for k in FEATURES])
                y.append(int(truth[a.id] == truth[b.id]))
    return np.array(X), np.array(y)


def main() -> None:
    today = date(2026, 1, 1)
    Xs, ys = [], []
    for s in TRAIN_SEEDS:
        recs, truth = to_records(generate(today, s, 0)["er_records"])
        # prefix ids per seed so seeds don't collide
        for r in recs:
            r.id = f"{s}-{r.id}"
        truth = {f"{s}-{k}": f"{s}-{v}" for k, v in truth.items()}
        X, y = pairs(recs, truth)
        Xs.append(X)
        ys.append(y)
    X, y = np.vstack(Xs), np.concatenate(ys)
    clf = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced")
    clf.fit(X, y)
    weights = {"bias": float(clf.intercept_[0]), **{k: float(w) for k, w in zip(FEATURES, clf.coef_[0])}}

    recs, truth = to_records(generate(today, EVAL_SEED, 0)["er_records"])
    metrics = {"trained": pairwise_metrics(resolve(recs, PairModel(weights)), truth),
               "fallback_weights": pairwise_metrics(resolve(recs, PairModel(dict(PairModel.FALLBACK))), truth)}
    # precision/recall trade-off across auto-link thresholds (for docs)
    import app.resolution.matcher as m
    sweep = {}
    for thr in (0.6, 0.75, 0.85, 0.92, 0.97):
        m.AUTO_LINK = thr
        sweep[str(thr)] = pairwise_metrics(resolve(recs, PairModel(weights)), truth)
    m.AUTO_LINK = AUTO_LINK
    metrics["threshold_sweep"] = sweep
    metrics["train_pairs"] = int(len(y))
    metrics["train_positive_pairs"] = int(y.sum())

    (ROOT / "ml" / "models").mkdir(parents=True, exist_ok=True)
    (ROOT / "ml" / "reports").mkdir(parents=True, exist_ok=True)
    (ROOT / "ml" / "models" / "er_model.json").write_text(json.dumps({"features": FEATURES, "weights": weights,
                                                                       "train_seeds": TRAIN_SEEDS}, indent=2))
    (ROOT / "ml" / "reports" / "er_eval.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
