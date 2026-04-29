"""Verdict generation. Returns one of four statuses so the UI can render
distinct UX for each failure mode rather than faking a low-confidence card.

  - ok            : we have a real verdict
  - out_of_scope  : the claim isn't a fitness-supplement claim we can answer.
                    `scope_reason` distinguishes:
                      * "prescription"  -> prescription drug / clinical
                                           pharmaceutical we don't evaluate
                      * "off_topic"     -> no supplement / nutrition signal
                                           detected at all
  - no_evidence   : in-scope but our corpus + retrieval came back empty
  - system_error  : LLM unreachable / unparseable response on the live path
"""
from __future__ import annotations

from typing import List, Optional

from .. import config
from ..models import EvidenceItem, Verdict
from . import ai_client, demo_cache, retriever


# Broad set of terms that indicate the claim is somewhere in the
# fitness-supplement / sports-nutrition domain. Anything matching this is
# considered in-scope; we may still lack curated evidence (handled below).
DOMAIN_TERMS = {
    # core supplements (covered by seed corpus / cache)
    "creatine", "ashwagandha", "beta-alanine", "beta alanine",
    "bcaa", "bcaas", "citrulline", "caffeine", "whey", "casein",
    "protein", "tongkat", "fish oil", "omega-3", "omega 3",
    "pre-workout", "preworkout", "pre workout",
    # vitamins & minerals
    "vitamin", "multivitamin", "magnesium", "zinc", "iron", "calcium",
    "potassium", "sodium", "biotin", "folate", "iodine", "selenium",
    "chromium", "boron",
    # herbs & adaptogens
    "rhodiola", "ginseng", "turmeric", "curcumin", "ginger", "maca",
    "fenugreek", "tribulus", "shilajit", "cordyceps", "reishi",
    "ginkgo", "saw palmetto",
    # nootropics & amino acids
    "nootropic", "l-theanine", "theanine", "tyrosine", "alpha-gpc",
    "alpha gpc", "lion's mane", "lions mane", "bacopa",
    # fat-loss / performance / endurance
    "yohimbine", "synephrine", "green tea", "egcg", "carnitine",
    "l-carnitine", "hmb", "betaine", "taurine", "glutamine", "arginine",
    "nitric oxide", "beta-hydroxybutyrate", "ketone",
    # hormones / signalling supplements
    "melatonin", "dhea", "ecdysterone", "turkesterone", "testosterone booster",
    # generic class words
    "supplement", "stack", "powder", "capsule", "extract",
    "amino acid", "adaptogen", "electrolyte", "intra-workout",
    "post-workout",
    # downstream effects often searched for
    "hypertrophy", "muscle gain", "fat loss", "fat burner",
    "recovery", "soreness", "endurance", "vo2", "strength gain",
    "cutting", "bulking",
}

# Prescription drugs / clinical pharmaceuticals. We don't evaluate these
# (different liability category and outside the corpus). Get a tailored
# response rather than a generic out-of-scope.
PRESCRIPTION_TERMS = {
    "viagra", "sildenafil", "cialis", "tadalafil",
    "ozempic", "wegovy", "semaglutide", "mounjaro", "tirzepatide",
    "finasteride", "propecia", "minoxidil", "rogaine",
    "adderall", "ritalin", "methylphenidate", "vyvanse",
    "trt", "testosterone replacement", "anabolic steroid", "steroid cycle",
    "trenbolone", "dianabol", "anavar", "clenbuterol", "sarm", "sarms",
    "ostarine", "rad-140", "lgd-4033",
    "ssri", "prozac", "zoloft", "lexapro", "xanax", "ambien",
    "metformin", "insulin",
}

DISPLAY_SUPPLEMENTS = [
    "creatine",
    "ashwagandha",
    "beta-alanine",
    "BCAAs",
    "citrulline malate",
    "caffeine",
    "whey protein",
    "tongkat ali",
    "fish oil",
    "pre-workout",
]


def _load_prompt() -> str:
    return (config.PROMPTS_DIR / config.VERDICT_PROMPT).read_text(encoding="utf-8")


def _format_evidence_block(docs: List[dict]) -> str:
    if not docs:
        return "(no evidence retrieved)"
    return "\n".join(
        f"[{i}] type={d.get('study_type')} year={d.get('year')} "
        f"n={d.get('sample_size')} population={d.get('population')}\n"
        f"{d.get('full_text','')}\n"
        for i, d in enumerate(docs, start=1)
    )


def _docs_to_evidence(docs: List[dict]) -> List[EvidenceItem]:
    return [
        EvidenceItem(
            source_title=d.get("source_title", "Untitled"),
            source_url=d.get("source_url", ""),
            study_type=d.get("study_type", "review"),
            year=int(d.get("year", 2020)),
            sample_size=d.get("sample_size"),
            population=d.get("population"),
            relevance_note=d.get("notes", ""),
        )
        for d in docs
    ]


def _mentions_domain(claim: str) -> bool:
    text = claim.lower()
    return any(term in text for term in DOMAIN_TERMS)


def _mentions_prescription(claim: str) -> bool:
    text = claim.lower()
    return any(term in text for term in PRESCRIPTION_TERMS)


def _scope_response(
    extracted_claim: str,
    request_id: str,
    gen_ms: int,
    reason: str = "off_topic",
) -> Verdict:
    return Verdict(
        extracted_claim=extracted_claim,
        status="out_of_scope",
        scope_reason=reason,  # type: ignore[arg-type]
        suggested_supplements=DISPLAY_SUPPLEMENTS,
        request_id=request_id,
        generation_time_ms=gen_ms,
    )


def _no_evidence_response(
    extracted_claim: str, request_id: str, gen_ms: int
) -> Verdict:
    return Verdict(
        extracted_claim=extracted_claim,
        status="no_evidence",
        suggested_supplements=DISPLAY_SUPPLEMENTS,
        request_id=request_id,
        generation_time_ms=gen_ms,
    )


def _system_error_response(
    extracted_claim: str, request_id: str, gen_ms: int, detail: str
) -> Verdict:
    return Verdict(
        extracted_claim=extracted_claim,
        status="system_error",
        error_detail=detail,
        request_id=request_id,
        generation_time_ms=gen_ms,
    )


async def generate_verdict(extracted_claim: str, request_id: str, gen_ms: int) -> Verdict:
    # 1. Demo cache (showcase claims)
    if config.DEMO_MODE:
        cached = demo_cache.find_verdict(extracted_claim)
        if cached:
            return Verdict(
                extracted_claim=extracted_claim,
                status="ok",
                tier=cached["tier"],
                summary=cached["summary"],
                effect_size=cached["effect_size"],
                dose=cached["dose"],
                population=cached["population"],
                confidence=cached["confidence"],
                why=cached["why"],
                evidence=[EvidenceItem(**e) for e in cached["evidence"]],
                request_id=request_id,
                generation_time_ms=gen_ms,
            )

    # 2. Only carve-out: prescription drugs / clinical pharmaceuticals.
    # Anything else — any supplement, vitamin, herb, nootropic, amino acid,
    # adaptogen, or sports-nutrition substance — flows through to retrieval
    # + LLM. We deliberately do NOT gate on a known-supplement whitelist:
    # Veritas covers every supplement.
    if _mentions_prescription(extracted_claim):
        return _scope_response(
            extracted_claim, request_id, gen_ms, reason="prescription"
        )

    # In demo mode the LLM isn't wired up, so any claim outside the showcase
    # cache surfaces honestly as "demo cache only" rather than a fake error.
    # Live mode uses the configured credit-based provider via ai_client.
    if config.DEMO_MODE:
        return _no_evidence_response(extracted_claim, request_id, gen_ms)

    # 3. Retrieve from corpus.
    docs = retriever.retrieve(extracted_claim, k=5)
    if not docs:
        return _no_evidence_response(extracted_claim, request_id, gen_ms)

    # 4. Live LLM verdict.
    prompt = (
        _load_prompt()
        .replace("{extracted_claim}", extracted_claim)
        .replace("{evidence_block}", _format_evidence_block(docs))
    )

    raw = await ai_client.generate_text(prompt, temperature=0.2, timeout=120.0)
    parsed: Optional[dict] = ai_client.parse_json_loose(raw or "")
    if parsed is None and raw:
        retry_prompt = prompt + (
            "\n\nYour previous response was not valid JSON. "
            "Output only valid JSON matching the schema above."
        )
        raw2 = await ai_client.generate_text(retry_prompt, temperature=0.0, timeout=120.0)
        parsed = ai_client.parse_json_loose(raw2 or "")

    if not parsed:
        return _system_error_response(
            extracted_claim,
            request_id,
            gen_ms,
            detail="The configured language model is unreachable or returned an unparseable response.",
        )

    try:
        tier_val = int(parsed.get("tier", 3))
        # The model uses 0 (or anything outside 1-5) to signal it can't
        # produce a verdict from the provided evidence. Surface that as
        # no_evidence rather than a fake tier or a system error.
        if tier_val not in (1, 2, 3, 4, 5):
            return _no_evidence_response(extracted_claim, request_id, gen_ms)
        return Verdict(
            extracted_claim=extracted_claim,
            status="ok",
            tier=tier_val,
            summary=str(parsed.get("summary", ""))[:500],
            effect_size=str(parsed.get("effect_size", "")),
            dose=str(parsed.get("dose", "")),
            population=str(parsed.get("population", "")),
            confidence=str(parsed.get("confidence", "low")),  # type: ignore[arg-type]
            why=str(parsed.get("why", "")),
            evidence=_docs_to_evidence(docs),
            request_id=request_id,
            generation_time_ms=gen_ms,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return _system_error_response(
            extracted_claim, request_id, gen_ms, detail=f"Verdict shaping failed: {exc}"
        )
