import logging
import os
import uuid
import asyncio
from datetime import datetime
from typing import Optional

# Load backend/.env before any module reads os.environ
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import certifi
import httpx
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from models import (
    AnalysisResult, SegmentAnalysis,
    ReportRequest, ReportResponse,
)
from database import init_db, save_analysis, get_analysis, save_report, get_report
from report_pdf import generate_pdf
from detector import analyze as run_detection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

YTDLP = os.path.join(os.path.dirname(__file__), "venv/bin/yt-dlp")
SSL_ENV = {**os.environ, "SSL_CERT_FILE": certifi.where()}

# ── Resemble AI Detect (optional — most accurate, requires public HTTPS URL) ──
RESEMBLE_API_KEY = os.environ.get("RESEMBLE_API_KEY", "").strip()
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
_RESEMBLE_BASE = "https://app.resemble.ai/api/v2"


async def _resemble_detect(file_id: str) -> tuple[Optional[float], list[float]]:
    """
    Submit audio to the Resemble AI Detect API and wait for results.

    Uses frame_length=3 so Resemble's per-chunk scores align with our
    3-second preprocessing windows — enabling Resemble to power the heatmap.

    Returns (overall_0_100, per_chunk_scores_0_100).
    Returns (None, []) when:
      • RESEMBLE_API_KEY is not set, or
      • BACKEND_URL is not a public HTTPS URL (audio must be reachable by Resemble)
    """
    if not RESEMBLE_API_KEY or not BACKEND_URL.startswith("https://"):
        if RESEMBLE_API_KEY and not BACKEND_URL.startswith("https://"):
            logger.info(
                "Resemble AI skipped — BACKEND_URL is not HTTPS (%s). "
                "Deploy and set BACKEND_URL=https://your-domain.com to enable.",
                BACKEND_URL,
            )
        return None, []

    audio_url = f"{BACKEND_URL}/preview/{file_id}"
    headers = {
        "Authorization": f"Bearer {RESEMBLE_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            # Submit detection job; frame_length=3 matches our 3-second segments
            resp = await client.post(
                f"{_RESEMBLE_BASE}/detect",
                json={"url": audio_url, "frame_length": 3},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success"):
                logger.warning("Resemble API: success=false — %s", data)
                return None, []

            item = data["item"]
            detect_uuid = item["uuid"]

            # Poll until completed (max 15 × 3 s = 45 s)
            for _ in range(15):
                status = item.get("status")
                if status == "completed":
                    break
                if status == "failed":
                    logger.warning(
                        "Resemble job failed: %s", item.get("error_message")
                    )
                    return None, []
                await asyncio.sleep(3)
                poll = await client.get(
                    f"{_RESEMBLE_BASE}/detect/{detect_uuid}", headers=headers
                )
                poll.raise_for_status()
                item = poll.json().get("item", item)

            metrics = item.get("metrics") or {}
            agg_str = str(metrics.get("aggregated_score", "")).strip()
            if not agg_str:
                logger.warning("Resemble: no aggregated_score in response")
                return None, []

            # aggregated_score is 0–1 float as a string
            agg = float(agg_str)
            overall = agg * 100 if agg <= 1.0 else agg

            # Per-chunk scores — each string is also 0–1
            chunk_scores: list[float] = []
            for s in metrics.get("score", []):
                try:
                    v = float(s)
                    chunk_scores.append(v * 100 if v <= 1.0 else v)
                except (ValueError, TypeError):
                    pass

            logger.info(
                "Resemble AI: overall=%.1f%%, %d chunk scores",
                overall, len(chunk_scores),
            )
            return float(overall), chunk_scores

    except Exception as exc:
        logger.warning("Resemble AI error: %s", exc)
        return None, []

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
        YTDLP, "-x", "--audio-format", "mp3", "-o", out_path, req.url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=SSL_ENV,
    )
    await asyncio.wait_for(proc.communicate(), timeout=120)
    if proc.returncode != 0:
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


@app.post("/analyze/{file_id}")
async def analyze(file_id: str):
    """
    Run the real ML detection pipeline (Features 2.1–2.3):
      · Preprocessing — normalise, trim silence, segment into 3 s windows
      · Ensemble model — Wav2Vec2 deepfake classifier (primary) +
                         acoustic feature analyser + CNN spectrogram analyser
      · Output — per-segment scores, overall probability, verdict, CI
    """
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

    # Call Resemble AI before the local pipeline (requires public HTTPS backend)
    resemble_overall, resemble_chunks = await _resemble_detect(file_id)

    try:
        detection = await asyncio.get_event_loop().run_in_executor(
            None, run_detection, audio_path, resemble_overall, resemble_chunks
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        logger.exception("Detection pipeline failed for %s", found)
        raise HTTPException(500, f"Analysis failed: {exc}")

    analysis_id = str(uuid.uuid4())
    result = AnalysisResult(
        analysis_id=analysis_id,
        file_id=file_id,
        filename=found,
        overall_score=detection.overall_score,
        verdict=detection.verdict,
        confidence_low=detection.confidence_low,
        confidence_high=detection.confidence_high,
        segments=[
            SegmentAnalysis(
                start_time=s.start_time,
                end_time=s.end_time,
                confidence_score=s.confidence_score,
                contributors=s.contributors,
            )
            for s in detection.segments
        ],
        summary=detection.summary,
        model_used=detection.model_used,
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
