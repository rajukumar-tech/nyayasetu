"""Hybrid judgment retrieval (BM25 + LSA dense vectors) over a LOCAL corpus of High Court
judgments. Hard rule: a judgment can be shown only if it exists in the corpus; any
citation not found in the corpus is stripped and logged (see `guard_citations`).

Corpus format: data/judgments/*.jsonl, one passage per line:
  {"id", "citation", "court", "date", "url", "text", "synthetic": bool}
`data/external/download_hc_judgments.py` builds it from the public HC judgments dataset.
The repo ships only data/judgments/synthetic_test_corpus.jsonl — clearly fictional
passages labelled SYNTHETIC so the pipeline can be tested without inventing real case law.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.core.config import settings

log = logging.getLogger("nyayasetu.citations")
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass
class Passage:
    id: str
    citation: str
    court: str
    date: str
    url: str
    text: str
    synthetic: bool


@dataclass
class Hit:
    passage: Passage
    score: float
    bm25: float
    dense: float
    snippet: str


def _tok(s: str) -> list[str]:
    return _TOKEN.findall(s.lower())


class JudgmentIndex:
    def __init__(self, passages: list[Passage]):
        from rank_bm25 import BM25Okapi
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.passages = passages
        self.by_citation = {_norm_cite(p.citation): p for p in passages}
        docs = [_tok(p.text + " " + p.citation) for p in passages] or [[""]]
        self.bm25 = BM25Okapi(docs)
        self.tfidf = TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2), min_df=1)
        X = self.tfidf.fit_transform([p.text for p in passages] or [""])
        k = max(1, min(64, X.shape[1] - 1, X.shape[0] - 1))
        self.svd = TruncatedSVD(n_components=k, random_state=0) if X.shape[0] > 2 else None
        dense = self.svd.fit_transform(X) if self.svd else X.toarray()
        self.dense = dense / (np.linalg.norm(dense, axis=1, keepdims=True) + 1e-9)

    @classmethod
    def load(cls, directory: Path | None = None) -> "JudgmentIndex":
        directory = directory or settings.judgments_dir
        passages = []
        for f in sorted(Path(directory).glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    d = json.loads(line)
                    passages.append(Passage(d["id"], d["citation"], d.get("court", ""), d.get("date", ""),
                                            d.get("url", ""), d["text"], bool(d.get("synthetic", False))))
        return cls(passages)

    def search(self, query: str, k: int = 3, alpha: float = 0.5) -> list[Hit]:
        if not self.passages:
            return []
        q = _tok(query)
        b = np.array(self.bm25.get_scores(q))
        b = b / (b.max() + 1e-9) if b.max() > 0 else b
        qv = self.tfidf.transform([query])
        qd = self.svd.transform(qv) if self.svd else qv.toarray()
        qd = qd / (np.linalg.norm(qd) + 1e-9)
        d = (self.dense @ qd.T).ravel()
        score = alpha * b + (1 - alpha) * np.clip(d, 0, None)
        order = np.argsort(-score)[:k]
        return [Hit(self.passages[i], float(score[i]), float(b[i]), float(d[i]), _snippet(self.passages[i].text, q))
                for i in order if score[i] > 0.15]

    def exists(self, citation: str) -> bool:
        return _norm_cite(citation) in self.by_citation


def _norm_cite(c: str) -> str:
    return re.sub(r"[^a-z0-9]", "", c.lower())


def _snippet(text: str, q: list[str], width: int = 320) -> str:
    low = text.lower()
    pos = min((low.find(t) for t in q if len(t) > 3 and low.find(t) >= 0), default=0)
    start = max(0, pos - width // 3)
    return ("…" if start else "") + text[start:start + width].strip() + ("…" if start + width < len(text) else "")


# Citation-like strings: "(2019) 5 SCC 123", "AIR 1979 SC 1360", "2023 SCC OnLine Kar 12", "Crl.P. No. 123/2020",
# and our synthetic ids.
CITATION_RE = re.compile(
    r"\(\d{4}\)\s*\d+\s*[A-Z][A-Za-z.]*\s*\d+|AIR\s+\d{4}\s+[A-Z][A-Za-z]*\s+\d+|\d{4}\s+SCC\s+OnLine\s+\w+\s+\d+|"
    r"(?:Crl\.?\s*[A-Z]\.?|W\.?P\.?|Crl\.?\s*A\.?)\s*No\.?\s*\d+\s*/\s*\d{4}|SYNTHETIC-TEST-\d{4}")


def guard_citations(text: str, index: "JudgmentIndex", context: str = "") -> tuple[str, list[str]]:
    """Strip any citation that is not in the retrieved corpus; log each removal."""
    removed = []

    def repl(m: re.Match) -> str:
        c = m.group(0)
        if index.exists(c):
            return c
        removed.append(c)
        log.warning("Stripped citation not in corpus: %r (%s)", c, context)
        return "[citation removed — not found in verified corpus]"
    return CITATION_RE.sub(repl, text), removed


@lru_cache(maxsize=1)
def get_index() -> JudgmentIndex:
    return JudgmentIndex.load()
