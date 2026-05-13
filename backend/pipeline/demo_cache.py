"""Demo-mode lookup. Matches claim text against keyword sets defined in
data/cached_verdicts.json so the showcase claims always work.

Two ``match`` formats are accepted in cached_verdicts.json:

  - Flat list of strings — every token must be a substring of the claim::

        "match": ["creatine", "hair loss"]

  - List of lists — every inner list contributes one required slot; that
    slot is satisfied if ANY of its entries is a substring of the claim
    (synonyms / paraphrases)::

        "match": [
            ["creatine"],
            ["hair loss", "hair", "bald", "alopecia"]
        ]

The two formats can be mixed within the same file (flat entries are kept
for back-compat).
"""
from __future__ import annotations

import hashlib
import json
from typing import List, Optional, Union

from .. import config

_CACHE: Optional[dict] = None

# Each "slot" is either a single substring or a list of synonym substrings.
_Slot = Union[str, List[str]]


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(config.CACHED_VERDICTS_PATH, "r", encoding="utf-8") as fh:
            _CACHE = json.load(fh)
    return _CACHE


def claim_hash(claim: str) -> str:
    return hashlib.sha1(claim.lower().strip().encode("utf-8")).hexdigest()[:12]


def _slot_matches(slot: _Slot, text: str) -> bool:
    if isinstance(slot, list):
        return any(isinstance(alt, str) and alt and alt.lower() in text for alt in slot)
    return isinstance(slot, str) and bool(slot) and slot.lower() in text


def _entry_matches(entry: dict, text: str) -> bool:
    slots = entry.get("match") or []
    if not slots:
        return False
    return all(_slot_matches(slot, text) for slot in slots)


def find_extract(raw_text: str) -> Optional[str]:
    """Try to map raw user input to a canonical extracted claim."""
    text = raw_text.lower()
    for entry in _load().get("showcase", []):
        if _entry_matches(entry, text):
            return entry.get("extracted_claim")
    return None


def find_verdict(extracted_claim: str) -> Optional[dict]:
    text = extracted_claim.lower()
    for entry in _load().get("showcase", []):
        if _entry_matches(entry, text):
            return entry.get("verdict")
    return None
