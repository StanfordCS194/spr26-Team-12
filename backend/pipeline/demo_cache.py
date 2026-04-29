"""Demo-mode lookup. Hashes the extracted claim and matches keyword sets
from data/cached_verdicts.json so the showcase claims always work."""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from .. import config

_CACHE: Optional[dict] = None


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(config.CACHED_VERDICTS_PATH, "r", encoding="utf-8") as fh:
            _CACHE = json.load(fh)
    return _CACHE


def claim_hash(claim: str) -> str:
    return hashlib.sha1(claim.lower().strip().encode("utf-8")).hexdigest()[:12]


def find_extract(raw_text: str) -> Optional[str]:
    """Try to map raw user input to a canonical extracted claim."""
    text = raw_text.lower()
    for entry in _load().get("showcase", []):
        if all(token in text for token in entry["match"]):
            return entry["extracted_claim"]
    return None


def find_verdict(extracted_claim: str) -> Optional[dict]:
    text = extracted_claim.lower()
    for entry in _load().get("showcase", []):
        if all(token in text for token in entry["match"]):
            return entry["verdict"]
    return None
