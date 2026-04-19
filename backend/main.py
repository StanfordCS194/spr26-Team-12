import os
import uuid
import asyncio
import certifi
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

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
    # Sanitize: only allow UUIDs
    try:
        uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(400, "Invalid file ID")

    for fname in os.listdir(UPLOAD_DIR):
        if fname.startswith(file_id):
            return FileResponse(os.path.join(UPLOAD_DIR, fname))

    raise HTTPException(404, "File not found")
