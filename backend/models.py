"""
Data contracts for the Veritas analysis pipeline.

AnalysisResult is the interface between the ML pipeline (Features 2-4)
and the report system (Feature 5).  When the real detection engine is
ready, have it return an AnalysisResult and everything downstream works.
"""

from pydantic import BaseModel
from typing import Optional


class SegmentAnalysis(BaseModel):
    start_time: float
    end_time: float
    confidence_score: float  # 0-100, likelihood of AI generation
    contributors: list[str]  # top features that drove the score


class SpeakerMatch(BaseModel):
    claimed_speaker: str
    similarity_score: float  # 0-100, cosine similarity to reference voice
    interpretation: str


class FactClaim(BaseModel):
    claim: str
    verdict: str        # "Verified" | "False" | "Unverifiable" | "Misleading"
    explanation: str
    sources: list[str]


class FactCheck(BaseModel):
    transcript: str
    claimed_speaker: Optional[str] = None
    claims: list[FactClaim]
    consistency_score: float  # 0-100, how consistent with public record
    summary: str


class AnalysisResult(BaseModel):
    analysis_id: str
    file_id: str
    filename: str
    overall_score: float  # 0-100
    verdict: str  # "Likely Authentic" | "Likely AI-Generated"
    confidence_low: float
    confidence_high: float
    segments: list[SegmentAnalysis]
    summary: str
    model_used: str
    speaker_match: Optional[SpeakerMatch] = None
    fact_check: Optional[FactCheck] = None
    analyzed_at: str  # ISO-8601


class ReportRequest(BaseModel):
    analysis_id: str


class ReportResponse(BaseModel):
    report_id: str
    share_url: str
    pdf_url: str
    created_at: str
    expires_at: str
