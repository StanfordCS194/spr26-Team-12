"""Lightweight live-scan pipeline for the Chrome extension.

Two-stage approach:
  1. Fast pre-screen (~50 tokens) — asks the LLM if the content contains
     verifiable claims worth fact-checking.  Skips if score < 0.3.
  2. Full extraction — pulls out up to 5 claims with verdicts.

Keeps API costs low because most content never reaches stage 2.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Dict, Optional, Tuple

log = logging.getLogger(__name__)

from .. import config
from ..models import QuickScanClaim, QuickScanResponse
from . import ai_client

# ── Client-side keyword pre-filter ─────────────────────────────────────────────
# Broad set covering health/fitness AND politics/current-events/misinformation.

HEALTH_KEYWORDS = {
    # Supplements & ingredients
    "creatine", "bcaa", "protein", "supplement", "collagen", "tongkat",
    "ashwagandha", "whey", "casein", "amino acid", "pre-workout",
    "probiotic", "vitamin", "magnesium", "zinc", "omega-3", "fish oil",
    "shilajit", "melatonin", "electrolytes", "antioxidant", "superfood",
    # Hormones & biology
    "testosterone", "estrogen", "cortisol", "hormone", "insulin",
    "metabolism", "anabolic", "catabolic", "endocrine", "thyroid",
    "serotonin", "dopamine", "growth hormone",
    # Fitness & training
    "muscle", "workout", "hypertrophy", "gains", "bulking", "cutting",
    "fat burn", "weight loss", "cardio", "hiit", "vo2 max",
    "recovery", "soreness", "overtraining",
    # Nutrition & diet
    "macros", "calories", "keto", "intermittent fasting", "carbs",
    "glycemic", "cholesterol", "saturated fat", "fiber",
    "gut health", "microbiome", "detox", "cleanse", "diet",
    # General health & medical
    "blood pressure", "heart disease", "diabetes", "cancer risk",
    "inflammation", "immune", "longevity", "anti-aging", "skin health",
    "joint", "bone density", "fertility", "sperm", "libido",
    "sleep", "insomnia", "circadian", "stress",
    "flexibility", "mobility", "posture", "hydration",
    "side effect", "health benefit", "clinical study",
}

POLITICS_KEYWORDS = {
    # Politics & governance
    "election", "democrat", "republican", "congress", "senate",
    "legislation", "policy", "regulation", "bipartisan", "filibuster",
    "executive order", "supreme court", "amendment", "electoral",
    "immigration", "border", "deportation", "asylum",
    "geopolitics", "sanctions", "diplomacy", "nato", "united nations",
    # Economics & finance
    "inflation", "gdp", "recession", "unemployment", "federal reserve",
    "interest rate", "national debt", "deficit", "tariff", "trade war",
    "tax", "subsidy", "minimum wage", "cost of living",
    # Environment & climate
    "climate change", "global warming", "carbon", "emissions",
    "renewable energy", "fossil fuel", "pollution", "deforestation",
    "sea level", "greenhouse", "net zero", "paris agreement",
    # Misinformation patterns
    "conspiracy", "cover-up", "deep state", "false flag", "hoax",
    "propaganda", "misinformation", "disinformation", "fact check",
    "debunked", "mainstream media", "censorship", "big pharma",
    "they don't want you to know", "exposed", "whistleblower",
    # Science & statistics
    "study shows", "research proves", "scientists say", "data shows",
    "percent", "statistic", "peer reviewed", "evidence",
    "correlation", "causation",
    # Social issues
    "crime rate", "gun control", "second amendment", "abortion",
    "vaccine", "vaccination", "pandemic", "public health",
    "education system", "student debt", "healthcare system",
}

CHECKABLE_KEYWORDS = HEALTH_KEYWORDS | POLITICS_KEYWORDS

_PRESCREEN_THRESHOLD = 0.3

# ── Video-level pre-screen cache ───────────────────────────────────────────────
# Keyed by video/content ID. Avoids re-running the LLM pre-screen for every
# transcript chunk from the same video.
_PRESCREEN_CACHE_TTL = 300  # 5 minutes
_prescreen_cache: Dict[str, Tuple[float, float]] = {}  # id -> (score, timestamp)


def _extract_video_id(url: Optional[str]) -> Optional[str]:
    """Pull a YouTube video ID out of common URL formats."""
    if not url:
        return None
    m = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", url)
    if m:
        return m.group(1)
    m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", url)
    if m:
        return m.group(1)
    return None


def _cache_get(video_id: str) -> Optional[float]:
    """Return cached pre-screen score if fresh, else None."""
    entry = _prescreen_cache.get(video_id)
    if entry is None:
        return None
    score, ts = entry
    if time.time() - ts > _PRESCREEN_CACHE_TTL:
        del _prescreen_cache[video_id]
        return None
    return score


def _cache_set(video_id: str, score: float) -> None:
    _prescreen_cache[video_id] = (score, time.time())


def _has_checkable_content(text: str) -> bool:
    lower = text.lower()
    return sum(1 for kw in CHECKABLE_KEYWORDS if kw in lower) >= 2


async def _prescreen(text: str) -> float:
    """Return 0-1 confidence that the text contains fact-checkable claims."""
    prompt = f"""Does this text contain claims, advice, or statements that a viewer might take as factual and that would benefit from fact-checking?

Score 0.7-1.0 if it contains ANY of:
- Health, supplement, or fitness claims (e.g. "creatine builds muscle")
- Diet or nutrition advice (e.g. "eat 1g protein per pound")
- Political or economic assertions (e.g. "inflation is caused by X")
- Statistical claims or data citations (e.g. "crime is up 50%")
- Conspiracy theories or unverified allegations
- Environmental or climate claims (e.g. "electric cars are worse for the environment")
- Historical or scientific claims presented as fact
- Product endorsements with specific benefit claims

Score 0.3-0.6 if it mentions these topics but only in passing.
Score 0.0-0.2 ONLY if the text is purely entertainment, personal vlog, or opinion with no factual claims.

Be generous — if in doubt, score higher.

Return ONLY valid JSON: {{"score": 0.0 to 1.0, "reason": "one sentence"}}

Text (first 1500 chars):
{text[:1500]}"""

    raw = await ai_client.generate_text(
        prompt,
        provider=config.PRIMARY_LLM_PROVIDER,
        system="You assess whether content contains fact-checkable claims across health, politics, science, economics, and other domains. Be generous — most informational content should score above 0.5. Return JSON only.",
        json_mode=True,
        temperature=0.0,
        timeout=8.0,
        max_tokens=60,
    )
    parsed = ai_client.parse_json_loose(raw or "")
    if not parsed or not isinstance(parsed, dict):
        return 0.0
    try:
        score = float(parsed.get("score", 0))
        reason = parsed.get("reason", "")
        log.info(f"[QUICK-SCAN] Pre-screen score={score:.2f} reason={reason}")
        return max(0.0, min(1.0, score))
    except (TypeError, ValueError):
        return 0.0


ALL_CATEGORIES = {
    "supplement", "training", "nutrition", "weight_loss",
    "muscle_gain", "hormones", "recovery", "sleep",
    "injury", "product_marketing", "medical_boundary",
    "politics", "economics", "environment", "legal",
    "statistics", "history", "science", "conspiracy",
    "other",
}


async def scan(
    text: str,
    *,
    url: Optional[str] = None,
    platform: Optional[str] = None,
    content_type: Optional[str] = None,
) -> QuickScanResponse:
    text = text.strip()[:5000]
    is_transcript = content_type == "transcript"

    # ── Transcripts skip prescreen — go straight to extraction ─────────────
    if not is_transcript:
        if not _has_checkable_content(text):
            log.info("[QUICK-SCAN] No checkable keywords found — skipping")
            return QuickScanResponse(claims=[], scan_time_ms=0, flagged=False)

        video_id = _extract_video_id(url)
        cached_score = _cache_get(video_id) if video_id else None

        if cached_score is not None:
            score = cached_score
            log.info(f"[QUICK-SCAN] Pre-screen cache HIT for video {video_id} — score={score:.2f}")
        else:
            score = await _prescreen(text)
            if video_id:
                _cache_set(video_id, score)
                log.info(f"[QUICK-SCAN] Pre-screen cached for video {video_id}")

        if score < _PRESCREEN_THRESHOLD:
            log.info(f"[QUICK-SCAN] Below threshold ({score:.2f} < {_PRESCREEN_THRESHOLD}) — skipping full scan")
            return QuickScanResponse(claims=[], scan_time_ms=0, flagged=False)

    # ── Claim extraction ───────────────────────────────────────────────────────
    timestamp_block = ""
    if is_transcript:
        timestamp_block = """
- Extract timestamps: set start_time (seconds), end_time (start_time+30), timestamp_label ("M:SS") from the [M:SS] markers."""

    prompt = f"""Extract verifiable claims from this text. Return JSON only.

Rules:
- Extract specific, verifiable claims (statistics, cause-effect, recommendations, scientific assertions).
- Skip opinions, speculation, greetings, personal stories.
- Proven facts: risk_level "low", prefix verdict with "Verified fact:".
- Always write in English even if source is another language.
- risk_level: "high"=dangerous/misleading, "medium"=exaggerated, "low"=accurate.{timestamp_block}
- category: one of supplement|training|nutrition|weight_loss|muscle_gain|hormones|recovery|sleep|injury|product_marketing|medical_boundary|politics|economics|environment|legal|statistics|history|science|conspiracy|other

Return: {{"claims":[{{"claim_id":"claim_1","text":"...","category":"...","risk_level":"...","confidence":"high|medium|low","brief_verdict":"..."{', "start_time":0.0,"end_time":30.0,"timestamp_label":"0:00"' if is_transcript else ''}}}]}}

Text:
{text}""".strip()

    raw = await ai_client.generate_text(
        prompt,
        provider=config.PRIMARY_LLM_PROVIDER,
        system="Extract all verifiable claims. Be thorough. Respond in English. JSON only.",
        json_mode=True,
        temperature=0.0,
        timeout=20.0,
    )

    log.info(f"[QUICK-SCAN] Extraction raw response: {(raw or '(none)')[:300]}")
    parsed = ai_client.parse_json_loose(raw or "")
    if not parsed or not isinstance(parsed, dict):
        log.info("[QUICK-SCAN] Failed to parse extraction response")
        return QuickScanResponse(claims=[], scan_time_ms=0, flagged=False)

    claims = []
    for i, item in enumerate(parsed.get("claims", [])[:30], start=1):
        text_val = str(item.get("text") or "").strip()
        if len(text_val) < 8:
            continue
        risk = str(item.get("risk_level") or "low")
        if risk not in {"low", "medium", "high"}:
            risk = "low"
        confidence = str(item.get("confidence") or "medium")
        if confidence not in {"low", "medium", "high"}:
            confidence = "medium"
        category = str(item.get("category") or "other")
        # Parse optional timestamp fields (transcript scans only)
        start_time = item.get("start_time")
        end_time = item.get("end_time")
        timestamp_label = item.get("timestamp_label")
        if start_time is not None:
            try:
                start_time = float(start_time)
                if start_time < 0:
                    start_time = None
            except (TypeError, ValueError):
                start_time = None
        if end_time is not None:
            try:
                end_time = float(end_time)
                if end_time < 0:
                    end_time = None
            except (TypeError, ValueError):
                end_time = None
        if timestamp_label is not None:
            timestamp_label = str(timestamp_label).strip()[:10] or None

        claims.append(
            QuickScanClaim(
                claim_id=str(item.get("claim_id") or f"claim_{i}"),
                text=text_val[:300],
                category=category if category in ALL_CATEGORIES else "other",
                risk_level=risk,
                confidence=confidence,
                brief_verdict=str(item.get("brief_verdict") or "")[:200],
                start_time=start_time,
                end_time=end_time,
                timestamp_label=timestamp_label,
            )
        )

    return QuickScanResponse(
        claims=claims,
        scan_time_ms=0,
        flagged=len(claims) > 0,
    )
