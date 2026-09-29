"""Entity resolution: blocking → pairwise features → trained logistic model → precision-first clustering.

False merges are worse than missed merges (a false merge can make someone look like a
repeat offender), so:
  * auto-link only at p ≥ AUTO_LINK (high precision),
  * hard vetoes (father's name clearly different, age gap ≥ AGE_VETO_YEARS) cap the score,
  * a merge that would put a vetoed pair in the same cluster is refused and sent to review,
  * everything in [REVIEW_LOW, AUTO_LINK) goes to the reviewer queue — never auto-merged.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from app.resolution.normalise import normalise_name, phonetic_key, phonetic_token, to_latin

AUTO_LINK = 0.92
REVIEW_LOW = 0.45
AGE_VETO_YEARS = 10
MODEL_PATH = Path(__file__).resolve().parents[3] / "ml" / "models" / "er_model.json"

FEATURES = ["name_token_sort", "name_jw_phonetic", "name_token_overlap", "alias_match", "initials_compatible",
            "father_sim", "father_missing", "age_diff_norm", "age_missing", "same_district", "same_station",
            "address_sim", "address_missing", "coaccused_overlap", "same_cnr"]


@dataclass
class Record:
    id: str
    name: str
    relative_name: str | None = None
    age: int | None = None
    district: str | None = None
    police_station: str | None = None
    address: str | None = None
    co_accused: list[str] = field(default_factory=list)
    cnrs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.norm = normalise_name(self.name)
        self.rel_key = phonetic_key(self.relative_name) if self.relative_name else ""


@dataclass
class PairScore:
    a: str
    b: str
    p: float
    features: dict[str, float]
    vetoes: list[str]
    decision: str  # link | review | no_link


def features(r1: Record, r2: Record) -> tuple[dict[str, float], list[str]]:
    n1, n2 = r1.norm, r2.norm
    f: dict[str, float] = {}
    f["name_token_sort"] = fuzz.token_sort_ratio(n1.full, n2.full) / 100
    k1, k2 = n1.key, n2.key
    f["name_jw_phonetic"] = JaroWinkler.similarity(k1, k2) if k1 and k2 else 0.0
    t1 = {phonetic_token(t) for t in n1.primary if len(t) > 1}
    t2 = {phonetic_token(t) for t in n2.primary if len(t) > 1}
    f["name_token_overlap"] = len(t1 & t2) / max(1, min(len(t1), len(t2)))
    a1 = {phonetic_key(" ".join(a)) for a in n1.aliases}
    a2 = {phonetic_key(" ".join(a)) for a in n2.aliases}
    f["alias_match"] = 1.0 if (a1 & ({k2} | a2)) or (a2 & {k1}) else 0.0
    i1 = {t[0] for t in n1.primary}
    i2 = {t[0] for t in n2.primary}
    f["initials_compatible"] = 1.0 if (i1 <= i2 or i2 <= i1) else 0.0
    vetoes: list[str] = []
    if r1.rel_key and r2.rel_key:
        f["father_sim"] = JaroWinkler.similarity(r1.rel_key, r2.rel_key)
        f["father_missing"] = 0.0
        if f["father_sim"] < 0.75:
            vetoes.append("RELATIVE_NAME_DIFFERS")
    else:
        f["father_sim"] = 0.5
        f["father_missing"] = 1.0
    if r1.age is not None and r2.age is not None:
        diff = abs(r1.age - r2.age)
        f["age_diff_norm"] = min(diff, 30) / 30
        f["age_missing"] = 0.0
        if diff >= AGE_VETO_YEARS:
            vetoes.append("AGE_GAP")
    else:
        f["age_diff_norm"] = 0.2
        f["age_missing"] = 1.0
    f["same_district"] = 1.0 if r1.district and r1.district == r2.district else 0.0
    f["same_station"] = 1.0 if r1.police_station and r1.police_station == r2.police_station else 0.0
    if r1.address and r2.address:
        f["address_sim"] = fuzz.token_set_ratio(to_latin(r1.address), to_latin(r2.address)) / 100
        f["address_missing"] = 0.0
    else:
        f["address_sim"], f["address_missing"] = 0.5, 1.0
    c1 = {phonetic_key(c) for c in r1.co_accused}
    c2 = {phonetic_key(c) for c in r2.co_accused}
    f["coaccused_overlap"] = 1.0 if c1 & c2 else 0.0
    f["same_cnr"] = 1.0 if set(r1.cnrs) & set(r2.cnrs) else 0.0
    return f, vetoes


class PairModel:
    """Logistic regression over FEATURES. Weights are trained by ml/train_er.py on synthetic
    labelled pairs; fallback weights are hand-set and conservative."""

    FALLBACK = {"bias": -9.0, "name_token_sort": 2.0, "name_jw_phonetic": 5.0, "name_token_overlap": 2.0, "alias_match": 1.5,
                "initials_compatible": 0.5, "father_sim": 4.0, "father_missing": -0.5, "age_diff_norm": -6.0,
                "age_missing": -0.5, "same_district": 0.8, "same_station": 0.8, "address_sim": 1.5, "address_missing": 0.0,
                "coaccused_overlap": 1.0, "same_cnr": 3.0}

    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or self._load() or dict(self.FALLBACK)

    @staticmethod
    def _load() -> dict[str, float] | None:
        try:
            return json.loads(MODEL_PATH.read_text())["weights"]
        except (OSError, KeyError, ValueError):
            return None

    def predict(self, f: dict[str, float]) -> float:
        z = self.weights.get("bias", 0.0) + sum(self.weights.get(k, 0.0) * v for k, v in f.items())
        return 1 / (1 + math.exp(-z))


def score_pair(r1: Record, r2: Record, model: PairModel) -> PairScore:
    f, vetoes = features(r1, r2)
    p = model.predict(f)
    if f["same_cnr"] and not vetoes:
        p = max(p, 0.97)  # same CNR = same case record (e.g. transferred case appearing twice)
    if f["alias_match"] and not vetoes:
        # a recorded alias ("@", "urf") is an explicit identity statement; with a matching relative
        # name and age it is strong evidence, otherwise it must be reviewed
        strong = f["father_sim"] >= 0.85 and not f["father_missing"] and not f["age_missing"] and f["age_diff_norm"] <= 2 / 30
        p = max(p, 0.93 if strong else REVIEW_LOW + 0.05)
    if vetoes:
        p = min(p, 0.2 if len(vetoes) > 1 or "AGE_GAP" in vetoes else 0.35)
    decision = "link" if p >= AUTO_LINK else "review" if p >= REVIEW_LOW else "no_link"
    return PairScore(r1.id, r2.id, round(p, 4), f, vetoes, decision)


def blocks(records: list[Record]) -> dict[str, list[Record]]:
    """Block on each phonetic name token (+ alias keys). Records sharing no key are never compared."""
    out: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        keys = {phonetic_token(t) for t in r.norm.primary if len(t) > 2}
        keys |= {phonetic_token(t) for a in r.norm.aliases for t in a if len(t) > 2}
        keys |= {f"cnr:{c}" for c in r.cnrs}
        for k in keys:
            out[k].append(r)
    return out


@dataclass
class Resolution:
    clusters: list[set[str]]
    links: list[PairScore]
    review: list[PairScore]
    refused: list[PairScore]  # would-be links blocked by a veto inside the merged cluster


def resolve(records: list[Record], model: PairModel | None = None) -> Resolution:
    model = model or PairModel()
    by_id = {r.id: r for r in records}
    scored: dict[tuple[str, str], PairScore] = {}
    for blk in blocks(records).values():
        if len(blk) > 200:
            continue  # pathological block (very common token) — rely on other keys
        for r1, r2 in combinations(sorted(blk, key=lambda r: r.id), 2):
            if (r1.id, r2.id) not in scored:
                scored[(r1.id, r2.id)] = score_pair(r1, r2, model)
    parent = {r.id: r.id for r in records}
    members: dict[str, set[str]] = {r.id: {r.id} for r in records}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    vetoed = {k for k, s in scored.items() if s.vetoes or s.p < 0.1}
    links, review, refused = [], [], []
    for s in sorted(scored.values(), key=lambda s: -s.p):
        if s.decision == "review":
            review.append(s)
            continue
        if s.decision != "link":
            continue
        ra, rb = find(s.a), find(s.b)
        if ra == rb:
            links.append(s)
            continue
        conflict = any(tuple(sorted((x, y))) in vetoed for x in members[ra] for y in members[rb])
        if conflict:
            refused.append(s)
            continue
        parent[rb] = ra
        members[ra] |= members.pop(rb)
        links.append(s)
    clusters = [m for m in members.values()]
    _ = by_id
    return Resolution(clusters, links, review, refused)


def pairwise_metrics(res: Resolution, truth: dict[str, str]) -> dict[str, float]:
    """Pairwise precision/recall/F1 + false-merge rate + cluster purity vs ground truth."""
    pred_pairs = {tuple(sorted(p)) for c in res.clusters for p in combinations(c, 2)}
    by_truth: dict[str, list[str]] = defaultdict(list)
    for rid, t in truth.items():
        by_truth[t].append(rid)
    true_pairs = {tuple(sorted(p)) for ids in by_truth.values() for p in combinations(ids, 2)}
    tp = len(pred_pairs & true_pairs)
    fp = len(pred_pairs - true_pairs)
    fn = len(true_pairs - pred_pairs)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    purity = sum(max(sum(1 for r in c if truth[r] == t) for t in {truth[r] for r in c}) for c in res.clusters) / len(truth)
    impure = sum(1 for c in res.clusters if len({truth[r] for r in c}) > 1)
    return {"precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
            "false_merge_pairs": fp, "clusters_with_false_merge": impure, "cluster_purity": round(purity, 4),
            "review_queue": len(res.review), "refused_by_veto": len(res.refused)}
