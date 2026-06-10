"""Feature 1 orchestration: transcript -> claims -> agreement-gated checks -> report."""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import List, Optional

from .. import config
from ..models import (
    AgentVerdict,
    AgreementResult,
    ClaimCheckResult,
    ClipReportResponse,
    EvidenceDirection,
    ExtractedClaimItem,
    SourceCandidate,
)
from . import ai_client, demo_cache, product_recommender, source_search

# How a 1-5 evidence tier from the demo cache maps to the public
# EvidenceDirection labels the UI renders.
_TIER_TO_DIRECTION: dict[int, EvidenceDirection] = {
    5: "supports",
    4: "supports",
    3: "mixed",
    2: "weak",
    1: "contradicts",
}

# Curated cache study-type strings -> rough quality_score for display dots.
_CACHE_STUDY_QUALITY = {
    "meta_analysis":  1.00,
    "systematic_review": 0.95,
    "position_stand": 0.92,
    "rct":            0.88,
    "review":         0.75,
    "fact_sheet":     0.78,
    "observational":  0.60,
}

ALLOWED_DIRECTIONS = {
    "supports",
    "partially_supports",
    "mixed",
    "weak",
    "contradicts",
    "insufficient",
}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_AGREEMENT = {
    "strong_agreement",
    "partial_agreement",
    "source_disagreement",
    "conclusion_disagreement",
    "insufficient_sources",
}
CATEGORIES = {
    "supplement",
    "training",
    "nutrition",
    "weight_loss",
    "muscle_gain",
    "hormones",
    "recovery",
    "sleep",
    "injury",
    "product_marketing",
    "medical_boundary",
    "other",
}
SUPPLEMENT_TERMS = {
    "creatine",
    "bcaa",
    "bcaas",
    "branched-chain amino",
    "tongkat",
    "ashwagandha",
    "beta-alanine",
    "caffeine",
    "citrulline",
    "whey",
    "protein powder",
    "supplement",
}


def _infer_category(raw: str, normalized: str, category: str) -> str:
    if category in CATEGORIES and category != "other":
        return category
    text = f"{raw} {normalized}".lower()
    if any(term in text for term in SUPPLEMENT_TERMS):
        return "supplement"
    if any(term in text for term in ("testosterone", "estrogen", "cortisol", "hormone")):
        return "hormones"
    if any(term in text for term in ("muscle protein synthesis", "build muscle", "hypertrophy")):
        return "muscle_gain"
    if any(term in text for term in ("fat loss", "weight loss", "burn fat")):
        return "weight_loss"
    return "other"


def _fallback_claims(transcript: str) -> List[ExtractedClaimItem]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript) if s.strip()]
    claims = []
    for index, sentence in enumerate(sentences[:6], start=1):
        if len(sentence) < 12:
            continue
        claims.append(
            ExtractedClaimItem(
                claim_id=f"claim_{index}",
                raw_claim=sentence[:260],
                normalized_claim=sentence[:260],
                category="other",
                risk_level="low",
            )
        )
    if not claims and transcript.strip():
        claims.append(
            ExtractedClaimItem(
                claim_id="claim_1",
                raw_claim=transcript.strip()[:260],
                normalized_claim=transcript.strip()[:260],
                category="other",
                risk_level="low",
            )
        )
    return claims[:8]


def _clean_claims(payload: dict, transcript: str) -> List[ExtractedClaimItem]:
    items = payload.get("claims", []) if isinstance(payload, dict) else []
    claims: List[ExtractedClaimItem] = []
    for index, item in enumerate(items[:8], start=1):
        raw = str(item.get("raw_claim") or item.get("claim") or "").strip()
        normalized = str(item.get("normalized_claim") or raw).strip()
        if len(normalized) < 8:
            continue
        category = str(item.get("category") or "other").strip()
        risk = str(item.get("risk_level") or "low").strip()
        claims.append(
            ExtractedClaimItem(
                claim_id=str(item.get("claim_id") or f"claim_{index}"),
                raw_claim=raw[:350] or normalized[:350],
                normalized_claim=normalized[:350],
                category=_infer_category(raw, normalized, category),  # type: ignore[arg-type]
                risk_level=risk if risk in {"low", "medium", "high"} else "low",  # type: ignore[arg-type]
            )
        )
    return claims or _fallback_claims(transcript)


async def extract_claims(transcript: str) -> List[ExtractedClaimItem]:
    prompt = f"""
Extract checkable factual fitness-science claims from this transcript.

Rules:
- Return only JSON.
- Extract up to 8 atomic claims.
- Ignore jokes, filler, intros, and non-factual opinions.
- Normalize vague bro-science into testable claims.
- Categories must be one of: {sorted(CATEGORIES)}.
- risk_level must be low, medium, or high.

JSON schema:
{{
  "claims": [
    {{
      "claim_id": "claim_1",
      "raw_claim": "original wording",
      "normalized_claim": "clear testable claim",
      "category": "supplement",
      "risk_level": "medium"
    }}
  ]
}}

Transcript:
{transcript[:12000]}
""".strip()
    raw = await ai_client.generate_text(
        prompt,
        provider=config.PRIMARY_LLM_PROVIDER,
        system="You extract only checkable factual fitness claims. Return valid JSON.",
        json_mode=True,
        temperature=0.0,
        timeout=60.0,
    )
    parsed = ai_client.parse_json_loose(raw or "")
    if not parsed:
        return _fallback_claims(transcript)
    return _clean_claims(parsed, transcript)


def _sources_block(sources: List[SourceCandidate]) -> str:
    if not sources:
        return "No sources found."
    return "\n\n".join(
        f"[{idx}] {source.title}\n"
        f"URL: {source.url}\n"
        f"Type: {source.source_type}\n"
        f"Year: {source.year or 'unknown'}\n"
        f"Quality: {source.quality_score:.2f} (0=blog, 1=meta-analysis)\n"
        f"Snippet: {source.snippet[:900]}"
        for idx, source in enumerate(sources, start=1)
    )


def _clean_agent_verdict(provider: str, payload: dict | None) -> AgentVerdict:
    if not payload:
        return AgentVerdict(
            provider=provider,
            conclusion="insufficient",
            confidence="low",
            summary="The verifier could not produce a structured conclusion.",
        )
    conclusion = str(payload.get("conclusion") or "insufficient")
    confidence = str(payload.get("confidence") or "low")
    source_urls = payload.get("source_urls") or []
    if not isinstance(source_urls, list):
        source_urls = []
    return AgentVerdict(
        provider=provider,
        conclusion=conclusion if conclusion in ALLOWED_DIRECTIONS else "insufficient",  # type: ignore[arg-type]
        confidence=confidence if confidence in ALLOWED_CONFIDENCE else "low",  # type: ignore[arg-type]
        summary=str(payload.get("summary") or "")[:500],
        source_urls=[str(url) for url in source_urls[:5]],
        reasoning=str(payload.get("reasoning") or "")[:800],
    )


async def _run_verifier(
    claim: ExtractedClaimItem,
    sources: List[SourceCandidate],
    *,
    provider: str,
) -> AgentVerdict:
    prompt = f"""
Fact-check this fitness/broscience claim using ONLY the sources below.

Claim: {claim.normalized_claim}
Category: {claim.category}
Risk level: {claim.risk_level}

Sources:
{_sources_block(sources)}

Return only JSON:
{{
  "conclusion": "supports | partially_supports | mixed | weak | contradicts | insufficient",
  "confidence": "low | medium | high",
  "summary": "one sentence verdict",
  "source_urls": ["urls used"],
  "reasoning": "2-4 sentence explanation"
}}

If sources are irrelevant or weak, use "insufficient" or "weak". Do not invent sources.
When evidence is mixed, give more weight to higher-Quality sources (meta-analyses, systematic reviews, position stands, and RCTs > observational > generic web > blogs).
""".strip()
    raw = await ai_client.generate_text(
        prompt,
        provider=provider,
        system="You are a skeptical fitness-science verifier. Use only supplied sources. Return valid JSON.",
        json_mode=True,
        temperature=0.1,
        timeout=90.0,
    )
    return _clean_agent_verdict(provider, ai_client.parse_json_loose(raw or ""))


def _heuristic_agreement(a: AgentVerdict, b: AgentVerdict, sources: List[SourceCandidate]) -> AgreementResult:
    if not sources:
        return AgreementResult(
            agreement_level="insufficient_sources",
            final_direction="insufficient",
            confidence="low",
            summary="No credible sources were found for this claim.",
            why="Veritas needs credible source material before it can issue a conclusion.",
        )
    if a.conclusion == b.conclusion:
        level = "strong_agreement" if set(a.source_urls) & set(b.source_urls) else "partial_agreement"
        confidence = "high" if a.confidence == b.confidence == "high" else "medium"
        return AgreementResult(
            agreement_level=level,  # type: ignore[arg-type]
            final_direction=a.conclusion,
            confidence=confidence,  # type: ignore[arg-type]
            summary=a.summary or b.summary or "Both verifiers reached a similar conclusion.",
            why="Veritas found enough consistent, relevant evidence to give this claim a clear rating.",
        )
    return AgreementResult(
        agreement_level="conclusion_disagreement",
        final_direction="mixed",
        confidence="low",
            summary="Veritas needs a clearer evidence signal before rating this claim.",
            why="The available evidence did not point clearly enough in one direction, so this claim needs review.",
    )


def _clean_agreement(payload: dict | None, fallback: AgreementResult) -> AgreementResult:
    if not payload:
        return fallback
    level = str(payload.get("agreement_level") or fallback.agreement_level)
    direction = str(payload.get("final_direction") or fallback.final_direction)
    confidence = str(payload.get("confidence") or fallback.confidence)
    if level == "insufficient_sources":
        direction = "insufficient"
        confidence = "low"
    elif level in {"source_disagreement", "conclusion_disagreement"}:
        direction = "mixed"
        confidence = "low"
    return AgreementResult(
        agreement_level=level if level in ALLOWED_AGREEMENT else fallback.agreement_level,  # type: ignore[arg-type]
        final_direction=direction if direction in ALLOWED_DIRECTIONS else fallback.final_direction,  # type: ignore[arg-type]
        confidence=confidence if confidence in ALLOWED_CONFIDENCE else fallback.confidence,  # type: ignore[arg-type]
        summary=str(payload.get("summary") or fallback.summary)[:500],
        why=str(payload.get("why") or fallback.why)[:800],
    )


def _public_direction_label(direction: str) -> str:
    labels = {
        "supports": "supported",
        "partially_supports": "partly supported",
        "mixed": "mixed",
        "weak": "weakly supported",
        "contradicts": "contradicted",
        "insufficient": "not supported by enough evidence",
    }
    return labels.get(direction, direction.replace("_", " "))


def _public_agreement_result(agreement: AgreementResult) -> AgreementResult:
    if agreement.agreement_level == "insufficient_sources":
        agreement.final_direction = "insufficient"
        agreement.confidence = "low"
        agreement.summary = "Veritas needs more relevant evidence before rating this claim."
        agreement.why = "The available sources were not strong or relevant enough to support a clear rating."
        return agreement
    if agreement.agreement_level in {"source_disagreement", "conclusion_disagreement"}:
        agreement.final_direction = "mixed"
        agreement.confidence = "low"
        agreement.summary = "Veritas needs a clearer evidence signal before rating this claim."
        agreement.why = "The available evidence did not point clearly enough in one direction, so this claim needs review."
        return agreement
    label = _public_direction_label(agreement.final_direction)
    agreement.summary = f"Veritas rates this claim as {label}."
    agreement.why = "Veritas found enough consistent, relevant evidence to give this claim a clear rating."
    return agreement


async def _judge_agreement(
    claim: ExtractedClaimItem,
    sources: List[SourceCandidate],
    check_a: AgentVerdict,
    check_b: AgentVerdict,
) -> AgreementResult:
    fallback = _heuristic_agreement(check_a, check_b, sources)
    prompt = f"""
Compare two independent internal checks for a fitness-science claim.

Claim: {claim.normalized_claim}

Internal check A:
{check_a.model_dump_json()}

Internal check B:
{check_b.model_dump_json()}

Available source URLs:
{json.dumps([source.url for source in sources])}

Return only JSON:
{{
  "agreement_level": "strong_agreement | partial_agreement | source_disagreement | conclusion_disagreement | insufficient_sources",
  "final_direction": "supports | partially_supports | mixed | weak | contradicts | insufficient",
  "confidence": "low | medium | high",
  "summary": "user-facing one sentence result",
  "why": "brief explanation of agreement/disagreement"
}}

If agreement_level is source_disagreement or conclusion_disagreement, final_direction must be mixed and confidence must be low.
If agreement_level is insufficient_sources, final_direction must be insufficient and confidence must be low.
When the two checks disagree, prefer the conclusion supported by higher-quality sources (meta-analyses and RCTs from trusted domains).
""".strip()
    raw = await ai_client.generate_text(
        prompt,
        provider=config.PRIMARY_LLM_PROVIDER,
        system="You are a strict agreement judge. Return valid JSON and do not hide disagreement.",
        json_mode=True,
        temperature=0.0,
        timeout=60.0,
    )
    agreement = _clean_agreement(ai_client.parse_json_loose(raw or ""), fallback)
    if (
        check_a.conclusion == check_b.conclusion
        and agreement.agreement_level in {"strong_agreement", "partial_agreement"}
    ):
        agreement.final_direction = check_a.conclusion
        if check_a.confidence == check_b.confidence:
            agreement.confidence = check_a.confidence
    return _public_agreement_result(agreement)


def _no_llm_keys_configured() -> bool:
    """True when neither primary nor secondary LLM provider has an API key.

    In this case the verifier round can only ever return 'insufficient', so the
    public surface should fall back to a hand-curated cache or an honest
    demo-mode message rather than dressing up an empty pipeline as
    'low-confidence'.
    """
    return not (config.OPENAI_API_KEY or config.GROQ_API_KEY)


def _sources_from_cache(cached: dict) -> List[SourceCandidate]:
    sources: List[SourceCandidate] = []
    for entry in cached.get("evidence", []) or []:
        study_type = str(entry.get("study_type") or "review")
        sources.append(
            SourceCandidate(
                title=str(entry.get("source_title") or "Curated source"),
                url=str(entry.get("source_url") or ""),
                snippet=str(entry.get("relevance_note") or "")[:900],
                source_type=study_type,
                year=int(entry["year"]) if isinstance(entry.get("year"), int) else None,
                provider="curated_cache",
                quality_score=_CACHE_STUDY_QUALITY.get(study_type, 0.80),
            )
        )
    return sources


async def _check_from_demo_cache(claim: ExtractedClaimItem) -> ClaimCheckResult | None:
    """Return a fully-formed ClaimCheckResult if the claim matches a hand-curated
    demo-cache entry, else None. Bypasses LLM verifiers entirely so showcase
    claims produce real, directional verdicts when no API key is set."""
    cached = demo_cache.find_verdict(claim.normalized_claim) or demo_cache.find_verdict(claim.raw_claim)
    if not cached:
        return None
    tier = int(cached.get("tier") or 3)
    direction: EvidenceDirection = _TIER_TO_DIRECTION.get(tier, "mixed")
    confidence = str(cached.get("confidence") or "medium")
    if confidence not in ALLOWED_CONFIDENCE:
        confidence = "medium"
    summary = str(cached.get("summary") or "")[:500]
    why = str(cached.get("why") or summary)[:800]
    agreement = AgreementResult(
        agreement_level="strong_agreement",
        final_direction=direction,
        confidence=confidence,  # type: ignore[arg-type]
        summary=summary,
        why=why,
    )
    sources = _sources_from_cache(cached)
    return ClaimCheckResult(
        claim=claim,
        status="ok",
        sources=sources,
        agreement=agreement,
        recommendations=await product_recommender.recommend_for_claim(claim),
    )


# Tokens that flip claim polarity. If any appears in the claim text, an
# 'effect_direction=positive' source actually *supports* the user's framing
# (e.g., "creatine is safe" → positive safety evidence supports the claim;
# "creatine is NOT safe" → same positive evidence contradicts the claim).
_NEGATION_TOKENS = (
    " no ", " not ", " never ", " doesn't ", " does not ", " don't ", " do not ",
    " isn't ", " is not ", " won't ", " will not ", " without ", " cannot ", " can't ",
)
_SAFETY_FRAMING = ("safe", "safety", "harmless", "side effect", "harm", "harmful",
                   "dangerous", "damage", "kidney", "liver", "adverse")


def _claim_is_negated(claim_text: str) -> bool:
    padded = f" {claim_text.lower()} "
    return any(tok in padded for tok in _NEGATION_TOKENS)


def _is_safety_framed(claim_text: str) -> bool:
    return any(tok in claim_text.lower() for tok in _SAFETY_FRAMING)


def _map_effect_to_direction(effect: str, *, negated: bool, safety_framed: bool) -> Optional[EvidenceDirection]:
    """Translate a corpus 'effect_direction' into a public verdict direction
    given the claim's polarity. Returns None when the mapping is ambiguous."""
    e = (effect or "").lower()
    if e in {"positive", "supports"}:
        base: EvidenceDirection = "supports"
    elif e in {"negative", "contradicts"}:
        base = "contradicts"
    elif e in {"null", "no_effect", "none"}:
        # No measurable effect. If the claim is *asserting* a strong effect,
        # this is weak evidence against. If the claim is asserting safety
        # (where "no effect" actually means "no harmful effect"), it supports.
        base = "supports" if safety_framed else "weak"
    elif e in {"mixed", "weak"}:
        base = "mixed"
    else:
        return None
    if negated:
        # "creatine does NOT cause hair loss" inverts a contradicts → supports.
        flip = {
            "supports": "contradicts",
            "contradicts": "supports",
            "partially_supports": "weak",
            "weak": "partially_supports",
        }
        return flip.get(base, base)  # type: ignore[return-value]
    return base


_HEURISTIC_STOP = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "but", "are", "was",
    "were", "you", "your", "have", "has", "had", "not", "into", "than", "then",
    "any", "all", "more", "less", "most", "some", "such", "also", "only", "very",
    "much", "many", "few", "what", "when", "where", "which", "while", "would",
    "could", "should", "will", "can", "cannot", "about", "after", "before",
    "between", "during", "every", "each", "these", "those", "they", "them",
    "their", "there", "here", "just", "really", "still", "even", "make", "makes",
    "made", "say", "says", "said", "talk", "talks", "great", "good", "bad",
})


def _meaningful_tokens(text: str, exclude: set[str]) -> set[str]:
    raw = re.findall(r"[a-z0-9\-]+", (text or "").lower())
    return {t for t in raw if len(t) > 3 and t not in _HEURISTIC_STOP and t not in exclude}


def _claim_topic_overlaps_sources(
    claim_text: str, sources: List[SourceCandidate], supplement_excludes: set[str]
) -> bool:
    """The heuristic should only fire when the claim's actual topic is
    represented in the retrieved evidence. 'creatine causes cancer' shares
    only 'creatine' with creatine-safety sources, so we should NOT confuse
    safety evidence for cancer evidence — return False here and let the
    sources-only fallback take over."""
    claim_tokens = _meaningful_tokens(claim_text, supplement_excludes)
    if not claim_tokens:
        # Claim was just the supplement name plus stopwords — treat as
        # a generic question the corpus broadly addresses.
        return True
    source_blob = " ".join(
        f"{src.title or ''} {src.snippet or ''}" for src in sources
    )
    source_tokens = _meaningful_tokens(source_blob, supplement_excludes)
    return bool(claim_tokens & source_tokens)


def _heuristic_from_corpus(claim: ExtractedClaimItem, sources: List[SourceCandidate]) -> Optional[AgreementResult]:
    """Quality-weighted heuristic over curated corpus effect_direction tags.

    Returns None if we don't have enough signal (no curated sources, no topical
    overlap, or ambiguous polarity). Otherwise returns a real directional
    AgreementResult that the UI can render confidently."""
    curated = [
        s for s in sources
        if s.provider == "curated_corpus" and s.effect_direction and s.quality_score >= 0.8
    ]
    if not curated:
        return None

    # Build the set of supplement / topic tokens we want to ignore for the
    # relevance check — these are the "topic anchor" terms (e.g., 'creatine'
    # for creatine sources), not what the *claim* is asking about.
    supplement_excludes = set()
    for src in curated:
        for slug in (src.source_type, ""):  # placeholder; topic comes from snippet
            pass
    # Anchor tokens: any single token that appears in many source titles
    # is treated as the topic anchor and excluded from the relevance overlap.
    for term in SUPPLEMENT_TERMS:
        supplement_excludes.add(term.replace(" ", "").replace("-", ""))
        supplement_excludes.add(term)
    # Plus tokens that appear in 50%+ of source titles.
    if len(curated) >= 2:
        title_token_counts: dict[str, int] = {}
        for src in curated:
            for tok in set(re.findall(r"[a-z0-9\-]+", (src.title or "").lower())):
                if len(tok) > 3:
                    title_token_counts[tok] = title_token_counts.get(tok, 0) + 1
        threshold = max(2, len(curated) // 2)
        for tok, count in title_token_counts.items():
            if count >= threshold:
                supplement_excludes.add(tok)

    safety_framed = _is_safety_framed(claim.normalized_claim)
    # Safety-framed claims (e.g., "creatine is safe") legitimately use the
    # whole corpus of safety evidence even if no exact non-anchor token
    # overlaps. For everything else we require topical overlap.
    if not safety_framed and not _claim_topic_overlaps_sources(
        claim.normalized_claim, curated, supplement_excludes
    ):
        return None

    negated = _claim_is_negated(claim.normalized_claim)

    bucket: dict[EvidenceDirection, float] = {}
    for src in curated:
        direction = _map_effect_to_direction(
            src.effect_direction or "",
            negated=negated,
            safety_framed=safety_framed,
        )
        if direction is None:
            continue
        bucket[direction] = bucket.get(direction, 0.0) + src.quality_score

    if not bucket:
        return None

    winner = max(bucket.items(), key=lambda kv: kv[1])
    total_weight = sum(bucket.values())
    margin = winner[1] / total_weight if total_weight else 0.0
    n_supporting = sum(1 for s in curated if _map_effect_to_direction(
        s.effect_direction or "", negated=negated, safety_framed=safety_framed) == winner[0])

    if n_supporting >= 2 and margin >= 0.6:
        confidence = "high"
    elif n_supporting >= 1 and margin >= 0.5:
        confidence = "medium"
    else:
        confidence = "low"

    direction = winner[0]
    pretty_dir = _public_direction_label(direction)
    summary = f"Based on {n_supporting} curated source(s), Veritas rates this claim as {pretty_dir}."
    why = (
        f"Veritas used quality-weighted curated evidence (effect direction "
        f"tags from peer-reviewed studies) to estimate this verdict because "
        f"no LLM agent ran. For a full two-agent AI fact-check, configure "
        f"OPENAI_API_KEY or GROQ_API_KEY in backend/.env."
    )
    return AgreementResult(
        agreement_level="strong_agreement" if confidence == "high" else "partial_agreement",
        final_direction=direction,
        confidence=confidence,  # type: ignore[arg-type]
        summary=summary,
        why=why,
    )


def _demo_no_cache_agreement(sources: List[SourceCandidate]) -> AgreementResult:
    """Honest fallback when in demo mode (no LLM, no cache match, no heuristic
    signal). Surfaces the retrieved evidence rather than faking a verdict."""
    if not sources:
        return AgreementResult(
            agreement_level="insufficient_sources",
            final_direction="insufficient",
            confidence="low",
            summary="Veritas could not find evidence for this claim in demo mode.",
            why="Try a more specific fitness claim, or configure API keys in backend/.env to enable the live AI agents.",
        )
    return AgreementResult(
        agreement_level="insufficient_sources",
        final_direction="insufficient",
        confidence="low",
        summary="Demo mode: relevant sources retrieved but no AI verdict.",
        why="Veritas pulled the sources above from its curated corpus. Add OPENAI_API_KEY or GROQ_API_KEY to backend/.env and restart to run the live two-agent fact-check pipeline.",
    )


SUMMARY_TRIGGER_LEN = 320


def _heuristic_source_summary(snippet: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", snippet.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return snippet[:240]
    pick: List[str] = [sentences[0]]
    for sentence in reversed(sentences):
        lowered = sentence.lower()
        if any(
            cue in lowered
            for cue in ("conclusion", "in summary", "in conclusion", "we found", "results show")
        ):
            if sentence not in pick:
                pick.append(sentence)
            break
    summary = " ".join(pick)
    return summary[:320]


async def _attach_source_summaries(
    claim: ExtractedClaimItem,
    sources: List[SourceCandidate],
) -> None:
    """Populate `summary` on long-form sources so the UI shows a tight 1-2
    sentence takeaway instead of a copy-pasted abstract."""
    targets = [
        (idx, source)
        for idx, source in enumerate(sources)
        if source.summary == "" and len(source.snippet) > SUMMARY_TRIGGER_LEN
    ]
    if not targets:
        return

    payload_sources = [
        {"index": idx, "title": source.title, "snippet": source.snippet[:1400]}
        for idx, source in targets
    ]
    prompt = f"""
Summarize each scientific source below in 1-2 plain-English sentences,
focused on what it concludes about this fitness claim.

Claim: {claim.normalized_claim}

Rules:
- Be concrete (mention the finding, not the methodology).
- No filler ("This study examines...").
- 280 characters max per summary.
- Return JSON only.

Sources:
{json.dumps(payload_sources)}

JSON schema:
{{ "summaries": [ {{ "index": 0, "summary": "..." }} ] }}
""".strip()

    parsed: dict | None = None
    try:
        raw = await ai_client.generate_text(
            prompt,
            provider=config.PRIMARY_LLM_PROVIDER,
            system="You write tight, factual one-sentence summaries of scientific sources. Return valid JSON.",
            json_mode=True,
            temperature=0.1,
            timeout=45.0,
        )
        parsed = ai_client.parse_json_loose(raw or "")
    except Exception:
        parsed = None

    summaries_by_index: dict[int, str] = {}
    if isinstance(parsed, dict):
        for entry in parsed.get("summaries", []) or []:
            try:
                idx = int(entry.get("index"))
            except (TypeError, ValueError):
                continue
            summary_text = str(entry.get("summary") or "").strip()
            if summary_text:
                summaries_by_index[idx] = summary_text[:320]

    for idx, source in targets:
        source.summary = summaries_by_index.get(idx) or _heuristic_source_summary(source.snippet)


async def check_claim(claim: ExtractedClaimItem) -> ClaimCheckResult:
    # 1) Hand-curated cache always wins for showcase claims so creatine, BCAAs,
    #    caffeine, ashwagandha, tongkat ali, protein dosing, etc. produce real
    #    directional verdicts even without any API keys configured.
    if config.DEMO_MODE:
        cached_result = await _check_from_demo_cache(claim)
        if cached_result is not None:
            return cached_result

    sources = await source_search.search_sources(claim.normalized_claim, limit=5)

    # 2) Demo mode + no cache match + no LLM keys: don't fake a low-confidence
    #    LLM verdict.
    #    2a) First, attempt a quality-weighted heuristic over curated corpus
    #        effect_direction tags. This catches "creatine is safe" /
    #        "creatine kidneys" / "fasted cardio" style claims where we have
    #        high-quality evidence but the verbatim cache match failed.
    #    2b) If the heuristic can't produce a signal, fall back to the honest
    #        'sources retrieved, no AI verdict' message.
    if config.DEMO_MODE and _no_llm_keys_configured():
        heuristic = _heuristic_from_corpus(claim, sources)
        agreement = heuristic if heuristic is not None else _demo_no_cache_agreement(sources)
        status = "no_evidence" if agreement.agreement_level == "insufficient_sources" and not sources else "ok"
        return ClaimCheckResult(
            claim=claim,
            status=status,  # type: ignore[arg-type]
            sources=sources,
            agreement=agreement,
            recommendations=await product_recommender.recommend_for_claim(claim),
        )

    # 3) Live path — two independent LLM verifiers + agreement judge.
    #    Pre-attach 1-2 sentence AI summaries to long-form sources for the UI.
    await _attach_source_summaries(claim, sources)
    check_a = await _run_verifier(
        claim,
        sources,
        provider=config.SECONDARY_LLM_PROVIDER,
    )
    check_b = await _run_verifier(
        claim,
        sources,
        provider=config.PRIMARY_LLM_PROVIDER,
    )
    agreement = await _judge_agreement(claim, sources, check_a, check_b)
    status = "no_evidence" if agreement.agreement_level == "insufficient_sources" else "ok"
    recommendations = await product_recommender.recommend_for_claim(claim)
    return ClaimCheckResult(
        claim=claim,
        status=status,  # type: ignore[arg-type]
        sources=sources,
        agreement=agreement,
        recommendations=recommendations,
    )


def _score_report(results: List[ClaimCheckResult]) -> int:
    if not results:
        return 50
    weights = {
        "supports": 1.0,
        "partially_supports": 0.75,
        "mixed": 0.5,
        "weak": 0.25,
        "insufficient": 0.0,
        "contradicts": 0.0,
    }
    total = sum(weights.get(r.agreement.final_direction, 0.0) for r in results)
    return round((total / len(results)) * 100)


def _summary(results: List[ClaimCheckResult]) -> str:
    if not results:
        return "No checkable claims were found."
    counts: dict[str, int] = {}
    for result in results:
        key = result.agreement.final_direction
        counts[key] = counts.get(key, 0) + 1
    parts = [f"{count} {direction.replace('_', ' ')}" for direction, count in counts.items()]
    return f"Checked {len(results)} claim(s): " + ", ".join(parts) + "."


async def build_report(
    transcript: str,
    claims: List[ExtractedClaimItem],
    *,
    source: str,
    creator_name: str | None = None,
    brand_name: str | None = None,
) -> ClipReportResponse:
    start = time.perf_counter()
    selected = [claim for claim in claims if claim.selected][:8]
    results: List[ClaimCheckResult] = []
    for claim in selected:
        results.append(await check_claim(claim))
    needs_review = any(
        result.agreement.agreement_level in {"source_disagreement", "conclusion_disagreement"}
        or result.claim.risk_level == "high"
        for result in results
    )
    return ClipReportResponse(
        report_id=uuid.uuid4().hex,
        transcript=transcript,
        source=source,  # type: ignore[arg-type]
        creator_name=creator_name,
        brand_name=brand_name,
        claims=results,
        overall_summary=_summary(results),
        clip_credibility_score=_score_report(results),
        needs_human_review=needs_review,
        generation_time_ms=int((time.perf_counter() - start) * 1000),
    )
