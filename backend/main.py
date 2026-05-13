"""FastAPI entrypoint. Run with: uvicorn backend.main:app --reload"""
from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import config, preprocessors
from .influencers import router as influencers_router
from .models import (
    ClipReportRequest,
    ClipReportResponse,
    ExtractRequest,
    ExtractClaimsRequest,
    ExtractClaimsResponse,
    ExtractResponse,
    ProcessResponse,
    ProviderStatus,
    QuickScanRequest,
    QuickScanResponse,
    Verdict,
    VerdictRequest,
)
from .pipeline import clip_checker, extractor, quick_scan, transcriber, verdict as verdict_pipeline
from .pipeline import credibility

app = FastAPI(title="Veritas", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(influencers_router)


@app.get("/api/health")
def health() -> dict:
    transcription_configured = bool(config.OPENAI_API_KEY or config.GROQ_API_KEY)
    return {
        "ok": True,
        "demo_mode": config.DEMO_MODE,
        "providers": ProviderStatus(
            primary_llm_provider=config.PRIMARY_LLM_PROVIDER,
            secondary_llm_provider=config.SECONDARY_LLM_PROVIDER,
            transcription_provider=config.TRANSCRIPTION_PROVIDER,
            search_provider=config.SEARCH_PROVIDER,
            openai_configured=bool(config.OPENAI_API_KEY),
            search_configured=bool(config.TAVILY_API_KEY or config.BRAVE_SEARCH_API_KEY),
            transcription_configured=transcription_configured,
            groq_configured=bool(config.GROQ_API_KEY),
        ).model_dump(),
    }


# --- Pre-processor endpoints (used by the frontend before /extract) ---
@app.post("/api/process/text", response_model=ProcessResponse)
def process_text_endpoint(payload: dict) -> ProcessResponse:
    try:
        text = preprocessors.process_text(payload.get("text", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ProcessResponse(text=text, source="text")


@app.post("/api/process/url", response_model=ProcessResponse)
async def process_url_endpoint(payload: dict) -> ProcessResponse:
    try:
        text, platform = await preprocessors.process_url(payload.get("url", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ProcessResponse(text=text, source="link", note=f"platform={platform}")


@app.post("/api/process/screenshot", response_model=ProcessResponse)
async def process_screenshot_endpoint(image: UploadFile = File(...)) -> ProcessResponse:
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    text = preprocessors.process_screenshot(data)
    return ProcessResponse(text=text, source="screenshot")


@app.post("/api/process/audio", response_model=ProcessResponse)
async def process_audio_endpoint(audio: UploadFile = File(...)) -> ProcessResponse:
    data = await audio.read()
    try:
        transcript = await transcriber.transcribe_audio(
            audio.filename or "audio",
            audio.content_type or "application/octet-stream",
            data,
        )
    except transcriber.TranscriptionUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ProcessResponse(text=transcript, source="audio", note="transcribed")


# --- Core endpoints ---
@app.post("/api/extract", response_model=ExtractResponse)
async def extract(req: ExtractRequest) -> ExtractResponse:
    if not req.raw_text.strip():
        raise HTTPException(status_code=400, detail="raw_text required")
    t0 = time.perf_counter()
    claim = await extractor.extract_claim(req.raw_text)
    return ExtractResponse(
        extracted_claim=claim,
        request_id=uuid.uuid4().hex,
        extraction_time_ms=int((time.perf_counter() - t0) * 1000),
    )


@app.post("/api/claims/extract", response_model=ExtractClaimsResponse)
async def extract_claims(req: ExtractClaimsRequest) -> ExtractClaimsResponse:
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="transcript required")
    t0 = time.perf_counter()
    claims = await clip_checker.extract_claims(req.transcript)
    return ExtractClaimsResponse(
        transcript=req.transcript,
        claims=claims,
        request_id=uuid.uuid4().hex,
        extraction_time_ms=int((time.perf_counter() - t0) * 1000),
    )


@app.post("/api/claims/quick-scan", response_model=QuickScanResponse)
async def quick_scan_endpoint(req: QuickScanRequest) -> QuickScanResponse:
    """Lightweight claim detection for the live Chrome extension overlay.
    Returns flagged claims with risk levels but skips full dual-verifier pipeline."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text required")
    t0 = time.perf_counter()
    result = await quick_scan.scan(req.text, url=req.url, platform=req.platform, content_type=req.content_type)
    result.scan_time_ms = int((time.perf_counter() - t0) * 1000)
    return result


@app.post("/api/verdict", response_model=Verdict)
async def verdict(req: VerdictRequest) -> Verdict:
    if not req.extracted_claim.strip():
        raise HTTPException(status_code=400, detail="extracted_claim required")
    t0 = time.perf_counter()
    result = await verdict_pipeline.generate_verdict(
        req.extracted_claim,
        req.request_id,
        gen_ms=0,
    )
    # patch in real elapsed time
    result.generation_time_ms = int((time.perf_counter() - t0) * 1000)
    return result


@app.post("/api/clip-report", response_model=ClipReportResponse)
async def clip_report(req: ClipReportRequest) -> ClipReportResponse:
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="transcript required")
    selected = [claim for claim in req.claims if claim.selected]
    if not selected:
        raise HTTPException(status_code=400, detail="select at least one claim")
    report = await clip_checker.build_report(
        req.transcript,
        req.claims,
        source=req.source,
        creator_name=req.creator_name,
        brand_name=req.brand_name,
    )
    # Feed the credibility ledger (Features 2 & 3) — no-op if no creator name.
    try:
        credibility.record_clip(
            creator_name=req.creator_name,
            transcript=req.transcript,
            claim_results=report.claims,
            source_clip=req.brand_name or None,
        )
    except Exception:
        pass
    return report


# --- Feature 2: Influencer credibility -------------------------------------
@app.get("/api/influencers")
def list_influencers_endpoint() -> dict:
    return {"influencers": credibility.list_influencers()}


@app.get("/api/influencers/{slug}")
def get_influencer_endpoint(slug: str) -> dict:
    inf = credibility.get_influencer(slug)
    if not inf:
        raise HTTPException(status_code=404, detail="influencer not found")
    return inf


# --- Feature 3: Product credibility ----------------------------------------
@app.get("/api/products")
def list_products_endpoint() -> dict:
    return {"products": credibility.list_products()}


@app.get("/api/products/{product_id}")
def get_product_endpoint(product_id: str) -> dict:
    prod = credibility.get_product(product_id)
    if not prod:
        raise HTTPException(status_code=404, detail="product not found")
    return prod
