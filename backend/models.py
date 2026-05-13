"""Pydantic schemas for the API contracts (see DESIGN.md §3, §4)."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

SourceMode = Literal["text", "link", "screenshot", "audio"]
StudyType = Literal[
    "meta_analysis",
    "rct",
    "observational",
    "review",
    "fact_sheet",
    "position_stand",
    "animal",
    "in_vitro",
]
Tier = Literal[1, 2, 3, 4, 5]
Confidence = Literal["low", "medium", "high"]
VerdictStatus = Literal["ok", "out_of_scope", "no_evidence", "system_error"]
ScopeReason = Literal["off_topic", "prescription", "medical_diagnosis"]
ClaimCategory = Literal[
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
]
RiskLevel = Literal["low", "medium", "high"]
EvidenceDirection = Literal[
    "supports",
    "partially_supports",
    "mixed",
    "weak",
    "contradicts",
    "insufficient",
]
AgreementLevel = Literal[
    "strong_agreement",
    "partial_agreement",
    "source_disagreement",
    "conclusion_disagreement",
    "insufficient_sources",
]


class ExtractRequest(BaseModel):
    raw_text: str = Field(..., max_length=2000)
    source: SourceMode = "text"


class ExtractResponse(BaseModel):
    extracted_claim: str
    request_id: str
    extraction_time_ms: int


class VerdictRequest(BaseModel):
    extracted_claim: str
    request_id: str


class ExtractClaimsRequest(BaseModel):
    transcript: str = Field(..., max_length=12000)
    source: SourceMode = "text"


class ExtractedClaimItem(BaseModel):
    claim_id: str
    raw_claim: str
    normalized_claim: str
    category: ClaimCategory = "other"
    risk_level: RiskLevel = "low"
    selected: bool = True


class ExtractClaimsResponse(BaseModel):
    transcript: str
    claims: List[ExtractedClaimItem]
    request_id: str
    extraction_time_ms: int


class SourceCandidate(BaseModel):
    title: str
    url: str
    snippet: str = ""
    summary: str = ""
    source_type: str = "web"
    year: Optional[int] = None
    provider: str = "unknown"
    quality_score: float = 0.5
    # Curated corpus tags the direction of evidence (positive/negative/null/mixed)
    # which downstream demo heuristics use when no LLM is available. Optional so
    # web/PubMed sources without this metadata remain valid.
    effect_direction: Optional[str] = None


class AgentVerdict(BaseModel):
    provider: str
    conclusion: EvidenceDirection = "insufficient"
    confidence: Confidence = "low"
    summary: str = ""
    source_urls: List[str] = []
    reasoning: str = ""


class AgreementResult(BaseModel):
    agreement_level: AgreementLevel
    final_direction: EvidenceDirection = "insufficient"
    confidence: Confidence = "low"
    summary: str = ""
    why: str = ""


class ProductRecommendation(BaseModel):
    id: str
    supplement: str
    brand: str
    product_name: str
    certification: str = ""
    form: str = ""
    price_band: str = ""
    note: str = ""
    url: str = ""
    image_url: str = ""


class ClaimCheckResult(BaseModel):
    claim: ExtractedClaimItem
    status: VerdictStatus = "ok"
    sources: List[SourceCandidate] = []
    agreement: AgreementResult
    recommendations: List[ProductRecommendation] = []


class ClipReportRequest(BaseModel):
    transcript: str = Field(..., max_length=12000)
    claims: List[ExtractedClaimItem]
    source: SourceMode = "text"
    creator_name: Optional[str] = None
    brand_name: Optional[str] = None


class ClipReportResponse(BaseModel):
    report_id: str
    transcript: str
    source: SourceMode
    creator_name: Optional[str] = None
    brand_name: Optional[str] = None
    claims: List[ClaimCheckResult]
    overall_summary: str
    clip_credibility_score: int
    needs_human_review: bool
    generation_time_ms: int


class EvidenceItem(BaseModel):
    source_title: str
    source_url: str
    study_type: StudyType
    year: int
    sample_size: Optional[int] = None
    population: Optional[str] = None
    relevance_note: str


class Verdict(BaseModel):
    extracted_claim: str
    status: VerdictStatus = "ok"
    # Tier / context fields are only meaningful when status == "ok".
    tier: Optional[Tier] = None
    summary: str = ""
    effect_size: str = ""
    dose: str = ""
    population: str = ""
    confidence: Confidence = "low"
    why: str = ""
    evidence: List[EvidenceItem] = []
    # Populated for non-ok statuses to help the UI guide the user.
    suggested_supplements: List[str] = []
    scope_reason: Optional[ScopeReason] = None
    error_detail: Optional[str] = None
    request_id: str
    generation_time_ms: int


# --- Pre-processor responses (used by /process endpoints) ---
class ProcessResponse(BaseModel):
    text: str
    source: SourceMode
    note: Optional[str] = None


class ProviderStatus(BaseModel):
    primary_llm_provider: str
    secondary_llm_provider: str
    transcription_provider: str
    search_provider: str
    openai_configured: bool
    groq_configured: bool
    search_configured: bool
