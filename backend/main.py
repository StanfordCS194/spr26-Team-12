import logging
import os
import uuid
import asyncio
from datetime import datetime

# Load backend/.env before any module reads os.environ
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import certifi
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from models import (
    AnalysisResult, FactCheck, FactClaim,
    ReportRequest, ReportResponse,
)
from database import init_db, save_analysis, get_analysis, save_report, get_report
from report_pdf import generate_pdf
from fact_checker import transcribe, fact_check

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

YTDLP = os.path.join(os.path.dirname(__file__), "venv/bin/yt-dlp")
SSL_ENV = {**os.environ, "SSL_CERT_FILE": certifi.where()}

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "/tmp/veritas"
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_TYPES = {
    "audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg",
    "audio/x-m4a", "audio/m4a", "video/mp4",
}
MAX_SIZE = 100 * 1024 * 1024  # 100 MB

init_db()


# ── Feature 1: Audio Upload & Ingestion ──────────────────────────


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(400, "File exceeds 100 MB limit")

    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1] or ".mp3"
    path = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")
    with open(path, "wb") as f:
        f.write(data)

    return {"file_id": file_id, "filename": file.filename}


class URLRequest(BaseModel):
    url: str


@app.post("/ingest-url")
async def ingest_url(req: URLRequest):
    if not req.url.startswith("https://"):
        raise HTTPException(400, "URL must use HTTPS")

    file_id = str(uuid.uuid4())
    out_path = os.path.join(UPLOAD_DIR, f"{file_id}.mp3")

    proc = await asyncio.create_subprocess_exec(
        YTDLP, "-x", "--audio-format", "mp3",
        "--extractor-args", "youtube:player_client=android",
        "-o", out_path, req.url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=SSL_ENV,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    if proc.returncode != 0:
        logger.error("yt-dlp failed: %s", stderr.decode(errors="replace"))
        raise HTTPException(400, "Could not extract audio from URL")

    return {"file_id": file_id, "filename": req.url.split("/")[-1]}


@app.get("/preview/{file_id}")
async def preview(file_id: str):
    try:
        uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(400, "Invalid file ID")

    for fname in os.listdir(UPLOAD_DIR):
        if fname.startswith(file_id):
            return FileResponse(os.path.join(UPLOAD_DIR, fname))

    raise HTTPException(404, "File not found")


# ── Feature 2: AI/Human Detection Engine ─────────────────────────


class AnalyzeRequest(BaseModel):
    speaker: str | None = None
    date: str | None = None


@app.post("/analyze/{file_id}")
async def analyze(file_id: str, req: AnalyzeRequest = AnalyzeRequest()):
    try:
        uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(400, "Invalid file ID")

    found = None
    for fname in os.listdir(UPLOAD_DIR):
        if fname.startswith(file_id):
            found = fname
            break
    if not found:
        raise HTTPException(404, "File not found")

    audio_path = os.path.join(UPLOAD_DIR, found)

    claimed_speaker = req.speaker or None
    claimed_date = req.date or None
    try:
        transcript = await asyncio.get_event_loop().run_in_executor(
            None, transcribe, audio_path
        )
        fc_raw = await asyncio.get_event_loop().run_in_executor(
            None, fact_check, transcript, claimed_speaker, claimed_date
        ) if transcript else None
    except Exception as exc:
        logger.exception("Fact-check pipeline failed for %s", found)
        raise HTTPException(500, f"Analysis failed: {exc}")

    fact_check_result = None
    if fc_raw:
        try:
            fact_check_result = FactCheck(
                transcript=fc_raw.get("transcript", transcript or ""),
                claimed_speaker=fc_raw.get("claimed_speaker"),
                claims=[FactClaim(**c) for c in fc_raw.get("claims", [])],
                consistency_score=float(fc_raw.get("consistency_score", 50)),
                summary=fc_raw.get("summary", ""),
            )
        except Exception as exc:
            logger.warning("FactCheck model validation failed: %s", exc)

    if not fact_check_result:
        raise HTTPException(500, "Could not transcribe or fact-check audio")

    analysis_id = str(uuid.uuid4())
    result = AnalysisResult(
        analysis_id=analysis_id,
        file_id=file_id,
        filename=found,
        overall_score=fact_check_result.consistency_score,
        verdict="Consistent with Public Record" if fact_check_result.consistency_score >= 60 else "Inconsistent with Public Record",
        confidence_low=max(0, fact_check_result.consistency_score - 10),
        confidence_high=min(100, fact_check_result.consistency_score + 10),
        segments=[],
        summary=fact_check_result.summary,
        model_used="Whisper (transcription) + Gemini 2.0 Flash (fact-check)",
        fact_check=fact_check_result,
        analyzed_at=datetime.utcnow().isoformat() + "Z",
    )

    save_analysis(analysis_id, file_id, found, result.model_dump())
    return result


@app.get("/analysis/{analysis_id}")
async def get_analysis_result(analysis_id: str):
    row = get_analysis(analysis_id)
    if not row:
        raise HTTPException(404, "Analysis not found")
    return row["result"]


# ── Feature 5: Shareable Report Export ────────────────────────────


@app.post("/reports", response_model=ReportResponse)
async def create_report(req: ReportRequest):
    row = get_analysis(req.analysis_id)
    if not row:
        raise HTTPException(404, "Analysis not found")

    analysis = AnalysisResult(**row["result"])
    report_id = str(uuid.uuid4())
    pdf_path = generate_pdf(report_id, analysis)

    save_report(report_id, req.analysis_id, analysis.file_id, analysis.filename, pdf_path)
    report = get_report(report_id)

    return ReportResponse(
        report_id=report_id,
        share_url=f"/shared/{report_id}",
        pdf_url=f"/reports/{report_id}/pdf",
        created_at=report["created_at"],
        expires_at=report["expires_at"],
    )


@app.get("/reports/{report_id}/pdf")
async def download_report_pdf(report_id: str):
    report = get_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found or expired")
    if not os.path.exists(report["pdf_path"]):
        raise HTTPException(404, "PDF file missing")
    return FileResponse(
        report["pdf_path"],
        media_type="application/pdf",
        filename=f"veritas-report-{report_id[:8]}.pdf",
    )


@app.get("/shared/{report_id}")
async def shared_report(report_id: str):
    """Returns report metadata + full analysis for the shared view."""
    report = get_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found or link has expired")
    analysis_row = get_analysis(report["analysis_id"])
    if not analysis_row:
        raise HTTPException(404, "Analysis data missing")
    return {
        "report": {
            "report_id": report["report_id"],
            "created_at": report["created_at"],
            "expires_at": report["expires_at"],
        },
        "analysis": analysis_row["result"],
    }
