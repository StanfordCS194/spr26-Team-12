"""Verified-product recommendations.

Dietary supplements are not "FDA approved" the way prescription drugs are.
The strongest regulated bar a supplement can meet is third-party
certification (NSF Certified for Sport, USP Verified, Informed Sport /
Informed Choice) produced in FDA-registered cGMP facilities. This module
maps a Veritas claim to a curated catalog of products that meet that bar.
"""
from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from typing import Iterable, List

from .. import config
from ..models import ExtractedClaimItem, ProductRecommendation
from . import image_resolver

# Each entry maps a supplement key (matching products.json) to the words /
# phrases that should trigger its recommendations when seen in the claim.
SUPPLEMENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "creatine": ("creatine",),
    "whey_protein": ("whey", "whey protein", "protein powder", "protein shake"),
    "beta_alanine": ("beta-alanine", "beta alanine", "carnosine"),
    "caffeine": ("caffeine", "pre-workout", "preworkout", "pre workout"),
    "fish_oil": ("fish oil", "omega-3", "omega 3", "epa", "dha"),
    "vitamin_d": ("vitamin d", "vitamin d3", "cholecalciferol"),
    "magnesium": ("magnesium",),
    "ashwagandha": ("ashwagandha", "withania"),
    "citrulline": ("citrulline", "l-citrulline"),
    "bcaa": ("bcaa", "bcaas", "branched-chain amino", "branched chain amino"),
    "tongkat_ali": ("tongkat", "eurycoma", "longjack", "longifolia"),
}


@lru_cache(maxsize=1)
def _load_catalog() -> dict:
    path = config.DATA_DIR / "products.json"
    if not path.exists():
        return {"supplements": {}}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _matched_supplements(text: str) -> List[str]:
    lowered = text.lower()
    matched: List[str] = []
    for key, keywords in SUPPLEMENT_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            matched.append(key)
    return matched


def _build_recommendations(keys: Iterable[str], *, limit: int = 3) -> List[ProductRecommendation]:
    catalog = _load_catalog().get("supplements", {})
    products: List[ProductRecommendation] = []
    seen_ids: set[str] = set()
    for key in keys:
        for item in catalog.get(key, []):
            product_id = str(item.get("id") or "")
            if not product_id or product_id in seen_ids:
                continue
            seen_ids.add(product_id)
            product_url = str(item.get("url", ""))
            placeholder_image = str(item.get("image_url", ""))
            resolved_image = image_resolver.resolve_image(
                product_url, fallback=placeholder_image
            )
            products.append(
                ProductRecommendation(
                    id=product_id,
                    supplement=key,
                    brand=str(item.get("brand", "")),
                    product_name=str(item.get("product_name", "")),
                    certification=str(item.get("certification", "")),
                    form=str(item.get("form", "")),
                    price_band=str(item.get("price_band", "")),
                    note=str(item.get("note", "")),
                    url=product_url,
                    image_url=resolved_image,
                )
            )
    return products[:limit]


async def recommend_for_claim(claim: ExtractedClaimItem, *, limit: int = 3) -> List[ProductRecommendation]:
    """Return verified products related to the supplement(s) in this claim."""
    text = f"{claim.raw_claim} {claim.normalized_claim}"
    keys = _matched_supplements(text)
    if not keys:
        return []
    return await asyncio.to_thread(_build_recommendations, keys, limit=limit)
