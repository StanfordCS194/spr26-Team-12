"""
Feature 2 — Per-influencer credibility persistence and scoring.

Every clip report generated for a named creator is appended to that
influencer's history file. The credibility score is recomputed from the
running history, so the score updates automatically as new clips are checked.

Score derivation (per claim):

    supports            +1.0   "true"
    partially_supports  +0.5   "mostly true"
    mixed                0.0   "mixed"
    weak                -0.5   "weakly supported"
    contradicts         -1.0   "false"
    insufficient         exc.  "unverified" (excluded from denominator)

    score = (sum + verified) / (2 * verified) * 100   ∈ [0, 100]

Letter grade:
    A ≥ 85   B ≥ 70   C ≥ 55   D ≥ 40   F < 40   N/A if no verified claims
"""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from .. import config
from ..models import ClaimCheckResult, ClipReportResponse

# JSON file living alongside the other backend data fixtures.
HISTORY_PATH = config.DATA_DIR / "influencer_history.json"

# Direction → (weight, public verdict label)
_VERDICT_WEIGHTS: dict[str, float] = {
    "supports": 1.0,
    "partially_supports": 0.5,
    "mixed": 0.0,
    "weak": -0.5,
    "contradicts": -1.0,
}
_PUBLIC_LABEL: dict[str, str] = {
    "supports": "true",
    "partially_supports": "mostly_true",
    "mixed": "mixed",
    "weak": "weak",
    "contradicts": "false",
    "insufficient": "unverified",
}

_lock = threading.Lock()


# ── slugging / IO ────────────────────────────────────────────────


def slugify(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"^@+", "", s)
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s or "unknown"


def _load() -> dict:
    if not HISTORY_PATH.exists():
        return {}
    try:
        with HISTORY_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    tmp.replace(HISTORY_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── recording ────────────────────────────────────────────────────


def record_report(report: ClipReportResponse) -> Optional[str]:
    """
    Persist each claim from ``report`` into the named creator's history.
    Returns the slug used, or None if there's no creator name to attach to.
    """
    if not report.creator_name or not report.creator_name.strip():
        return None

    slug = slugify(report.creator_name)
    checked_at = _now_iso()
    new_records = [_record_for_claim(report, claim, checked_at) for claim in report.claims]

    with _lock:
        data = _load()
        profile = data.get(slug) or {
            "slug": slug,
            "name": report.creator_name.strip(),
            "first_seen": checked_at,
            "claim_records": [],
        }
        profile["name"] = report.creator_name.strip()
        profile["claim_records"].extend(new_records)
        data[slug] = profile
        _save(data)
    return slug


def _record_for_claim(report: ClipReportResponse, claim: ClaimCheckResult, checked_at: str) -> dict:
    primary_url = claim.sources[0].url if claim.sources else None
    return {
        "report_id": report.report_id,
        "checked_at": checked_at,
        "claim_id": claim.claim.claim_id,
        "claim_text": claim.claim.normalized_claim,
        "category": claim.claim.category,
        "risk_level": claim.claim.risk_level,
        "status": claim.status,
        "final_direction": claim.agreement.final_direction,
        "confidence": claim.agreement.confidence,
        "agreement_level": claim.agreement.agreement_level,
        "summary": claim.agreement.summary,
        "needs_review": claim.agreement.agreement_level
        in {"source_disagreement", "conclusion_disagreement"},
        "source_url": primary_url,
        "source_domain": _domain(primary_url),
    }


def _domain(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    m = re.match(r"https?://([^/]+)/?", url)
    return m.group(1).lower() if m else None


# ── reading + scoring ───────────────────────────────────────────


def _grade(score: Optional[float]) -> str:
    if score is None:
        return "N/A"
    if score >= 85: return "A"
    if score >= 70: return "B"
    if score >= 55: return "C"
    if score >= 40: return "D"
    return "F"


def _bucket_counts(records: Iterable[dict]) -> Counter:
    counter: Counter = Counter()
    for record in records:
        label = _PUBLIC_LABEL.get(record.get("final_direction") or "insufficient", "unverified")
        counter[label] += 1
    for label in ("true", "mostly_true", "mixed", "weak", "false", "unverified"):
        counter.setdefault(label, 0)
    return counter


def _compute_score(records: list[dict]) -> dict:
    weighted_sum = 0.0
    verified = 0
    for record in records:
        weight = _VERDICT_WEIGHTS.get(record.get("final_direction") or "")
        if weight is None:
            continue
        weighted_sum += weight
        verified += 1

    if verified == 0:
        score: Optional[float] = None
    else:
        raw = (weighted_sum + verified) / (2 * verified) * 100
        score = round(max(0.0, min(100.0, raw)), 1)

    buckets = _bucket_counts(records)
    return {
        "score": score,
        "grade": _grade(score),
        "verified_claims": verified,
        "total_claims": len(records),
        "buckets": dict(buckets),
        "needs_review_claims": sum(1 for r in records if r.get("needs_review")),
        "last_checked_at": max(
            (r.get("checked_at") for r in records if r.get("checked_at")), default=None
        ),
    }


def _profile_summary(profile: dict) -> dict:
    score = _compute_score(profile.get("claim_records", []))
    return {
        "slug": profile["slug"],
        "name": profile["name"],
        "first_seen": profile.get("first_seen"),
        "credibility": score,
    }


def list_profiles(min_verified: int = 0) -> list[dict]:
    data = _load()
    out = [_profile_summary(p) for p in data.values()]
    out = [p for p in out if p["credibility"]["verified_claims"] >= min_verified]
    out.sort(
        key=lambda p: (
            p["credibility"]["score"] is not None,
            p["credibility"]["score"] or 0,
            p["credibility"]["verified_claims"],
        ),
        reverse=True,
    )
    return out


def get_profile(slug: str) -> Optional[dict]:
    data = _load()
    profile = data.get(slug)
    if not profile:
        return None
    summary = _profile_summary(profile)
    records = sorted(
        profile.get("claim_records", []),
        key=lambda r: r.get("checked_at") or "",
        reverse=True,
    )
    summary["claim_records"] = records
    summary["category_breakdown"] = _category_counts(records)
    return summary


def _category_counts(records: List[dict]) -> dict:
    counter: Counter = Counter()
    for record in records:
        counter[record.get("category") or "other"] += 1
    return dict(counter)


def delete_profile(slug: str) -> bool:
    with _lock:
        data = _load()
        if slug not in data:
            return False
        del data[slug]
        _save(data)
    return True


# ── seed ────────────────────────────────────────────────────────


def is_empty() -> bool:
    return not _load()


def seed_demo() -> int:
    """Populate a few example influencers without going through the LLM pipeline."""
    if not is_empty():
        return 0

    base_time = datetime.now(timezone.utc)

    def _claim(direction: str, category: str, text: str, *, risk: str = "medium",
               agreement: str = "strong_agreement", confidence: str = "high",
               source_url: str | None = None, summary: str = "") -> dict:
        return {
            "report_id": f"seed_{slugify(text)[:24]}",
            "checked_at": base_time.isoformat(),
            "claim_id": "seed",
            "claim_text": text,
            "category": category,
            "risk_level": risk,
            "status": "ok" if direction != "insufficient" else "no_evidence",
            "final_direction": direction,
            "confidence": confidence,
            "agreement_level": agreement,
            "summary": summary or f"Veritas rates this claim as {direction.replace('_', ' ')}.",
            "needs_review": agreement in {"source_disagreement", "conclusion_disagreement"},
            "source_url": source_url,
            "source_domain": _domain(source_url),
        }

    demo: dict[str, dict] = {
        "Greg Doucette": [
            _claim("supports", "supplement",
                   "Creatine monohydrate is a safe, effective supplement for strength gains.",
                   source_url="https://jissn.biomedcentral.com/articles/10.1186/s12970-021-00412-w"),
            _claim("supports", "nutrition",
                   "Caloric surplus is the primary driver of weight gain, not dietary fat alone."),
            _claim("partially_supports", "muscle_gain",
                   "1g of protein per pound of bodyweight is required for hypertrophy."),
        ],
        "Liver King": [
            _claim("contradicts", "hormones",
                   "My physique was built only on ancestral eating, no anabolic steroids.",
                   risk="high",
                   source_url="https://www.nytimes.com/2022/12/02/style/liver-king-steroids.html"),
            _claim("weak", "supplement",
                   "Raw liver provides bioavailable retinol superior to supplementation.",
                   risk="medium"),
            _claim("contradicts", "hormones",
                   "Cold exposure meaningfully boosts long-term testosterone."),
            _claim("supports", "training",
                   "Walking 10,000 steps a day improves cardiovascular health markers."),
        ],
        "Layne Norton": [
            _claim("supports", "nutrition",
                   "Sugar is not uniquely fattening compared to other carbs at equal calories."),
            _claim("supports", "nutrition",
                   "Seed oils are not driving the obesity epidemic.",
                   source_url="https://www.health.harvard.edu/staying-healthy/no-need-to-avoid-healthy-omega-6-fats"),
            _claim("supports", "training",
                   "Resistance training is among the strongest interventions for healthspan."),
            _claim("contradicts", "nutrition",
                   "Artificial sweeteners cause cancer at normal intakes.",
                   source_url="https://www.fda.gov/food/food-additives-petitions/aspartame-and-other-sweeteners-food"),
        ],
        "Bro Science Life": [
            _claim("contradicts", "muscle_gain",
                   "There is only a 30-minute anabolic window after lifting."),
            _claim("contradicts", "training",
                   "Squatting will stunt your growth.", risk="medium"),
            _claim("contradicts", "weight_loss",
                   "Drinking a gallon of water a day directly burns belly fat."),
            _claim("contradicts", "weight_loss",
                   "You can spot-reduce belly fat with crunches.", risk="medium"),
            _claim("mixed", "training",
                   "Slow-tempo reps build noticeably more muscle than normal-tempo reps."),
        ],
        "Andrew Huberman": [
            _claim("supports", "sleep",
                   "Morning sunlight exposure helps regulate the circadian rhythm.",
                   source_url="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6751071/"),
            _claim("partially_supports", "recovery",
                   "NSDR / yoga nidra can partially offset short-term sleep debt."),
            _claim("weak", "hormones",
                   "Cold plunges produce dopamine spikes that last for hours."),
            _claim("insufficient", "supplement",
                   "Tongkat ali reliably raises testosterone in healthy men."),
        ],
    }

    with _lock:
        data = _load()
        for name, records in demo.items():
            slug = slugify(name)
            data[slug] = {
                "slug": slug,
                "name": name,
                "first_seen": base_time.isoformat(),
                "claim_records": records,
            }
        _save(data)

    return len(demo)
