"""Feature 1 orchestration: transcript -> claims -> agreement-gated checks -> report."""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import List

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
from . import ai_client, product_recommender, source_search

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
        f"[{idx}] {source.title}\nURL: {source.url}\nType: {source.source_type}\nYear: {source.year or 'unknown'}\nSnippet: {source.snippet[:900]}"
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
    sources = await source_search.search_sources(claim.normalized_claim, limit=5)
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
    recommendations = product_recommender.recommend_for_claim(claim)
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
    impacts = {
        "supports": 5,
        "partially_supports": 2,
        "mixed": 0,
        "weak": -4,
        "contradicts": -8,
        "insufficient": -2,
    }
    score = 75
    for result in results:
        score += impacts.get(result.agreement.final_direction, 0)
        if result.claim.risk_level == "high" and result.agreement.final_direction in {"weak", "contradicts"}:
            score -= 5
        if result.agreement.agreement_level in {"conclusion_disagreement", "source_disagreement"}:
            score -= 3
    return max(0, min(100, score))


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
