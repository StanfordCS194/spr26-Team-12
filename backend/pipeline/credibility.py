"""Credibility aggregation for Features 2 (influencers) and 3 (products).

Single source of truth = a JSON ledger appended to whenever a clip report
is generated (or seeded from `influencers.json#seed_ledger` on first load).

Each ledger entry:
  {
    "ts": int,
    "influencer_slug": str | null,
    "claim": str,
    "direction": EvidenceDirection,
    "confidence": Confidence,
    "supplements": [supplement_key, ...],   # keys from products.json
    "source_clip": str | null,
  }

Scoring is deliberately simple and explainable:
  baseline = influencer.baseline_score (or 70 if unknown)
  for each ledger entry: score += DIRECTION_WEIGHT[direction] * CONF_WEIGHT[conf]
  clamp to [0, 100], round to int.

Product score blends evidence (per-supplement aggregation), formulation
(certification tier from products.json), and endorsement quality (avg
score of influencers who promoted it).
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import config

_DATA_DIR = Path(config.BASE_DIR) / "data"
_INFLUENCERS_PATH = _DATA_DIR / "influencers.json"
_PRODUCTS_PATH = _DATA_DIR / "products.json"
_LEDGER_PATH = _DATA_DIR / "credibility_ledger.json"
# Hidden set is intentionally a separate file so the canonical
# influencers.json (tracked in git, used to seed demos) stays immutable
# at runtime. DELETE is a soft-hide; reseed clears this set.
_HIDDEN_PATH = _DATA_DIR / "hidden_influencers.json"

_lock = threading.Lock()

DIRECTION_WEIGHT = {
    "supports": +6,
    "partially_supports": +2,
    "mixed": 0,
    "weak": -2,
    "contradicts": -8,
    "insufficient": 0,
}
CONF_WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.4}

# Tier weight for third-party certifications (Feature 3 quality dimension).
CERT_TIER = {
    "NSF Certified for Sport": 1.0,
    "Informed Sport": 1.0,
    "Informed Choice": 0.9,
    "USP Verified": 0.95,
    "IFOS 5-star": 0.95,
    "USP Verified ingredients": 0.85,
    "NSF GMP-registered facility": 0.8,
    "TGA-tested manufacturing": 0.75,
    "cGMP, third-party tested": 0.7,
}

# Map supplement keys → human-friendly display name.
SUPPLEMENT_DISPLAY = {
    "creatine": "Creatine",
    "whey_protein": "Whey Protein",
    "beta_alanine": "Beta-Alanine",
    "caffeine": "Caffeine",
    "fish_oil": "Fish Oil (Omega-3)",
    "vitamin_d": "Vitamin D",
    "magnesium": "Magnesium",
    "ashwagandha": "Ashwagandha",
    "citrulline": "L-Citrulline",
    "bcaa": "BCAA",
    "tongkat_ali": "Tongkat Ali",
}


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_ledger(entries: List[dict]) -> None:
    _LEDGER_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _ensure_ledger() -> List[dict]:
    """Return ledger entries, seeding from influencers.json on first run."""
    existing = _load_json(_LEDGER_PATH)
    if isinstance(existing, list):
        return existing
    seed_src = _load_json(_INFLUENCERS_PATH) or {}
    seed = list(seed_src.get("seed_ledger") or [])
    _save_ledger(seed)
    return seed


def _influencer_index() -> Dict[str, dict]:
    data = _load_json(_INFLUENCERS_PATH) or {}
    return {inf["slug"]: inf for inf in data.get("influencers", [])}


def _all_products() -> Dict[str, List[dict]]:
    data = _load_json(_PRODUCTS_PATH) or {}
    return data.get("supplements", {}) or {}


# --- ledger writes -----------------------------------------------------------


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")


def _detect_supplements(text: str) -> List[str]:
    """Map free-text claim/transcript to known supplement keys."""
    if not text:
        return []
    t = text.lower()
    hits: List[str] = []
    keywords = {
        "creatine": ["creatine"],
        "whey_protein": ["whey", "protein powder", "whey protein"],
        "beta_alanine": ["beta-alanine", "beta alanine"],
        "caffeine": ["caffeine", "pre-workout", "preworkout", "pre workout"],
        "fish_oil": ["fish oil", "omega-3", "omega 3", "epa", "dha"],
        "vitamin_d": ["vitamin d", "vitamin-d", "vit d"],
        "magnesium": ["magnesium"],
        "ashwagandha": ["ashwagandha", "ashwaganda", "ksm-66", "ksm 66"],
        "citrulline": ["citrulline"],
        "bcaa": ["bcaa", "branched chain amino"],
        "tongkat_ali": ["tongkat", "eurycoma"],
    }
    for key, words in keywords.items():
        if any(w in t for w in words):
            hits.append(key)
    return hits


def record_clip(
    creator_name: Optional[str],
    transcript: str,
    claim_results: List[Any],
    source_clip: Optional[str] = None,
) -> None:
    """Append one ledger entry per claim_result to the persistent ledger.

    `claim_results` is a list of `ClaimCheckResult`-shaped objects.
    Silently no-ops if creator_name is missing — Features 2/3 only need
    attributed claims.
    """
    if not creator_name:
        return
    slug = _slugify(creator_name)
    now = int(time.time())
    new_entries: List[dict] = []
    for cr in claim_results:
        try:
            agreement = getattr(cr, "agreement", None)
            claim = getattr(cr, "claim", None)
            direction = getattr(agreement, "final_direction", "insufficient")
            confidence = getattr(agreement, "confidence", "low")
            text = getattr(claim, "normalized_claim", None) or getattr(claim, "raw_claim", "")
        except Exception:
            continue
        sups = _detect_supplements(f"{text} {transcript}")
        new_entries.append(
            {
                "ts": now,
                "influencer_slug": slug,
                "claim": text,
                "direction": direction,
                "confidence": confidence,
                "supplements": sups,
                "source_clip": source_clip,
            }
        )
    if not new_entries:
        return
    with _lock:
        ledger = _ensure_ledger()
        ledger.extend(new_entries)
        # auto-register unknown influencers so Feature 2 picks them up
        idx = _influencer_index()
        if slug not in idx:
            data = _load_json(_INFLUENCERS_PATH) or {"influencers": []}
            data["influencers"].append(
                {
                    "slug": slug,
                    "name": creator_name,
                    "handle": "",
                    "platforms": [],
                    "followers": "",
                    "topics": [],
                    "avatar_color": "#475569",
                    "bio": "Auto-added from a Veritas fact-check.",
                    "baseline_score": 70,
                }
            )
            _INFLUENCERS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _save_ledger(ledger)


# --- read-side aggregation --------------------------------------------------


def _score_from_entries(baseline: int, entries: List[dict]) -> int:
    score = float(baseline)
    for e in entries:
        score += DIRECTION_WEIGHT.get(e.get("direction", "insufficient"), 0) * CONF_WEIGHT.get(
            e.get("confidence", "low"), 0.4
        )
    return max(0, min(100, round(score)))


def _direction_breakdown(entries: List[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for e in entries:
        d = e.get("direction", "insufficient")
        out[d] = out.get(d, 0) + 1
    return out


def _load_hidden() -> set:
    data = _load_json(_HIDDEN_PATH)
    if isinstance(data, list):
        return set(data)
    return set()


def _save_hidden(slugs: set) -> None:
    _HIDDEN_PATH.write_text(json.dumps(sorted(slugs), indent=2), encoding="utf-8")


def list_influencers(min_verified: int = 0) -> List[dict]:
    """Return all influencers with current aggregated scores.

    Args:
        min_verified: only return influencers whose `claims_checked`
            (ledger entries attributed to them) is >= this value. Filtering
            happens server-side so the threshold semantics live in one place
            and the wire payload shrinks for clients that only care about
            "verified" creators.
    """
    idx = _influencer_index()
    hidden = _load_hidden()
    ledger = _ensure_ledger()
    grouped: Dict[str, List[dict]] = {}
    for e in ledger:
        s = e.get("influencer_slug")
        if s:
            grouped.setdefault(s, []).append(e)
    out: List[dict] = []
    for slug, inf in idx.items():
        if slug in hidden:
            continue
        entries = grouped.get(slug, [])
        if min_verified > 0 and len(entries) < min_verified:
            continue
        score = _score_from_entries(inf.get("baseline_score", 70), entries)
        out.append(
            {
                "slug": slug,
                "name": inf.get("name"),
                "handle": inf.get("handle", ""),
                "platforms": inf.get("platforms", []),
                "followers": inf.get("followers", ""),
                "topics": inf.get("topics", []),
                "avatar_color": inf.get("avatar_color", "#475569"),
                "bio": inf.get("bio", ""),
                "credibility_score": score,
                "claims_checked": len(entries),
            }
        )
    out.sort(key=lambda x: -x["credibility_score"])
    return out


def hide_influencer(slug: str) -> bool:
    """Soft-delete an influencer from listings. Returns True if the slug
    is known (and is now hidden), False if the slug does not exist.

    Soft-hide rather than hard-delete because influencers.json is the
    canonical demo dataset committed to the repo; mutating it at runtime
    would dirty the working tree and break reproducible demos. Reseeding
    clears the hidden set, making this fully reversible.
    """
    if slug not in _influencer_index():
        return False
    with _lock:
        hidden = _load_hidden()
        hidden.add(slug)
        _save_hidden(hidden)
    return True


def reseed_ledger() -> int:
    """Reset the credibility ledger to the canonical seed in
    influencers.json#seed_ledger and clear any soft-hidden slugs.

    Returns the number of ledger entries after reseeding. Intended for
    demos / TA review so the leaderboard returns to a known state on
    demand without manual file edits.
    """
    seed_src = _load_json(_INFLUENCERS_PATH) or {}
    seed = list(seed_src.get("seed_ledger") or [])
    with _lock:
        _save_ledger(seed)
        _save_hidden(set())
    return len(seed)


def get_influencer(slug: str) -> Optional[dict]:
    idx = _influencer_index()
    inf = idx.get(slug)
    if not inf:
        return None
    ledger = _ensure_ledger()
    entries = [e for e in ledger if e.get("influencer_slug") == slug]
    score = _score_from_entries(inf.get("baseline_score", 70), entries)
    breakdown = _direction_breakdown(entries)
    promoted_keys = sorted({k for e in entries for k in e.get("supplements", [])})
    products_index = _all_products()
    promoted_products: List[dict] = []
    for k in promoted_keys:
        for prod in products_index.get(k, []):
            promoted_products.append(
                {
                    "supplement": SUPPLEMENT_DISPLAY.get(k, k),
                    "supplement_key": k,
                    "id": prod.get("id"),
                    "brand": prod.get("brand"),
                    "product_name": prod.get("product_name"),
                    "url": prod.get("url", ""),
                    "image_url": prod.get("image_url", ""),
                }
            )
    # most recent claims first
    claims = sorted(entries, key=lambda e: -int(e.get("ts", 0)))
    return {
        "slug": slug,
        "name": inf.get("name"),
        "handle": inf.get("handle", ""),
        "platforms": inf.get("platforms", []),
        "followers": inf.get("followers", ""),
        "topics": inf.get("topics", []),
        "avatar_color": inf.get("avatar_color", "#475569"),
        "bio": inf.get("bio", ""),
        "credibility_score": score,
        "claims_checked": len(entries),
        "direction_breakdown": breakdown,
        "recent_claims": claims[:25],
        "promoted_products": promoted_products,
    }


def _supplement_evidence(key: str, ledger: List[dict]) -> Dict[str, Any]:
    matches = [e for e in ledger if key in (e.get("supplements") or [])]
    breakdown = _direction_breakdown(matches)
    # Evidence sub-score: like influencer scoring but without a baseline.
    # Map [-50, +50] -> [0, 100] symmetrically around 50.
    raw = sum(
        DIRECTION_WEIGHT.get(e.get("direction", "insufficient"), 0)
        * CONF_WEIGHT.get(e.get("confidence", "low"), 0.4)
        for e in matches
    )
    evidence_score = max(0, min(100, round(50 + raw)))
    return {"matches": matches, "breakdown": breakdown, "evidence_score": evidence_score}


def list_products() -> List[dict]:
    products_index = _all_products()
    ledger = _ensure_ledger()
    influencers_idx = _influencer_index()
    influencer_scores = {i["slug"]: i for i in list_influencers()}
    out: List[dict] = []
    for sup_key, plist in products_index.items():
        ev = _supplement_evidence(sup_key, ledger)
        promoter_slugs = sorted({e["influencer_slug"] for e in ev["matches"] if e.get("influencer_slug")})
        if promoter_slugs:
            promoter_avg = round(
                sum(influencer_scores.get(s, {}).get("credibility_score", 70) for s in promoter_slugs)
                / len(promoter_slugs)
            )
        else:
            promoter_avg = 70
        for prod in plist:
            cert_tier = CERT_TIER.get(prod.get("certification", ""), 0.6)
            quality_score = round(60 + cert_tier * 40)  # 60..100
            # Final = 0.5 evidence + 0.3 quality + 0.2 endorsement
            final = round(0.5 * ev["evidence_score"] + 0.3 * quality_score + 0.2 * promoter_avg)
            out.append(
                {
                    "id": prod.get("id"),
                    "brand": prod.get("brand"),
                    "product_name": prod.get("product_name"),
                    "supplement_key": sup_key,
                    "supplement": SUPPLEMENT_DISPLAY.get(sup_key, sup_key),
                    "certification": prod.get("certification", ""),
                    "form": prod.get("form", ""),
                    "price_band": prod.get("price_band", ""),
                    "note": prod.get("note", ""),
                    "url": prod.get("url", ""),
                    "image_url": prod.get("image_url", ""),
                    "credibility_score": max(0, min(100, final)),
                    "evidence_score": ev["evidence_score"],
                    "quality_score": quality_score,
                    "endorsement_score": promoter_avg,
                    "claims_count": len(ev["matches"]),
                }
            )
    out.sort(key=lambda x: -x["credibility_score"])
    return out


def get_product(product_id: str) -> Optional[dict]:
    products_index = _all_products()
    ledger = _ensure_ledger()
    target_prod = None
    target_key = None
    for sup_key, plist in products_index.items():
        for prod in plist:
            if prod.get("id") == product_id:
                target_prod = prod
                target_key = sup_key
                break
        if target_prod:
            break
    if not target_prod or not target_key:
        return None
    ev = _supplement_evidence(target_key, ledger)
    influencers_idx = _influencer_index()
    influencer_scores = {i["slug"]: i for i in list_influencers()}
    promoter_slugs = sorted({e["influencer_slug"] for e in ev["matches"] if e.get("influencer_slug")})
    promoter_cards: List[dict] = []
    for s in promoter_slugs:
        info = influencers_idx.get(s) or {}
        score_card = influencer_scores.get(s, {})
        their_calls = [e for e in ev["matches"] if e.get("influencer_slug") == s]
        promoter_cards.append(
            {
                "slug": s,
                "name": info.get("name", s),
                "handle": info.get("handle", ""),
                "credibility_score": score_card.get("credibility_score", 70),
                "avatar_color": info.get("avatar_color", "#475569"),
                "calls": their_calls,
            }
        )
    promoter_cards.sort(key=lambda x: -x["credibility_score"])
    promoter_avg = (
        round(sum(p["credibility_score"] for p in promoter_cards) / len(promoter_cards))
        if promoter_cards
        else 70
    )
    cert_tier = CERT_TIER.get(target_prod.get("certification", ""), 0.6)
    quality_score = round(60 + cert_tier * 40)
    final = round(0.5 * ev["evidence_score"] + 0.3 * quality_score + 0.2 * promoter_avg)
    return {
        "id": target_prod.get("id"),
        "brand": target_prod.get("brand"),
        "product_name": target_prod.get("product_name"),
        "supplement_key": target_key,
        "supplement": SUPPLEMENT_DISPLAY.get(target_key, target_key),
        "certification": target_prod.get("certification", ""),
        "form": target_prod.get("form", ""),
        "price_band": target_prod.get("price_band", ""),
        "note": target_prod.get("note", ""),
        "url": target_prod.get("url", ""),
        "image_url": target_prod.get("image_url", ""),
        "credibility_score": max(0, min(100, final)),
        "evidence_score": ev["evidence_score"],
        "quality_score": quality_score,
        "endorsement_score": promoter_avg,
        "evidence_breakdown": ev["breakdown"],
        "evidence_claims": sorted(ev["matches"], key=lambda e: -int(e.get("ts", 0)))[:20],
        "promoted_by": promoter_cards,
    }
