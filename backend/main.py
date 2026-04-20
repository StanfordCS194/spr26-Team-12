import os
import uuid
import asyncio
from datetime import datetime
from typing import Optional

import certifi
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from models import (
    AnalysisResult, SegmentAnalysis, SpeakerMatch,
    ReportRequest, ReportResponse,
)
from database import (
    init_db, save_analysis, get_analysis, save_report, get_report,
    list_speakers, get_speaker,
)
from report_pdf import generate_pdf
import speaker_match

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


@app.on_event("startup")
def _warm_models():
    # Lazy-load ECAPA so the first /analyze isn't slow. Don't block startup
    # if the model can't be reached -- speaker matching just becomes optional.
    try:
        speaker_match.warmup()
    except Exception as e:
        print(f"[warn] speaker encoder warmup failed: {e}")


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


# ── Mock analysis (stands in for Features 2-4) ───────────────────

MOCK_SEGMENTS = [
    SegmentAnalysis(
        start_time=0.0, end_time=3.0, confidence_score=42.0,
        contributors=["Normal pitch variance", "Natural breath pattern", "Consistent formant transitions"],
    ),
    SegmentAnalysis(
        start_time=3.0, end_time=6.0, confidence_score=78.5,
        contributors=["Unusual pitch stability", "Spectral smoothing at 3.8kHz", "Missing micro-pauses"],
    ),
    SegmentAnalysis(
        start_time=6.0, end_time=9.0, confidence_score=91.2,
        contributors=["Synthetic vowel transitions", "Spectral artifact at 4.2kHz", "Unnatural F0 contour"],
    ),
    SegmentAnalysis(
        start_time=9.0, end_time=12.0, confidence_score=88.7,
        contributors=["TTS boundary artifact", "Flat energy envelope", "Phase discontinuity"],
    ),
    SegmentAnalysis(
        start_time=12.0, end_time=15.0, confidence_score=65.3,
        contributors=["Moderate pitch regularity", "Slight spectral banding", "Natural trailing off"],
    ),
]

MOCK_SUMMARY = (
    "Segments 3.0s\u201312.0s display spectral characteristics strongly associated with "
    "neural text-to-speech synthesis, including unusual pitch stability, spectral smoothing "
    "artifacts, and synthetic vowel transitions. The opening and closing segments show more "
    "natural acoustic properties, suggesting possible splicing of authentic and synthetic "
    "audio. Overall AI-generation probability: 87.3%."
)


# ── Feature 4: Politician Identity Matching ───────────────────────


@app.get("/speakers")
async def speakers():
    """Return the indexed reference politicians for the upload-page dropdown."""
    return list_speakers()


class AnalyzeRequest(BaseModel):
    claimed_speaker_id: Optional[str] = None


@app.post("/analyze/{file_id}")
async def analyze(file_id: str, req: Optional[AnalyzeRequest] = None):
    """Mock detection (Features 2-3) + real speaker matching (Feature 4)."""
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

    # Feature 4: real speaker matching, only if a speaker was claimed.
    sm: Optional[SpeakerMatch] = None
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
            print(f"[warn] speaker_match.compare failed: {e}")

    analysis_id = str(uuid.uuid4())
    result = AnalysisResult(
        analysis_id=analysis_id,
        file_id=file_id,
        filename=found,
        overall_score=87.3,
        verdict="Likely AI-Generated",
        confidence_low=82.1,
        confidence_high=92.5,
        segments=MOCK_SEGMENTS,
        summary=MOCK_SUMMARY,
        model_used="Wav2Vec 2.0 (fine-tuned) + CNN Spectrogram Ensemble",
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
