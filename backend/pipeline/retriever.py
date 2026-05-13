"""Retrieval over the curated corpus.

Default ranker is a pure-Python TF-IDF cosine similarity over each document's
``title + supplement + full_text``. This produces much better recall on
naturally phrased claims than the previous keyword-overlap ranker while staying
dependency-free.

A keyword-overlap fallback is kept as a safety net for the rare case where
TF-IDF scores are all zero. The longer-term path is to swap the body of
``retrieve`` for chromadb + sentence-transformers; that wiring is intentionally
left for later so the demo path stays dependency-free.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

from .. import config

_DOCS: Optional[List[dict]] = None
_INDEX: Optional["_TfIdfIndex"] = None


# ── Loading ────────────────────────────────────────────────────────────────

def _load_docs() -> List[dict]:
    global _DOCS
    if _DOCS is None:
        docs: List[dict] = []
        for path in config.CORPUS_DIR.glob("*.json"):
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
                if isinstance(payload, list):
                    docs.extend(payload)
        _DOCS = docs
    return _DOCS


# ── Tokenisation ───────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-z0-9\-]+")
# Small fitness-science stopword list; we keep technical terms intact.
_STOP = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "but", "are",
    "was", "were", "you", "your", "have", "has", "had", "not", "into",
    "than", "then", "their", "they", "them", "its", "it's", "its'", "any",
    "all", "more", "less", "most", "least", "some", "such", "also", "only",
    "very", "much", "many", "few", "lot", "lots", "what", "when", "where",
    "which", "while", "would", "could", "should", "will", "can", "cannot",
    "about", "after", "before", "between", "during", "every", "each",
})


def _tokens(text: str) -> List[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) > 2 and t not in _STOP]


def _doc_text(doc: dict) -> str:
    return " ".join(
        str(doc.get(field) or "")
        for field in ("supplement", "source_title", "notes", "full_text")
    )


# ── TF-IDF index ───────────────────────────────────────────────────────────

class _TfIdfIndex:
    """Tiny stdlib TF-IDF index.

    log(N / df) IDF with smoothing, L2-normalized TF-IDF vectors, cosine
    similarity via dot product. Built lazily on first query.
    """

    def __init__(self, docs: List[dict]):
        self.docs = docs
        self.tokenized: List[List[str]] = [_tokens(_doc_text(d)) for d in docs]
        df: Counter[str] = Counter()
        for tokens in self.tokenized:
            df.update(set(tokens))
        n = max(1, len(docs))
        self.idf: Dict[str, float] = {
            term: math.log((n + 1) / (count + 1)) + 1.0
            for term, count in df.items()
        }
        self.vectors: List[Dict[str, float]] = [
            self._vectorize(tokens) for tokens in self.tokenized
        ]

    def _vectorize(self, tokens: List[str]) -> Dict[str, float]:
        if not tokens:
            return {}
        tf = Counter(tokens)
        vec = {term: count * self.idf.get(term, 0.0) for term, count in tf.items()}
        norm = math.sqrt(sum(value * value for value in vec.values()))
        if norm == 0:
            return {}
        return {term: value / norm for term, value in vec.items()}

    def query(self, claim: str, k: int) -> List[Tuple[float, dict]]:
        query_vec = self._vectorize(_tokens(claim))
        if not query_vec:
            return []
        scored: List[Tuple[float, dict]] = []
        for doc, doc_vec in zip(self.docs, self.vectors):
            if not doc_vec:
                continue
            # Cosine sim = dot product of L2-normalized vectors.
            score = sum(weight * doc_vec.get(term, 0.0) for term, weight in query_vec.items())
            # Supplement-name boost: docs tagged for a specific topic that the
            # claim explicitly mentions get a strong recall bump.
            supplement = str(doc.get("supplement") or "").lower().replace("_", " ")
            if supplement and supplement in claim.lower():
                score += 0.35
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:k]


def _get_index() -> _TfIdfIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = _TfIdfIndex(_load_docs())
    return _INDEX


# ── Public ranking entry points ────────────────────────────────────────────

def keyword_search(claim: str, k: int = 5) -> List[dict]:
    """Legacy keyword-overlap fallback. Kept for safety / debugging."""
    claim_tokens = set(_tokens(claim))
    scored: List[Tuple[int, dict]] = []
    for doc in _load_docs():
        doc_tokens = set(_tokens(_doc_text(doc)))
        if not doc_tokens:
            continue
        overlap = len(claim_tokens & doc_tokens)
        supplement = str(doc.get("supplement") or "").lower().replace("_", " ")
        if supplement and supplement in claim.lower():
            overlap += 5
        if overlap > 0:
            scored.append((overlap, doc))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [doc for _, doc in scored[:k]]


def retrieve(claim: str, k: int = 5) -> List[dict]:
    """Rank corpus docs against ``claim``.

    TF-IDF cosine similarity first, with a keyword-overlap fallback when the
    query produced no positive scores (e.g., out-of-vocabulary single-word
    queries). This entry point is intentionally synchronous; ``source_search``
    awaits in its own coroutine.
    """
    index = _get_index()
    hits = index.query(claim, k=k)
    if hits:
        return [doc for _, doc in hits]
    return keyword_search(claim, k=k)
