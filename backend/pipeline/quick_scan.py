"""Lightweight live-scan pipeline for the Chrome extension.

Two-stage approach:
  1. Fast pre-screen (~50 tokens) — asks the LLM if the content contains
     verifiable health claims worth fact-checking.  Skips if score < 0.5.
  2. Full extraction — pulls out up to 5 claims with verdicts.

Keeps API costs low because most content never reaches stage 2.
"""
from __future__ import annotations

from typing import Optional

from .. import config
from ..models import QuickScanClaim, QuickScanResponse
from . import ai_client

FITNESS_KEYWORDS = {
    "creatine", "bcaa", "protein", "supplement", "testosterone", "fat burn",
    "weight loss", "muscle", "workout", "pre-workout", "collagen", "tongkat",
    "ashwagandha", "metabolism", "cortisol", "hormone", "gains", "bulking",
    "cutting", "macros", "calories", "whey", "casein", "amino acid",
    "hypertrophy", "anabolic", "catabolic", "recovery", "soreness",
    "inflammation", "detox", "cleanse", "gut health", "superfood",
    "keto", "intermittent fasting", "carbs", "insulin", "glycemic",
    "electrolytes", "hydration", "cardio", "hiit", "vo2 max",
    "flexibility", "mobility", "posture", "sleep", "melatonin",
}

_PRESCREEN_THRESHOLD = 0.5


def _has_fitness_content(text: str) -> bool:
    lower = text.lower()
    return sum(1 for kw in FITNESS_KEYWORDS if kw in lower) >= 2


async def _prescreen(text: str) -> float:
    """Return 0-1 confidence that the text contains fact-checkable health claims."""
    prompt = f"""Does this text contain specific, verifiable health or fitness claims that a viewer might follow as advice?
Do NOT count personal anecdotes, figures of speech, opinions, or common knowledge.
Only count concrete cause-and-effect assertions or specific recommendations.

Return ONLY valid JSON: {{"score": 0.0 to 1.0, "reason": "one sentence"}}

Text (first 1500 chars):
{text[:1500]}"""

    raw = await ai_client.generate_text(
        prompt,
        provider=config.PRIMARY_LLM_PROVIDER,
        system="You quickly assess whether fitness content contains verifiable health claims. Return JSON only.",
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
        print(f"[QUICK-SCAN] Pre-screen score={score:.2f} reason={reason}")
        return max(0.0, min(1.0, score))
    except (TypeError, ValueError):
        return 0.0


async def scan(
    text: str,
    *,
    url: Optional[str] = None,
    platform: Optional[str] = None,
    content_type: Optional[str] = None,
) -> QuickScanResponse:
    text = text.strip()[:5000]

    if not _has_fitness_content(text):
        return QuickScanResponse(claims=[], scan_time_ms=0, flagged=False)

    # ── Stage 1: fast pre-screen ──────────────────────────────────────────────
    score = await _prescreen(text)
    if score < _PRESCREEN_THRESHOLD:
        print(f"[QUICK-SCAN] Below threshold ({score:.2f} < {_PRESCREEN_THRESHOLD}) — skipping full scan")
        return QuickScanResponse(claims=[], scan_time_ms=0, flagged=False)

    # ── Stage 2: full claim extraction ────────────────────────────────────────
    is_transcript = content_type == "transcript"

    timestamp_fields = ""
    timestamp_rules = ""
    if is_transcript:
        timestamp_fields = """
      "start_time": 90.0,
      "end_time": 120.0,
      "timestamp_label": "1:30","""
        timestamp_rules = """
- The text contains timestamped transcript segments in [M:SS] format.
- For each claim, extract the timestamp where it appears.
- Set start_time to the seconds value of the [M:SS] marker where the claim begins.
- Set end_time to the start_time of the next segment or start_time + 30 if it's the last.
- Set timestamp_label to the human-readable [M:SS] string (without brackets)."""

    prompt = f"""Extract concrete health/fitness claims from this text that could mislead viewers.

Rules:
- Only extract verifiable cause-and-effect claims or specific health recommendations.
- Skip figures of speech, anecdotes, opinions, common knowledge, and personal results.
- Up to 5 claims max. For each, give a one-sentence scientific verdict.
- risk_level: "high" = dangerous, "medium" = misleading/exaggerated, "low" = minor inaccuracy.
- confidence: your assessment confidence.
- category: supplement, training, nutrition, weight_loss, muscle_gain, hormones, recovery, sleep, injury, product_marketing, medical_boundary, or other.{timestamp_rules}

Return ONLY valid JSON:
{{
  "claims": [
    {{
      "claim_id": "claim_1",
      "text": "the claim as stated",
      "category": "supplement",
      "risk_level": "medium",
      "confidence": "high",
      "brief_verdict": "one sentence scientific reality check"{f",{timestamp_fields}" if is_transcript else ""}
    }}
  ]
}}

If no dubious claims found, return {{"claims": []}}.

Text{f' (from {platform})' if platform else ''}:
{text}""".strip()

    raw = await ai_client.generate_text(
        prompt,
        provider=config.PRIMARY_LLM_PROVIDER,
        system="You are a precise fitness-science fact checker. Only flag concrete, verifiable health claims. Return valid JSON only.",
        json_mode=True,
        temperature=0.0,
        timeout=15.0,
    )

    parsed = ai_client.parse_json_loose(raw or "")
    if not parsed or not isinstance(parsed, dict):
        return QuickScanResponse(claims=[], scan_time_ms=0, flagged=False)

    claims = []
    for i, item in enumerate(parsed.get("claims", [])[:5], start=1):
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
                category=category if category in {
                    "supplement", "training", "nutrition", "weight_loss",
                    "muscle_gain", "hormones", "recovery", "sleep",
                    "injury", "product_marketing", "medical_boundary", "other",
                } else "other",
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
