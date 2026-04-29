"""Claim extraction.

Uses the configured credit-based LLM when available; otherwise falls back to a
heuristic single-sentence cleanup so the UX always returns something.
"""
from __future__ import annotations

import re
from typing import Optional

from .. import config
from . import ai_client, demo_cache


def _load_prompt() -> str:
    return (config.PROMPTS_DIR / config.EXTRACT_PROMPT).read_text(encoding="utf-8")


def _heuristic(raw_text: str) -> str:
    text = re.sub(r"\s+", " ", raw_text).strip()
    # take first sentence-ish, cap length
    parts = re.split(r"(?<=[.!?])\s+", text)
    candidate = parts[0] if parts else text
    if len(candidate) > 220:
        candidate = candidate[:217].rstrip() + "..."
    return candidate


async def extract_claim(raw_text: str) -> str:
    if config.DEMO_MODE:
        cached = demo_cache.find_extract(raw_text)
        if cached:
            return cached

    prompt = _load_prompt().replace("{raw_text}", raw_text)
    response: Optional[str] = await ai_client.generate_text(
        prompt,
        temperature=0.1,
        timeout=30.0,
    )
    if response:
        # take first non-empty line
        for line in response.splitlines():
            line = line.strip().strip('"').strip("'")
            if line:
                return line
    return _heuristic(raw_text)
