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

_PRESCREEN_THRESHOLD = 0.3


def _has_fitness_content(text: str) -> bool:
    lower = text.lower()
    return sum(1 for kw in FITNESS_KEYWORDS if kw in lower) >= 2


async def _prescreen(text: str) -> float:
    """Return 0-1 confidence that the text contains fact-checkable health claims."""
    prompt = f"""Does this text discuss health, fitness, supplements, nutrition, or exercise in a way that a viewer might take as advice or guidance?

Score 0.7-1.0 if it contains ANY of:
- Supplement recommendations or claims (e.g. "creatine builds muscle")
- Diet or nutrition advice (e.g. "eat 1g protein per pound")
- Exercise or training guidance (e.g. "you should train to failure")
- Health cause-and-effect statements (e.g. "fasting boosts testosterone")
- Product endorsements with health benefits

Score 0.3-0.6 if the text mentions fitness topics but only in passing.
Score 0.0-0.2 ONLY if the text has nothing to do with health or fitness advice.

Be generous — if in doubt, score higher. The text already matched fitness keywords.

Return ONLY valid JSON: {{"score": 0.0 to 1.0, "reason": "one sentence"}}

Text (first 1500 chars):
{text[:1500]}"""

    raw = await ai_client.generate_text(
        prompt,
        provider=config.PRIMARY_LLM_PROVIDER,
        system="You assess whether content discusses health or fitness topics. Be generous — most fitness creator content should score above 0.5. Return JSON only.",
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

    prompt = f"""Extract health, fitness, or supplement claims from this text that a viewer might act on.

Rules:
- Extract any specific health claim, recommendation, or cause-and-effect statement.
- Include claims about supplements, diets, exercises, hormones, medical topics, etc.
- Include claims even if they are stated as facts or educational content — they still need checking.
- Skip purely personal stories ("I felt great"), greetings, and non-health content.
- Up to 5 claims max. For each, give a one-sentence scientific verdict.
- risk_level: "high" = potentially dangerous if wrong, "medium" = misleading/exaggerated, "low" = minor or likely accurate.
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

If the text contains NO health or fitness claims at all, return {{"claims": []}}.

Text{f' (from {platform})' if platform else ''}:
{text}""".strip()

    raw = await ai_client.generate_text(
        prompt,
        provider=config.PRIMARY_LLM_PROVIDER,
        system="You extract health and fitness claims from text. Be inclusive — extract any claim a viewer might follow as advice. Return valid JSON only.",
        json_mode=True,
        temperature=0.0,
        timeout=15.0,
    )

    print(f"[QUICK-SCAN] Extraction raw response: {(raw or '(none)')[:300]}")
    parsed = ai_client.parse_json_loose(raw or "")
    if not parsed or not isinstance(parsed, dict):
        print("[QUICK-SCAN] Failed to parse extraction response")
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
