"""Retrieval over the seed corpus. If chromadb + sentence-transformers are
installed we use real vector search; otherwise we fall back to a simple
keyword overlap ranker so the demo still produces sensible evidence."""
from __future__ import annotations

import json
import re
from typing import List, Optional

from .. import config

_DOCS: Optional[List[dict]] = None


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


_TOKEN_RE = re.compile(r"[a-z0-9\-]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2}


def keyword_search(claim: str, k: int = 5) -> List[dict]:
    claim_tokens = _tokens(claim)
    scored = []
    for doc in _load_docs():
        doc_tokens = _tokens(
            f"{doc.get('supplement','')} {doc.get('source_title','')} {doc.get('full_text','')}"
        )
        if not doc_tokens:
            continue
        overlap = len(claim_tokens & doc_tokens)
        if doc.get("supplement", "").lower() in claim.lower():
            overlap += 5
        if overlap > 0:
            scored.append((overlap, doc))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [doc for _, doc in scored[:k]]


def retrieve(claim: str, k: int = 5) -> List[dict]:
    """Public entrypoint. Currently keyword search; swap in vector search
    once chromadb is wired up."""
    return keyword_search(claim, k=k)
