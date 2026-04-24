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
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from models import (
    AnalysisResult, SegmentAnalysis,
    ReportRequest, ReportResponse,
)
from database import (
    init_db, save_analysis, get_analysis, save_report, get_report,
    list_speakers, get_speaker,
)
from report_pdf import generate_pdf
import speaker_match
from detector import analyze as run_detection

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


async def _warm_models_task():
    # Lazy-load ECAPA so the first /analyze isn't slow. Don't block startup
    # if the model can't be reached -- speaker matching just becomes optional.
    try:
        await asyncio.wait_for(asyncio.to_thread(speaker_match.warmup), timeout=30)
    except asyncio.TimeoutError:
        print("[warn] speaker encoder warmup timed out")
    except Exception as e:
        print(f"[warn] speaker encoder warmup failed: {e}")


@app.on_event("startup")
async def _warm_models():
    asyncio.create_task(_warm_models_task())
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


# ── Feature 4: Politician Identity Matching ───────────────────────


@app.get("/speakers")
async def speakers():
    """Return the indexed reference politicians for the upload-page dropdown."""
    return list_speakers()


class AnalyzeRequest(BaseModel):
    claimed_speaker_id: Optional[str] = None


@app.post("/analyze/{file_id}")
async def analyze(file_id: str, req: Optional[AnalyzeRequest] = None):
    """
    Run the real ML detection pipeline (Features 2.1–2.3) and, if a
    `claimed_speaker_id` is supplied in the body, the Feature-4 speaker-
    identity match against the stored reference centroid.
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

    # Features 2.1–2.3: real ML detection.
    try:
        detection = await asyncio.get_event_loop().run_in_executor(
            None, run_detection, audio_path
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        logger.exception("Detection pipeline failed for %s", found)
        raise HTTPException(500, f"Analysis failed: {exc}")

    # Feature 4: real speaker matching, only if a speaker was claimed.
    sm = None
    claimed_id = req.claimed_speaker_id if req else None
    if claimed_id:
        if get_speaker(claimed_id) is None:
            raise HTTPException(404, f"Unknown speaker: {claimed_id}")
        try:
            sm = speaker_match.compare(audio_path, claimed_id)
        except ValueError as e:
            # e.g. clip too short for reliable matching (R12)
            raise HTTPException(400, str(e))
        except Exception as e:
            # Don't fail the whole analysis if speaker matching breaks.
            logger.warning("speaker_match.compare failed: %s", e)

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
        speaker_match=sm,
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
