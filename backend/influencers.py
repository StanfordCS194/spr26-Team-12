"""
Feature 2 — Credibility score endpoints.

These read from the rolling history maintained by ``credibility_store``.
``main.py`` calls ``record_clip_report`` after every clip-report so the
score updates automatically; this module only exposes the read/admin API.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .pipeline import credibility_store

router = APIRouter(prefix="/api/influencers", tags=["credibility"])


class ScoreSummary(BaseModel):
    score: Optional[float]
    grade: str
    verified_claims: int
    total_claims: int
    needs_review_claims: int
    last_checked_at: Optional[str]
    buckets: dict


class InfluencerSummary(BaseModel):
    slug: str
    name: str
    first_seen: Optional[str]
    credibility: ScoreSummary


class ClaimRecord(BaseModel):
    report_id: str
    checked_at: str
    claim_id: str
    claim_text: str
    category: str
    risk_level: str
    status: str
    final_direction: str
    confidence: str
    agreement_level: str
    summary: str
    needs_review: bool
    source_url: Optional[str] = None
    source_domain: Optional[str] = None


class InfluencerDetail(InfluencerSummary):
    claim_records: list[ClaimRecord]
    category_breakdown: dict


@router.get("", response_model=list[InfluencerSummary])
def list_influencers(
    min_verified: int = Query(0, ge=0,
        description="Hide profiles with fewer than N verified claims"),
):
    return credibility_store.list_profiles(min_verified=min_verified)


@router.get("/{slug}", response_model=InfluencerDetail)
def influencer_detail(slug: str):
    profile = credibility_store.get_profile(slug)
    if not profile:
        raise HTTPException(404, "Influencer not found")
    return profile


@router.delete("/{slug}", status_code=204)
def delete_influencer(slug: str):
    if not credibility_store.delete_profile(slug):
        raise HTTPException(404, "Influencer not found")


@router.post("/seed")
def seed_demo():
    created = credibility_store.seed_demo()
    if created == 0:
        return {"status": "already_seeded"}
    return {"status": "seeded", "created": created}
