# Veritas — AI Voice Authentication Platform

AI-powered deepfake audio detector for political speech. Designed for journalists, fact-checkers, campaign staff, and the informed public.

---

## How to Run

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.10+ | [python.org](https://www.python.org) |
| Node | 18+ | [nodejs.org](https://nodejs.org) |
| ffmpeg | any | `brew install ffmpeg` (macOS) |

### 1. Clone and configure

```bash
git clone https://github.com/StanfordCS194/spr26-Team-12.git
cd spr26-Team-12
cp backend/.env.example backend/.env
# Edit backend/.env — Supabase and Resemble AI keys are optional (see Configuration below)
```

### 2. Start the backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

The backend starts at **http://localhost:8000**. On first run it will download the Wav2Vec2 model (~400 MB) — this is one-time only.

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

---

## Configuration (`backend/.env`)

Copy `backend/.env.example` to `backend/.env` and fill in as needed. All values are optional — the app runs without them using local SQLite and the acoustic/CNN ensemble only.

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Optional | Cloud-persists analyses + reports. Falls back to local SQLite. |
| `SUPABASE_KEY` | Optional | Service-role key from your Supabase project settings. |
| `RESEMBLE_API_KEY` | Optional | **Significantly improves accuracy.** Get free key at [app.resemble.ai/account/api](https://app.resemble.ai/account/api). |
| `BACKEND_URL` | Optional | Public HTTPS URL of the deployed backend (e.g. `https://your-domain.com`). Resemble requires this to fetch audio. Skipped automatically for `http://`. |

**Note:** Resemble AI requires the backend to be publicly accessible via HTTPS so it can fetch the audio. During local development, Resemble is automatically skipped and the local Wav2Vec2 + acoustic ensemble runs instead.

---

## Detection Architecture

Four-tier ensemble — highest accuracy to fastest fallback:

| Tier | Model | Weight | When Active |
|------|-------|--------|-------------|
| 1 | **Resemble AI Detect** (cloud API) | 55% overall + per-segment | `RESEMBLE_API_KEY` + public HTTPS backend |
| 2 | **Wav2Vec2** (`dima806/deepfake-vs-real-audio-detection`) | 60% of segments (no Resemble) | Local, lazy-loads on first `/analyze` |
| 3 | **Acoustic Features** (MFCC delta, pitch jitter, spectral flux, RMS, ZCR) | Always | Local, instant |
| 4 | **CNN Spectrogram** (band energy, temporal correlation, harmonic cleanness) | Always | Local, instant |

All tiers run per 3-second segment so the confidence heatmap always has data. The Resemble `frame_length=3` parameter aligns its chunks exactly to our preprocessing windows.

---

## Features

### Feature 1: Audio Upload & Ingestion — ✅ Done

- **1.1 File Upload** — Drag-and-drop or click to select (MP3, MP4, WAV, OGG, M4A, max 100 MB). Real XHR upload with byte-level progress bar. File type validated before upload.
- **1.2 URL Input** — Paste a YouTube, Twitter/X, or HTTPS media link. Backend extracts audio via `yt-dlp`. Shows error if extraction fails.
- **1.3 Audio Preview** — Listen before submitting. Submit button stays disabled until audio has been played.

### Feature 2: AI/Human Detection Engine — ✅ Done

- **2.1 Preprocessing** — Normalize to 16 kHz mono, RMS normalize, trim silence, segment into 3-second non-overlapping windows (up to 100 segments / ~5 min).
- **2.2 Model** — Four-tier ensemble: Resemble AI (cloud) + Wav2Vec2 (transformer) + Acoustic analyser (classic speech features) + CNN spectrogram analyser.
- **2.3 Output** — Overall probability (0–100%), per-segment scores, binary verdict, 95% Wald confidence interval, plain-English M:SS-timestamped summary.

### Feature 3: Confidence Heatmap & Explainability — ✅ Done

- **3.1 Visual Heatmap** — Interactive timeline bar, green→yellow→red. Hover each segment to see exact probability and top-3 contributors (e.g. "Unusual pitch stability", "Resemble AI deepfake detection score"). Legend below bar.
- **3.2 Plain English Summary** — Auto-generated paragraph with M:SS timestamps, citable for news articles. Example: *"Segment(s) 0:12–0:28 displayed the highest AI probability (87%), exhibiting: unusual pitch stability; Resemble AI deepfake detection score."*

### Feature 4: Politician Identity Matching — 🚧 Not Started

- **4.1 Reference Voice Index** — ~200 political leaders from C-SPAN/archives using ECAPA-TDNN speaker verification.
- **4.2 Speaker Similarity Score** — Cosine similarity against reference voice, shown alongside AI detection score. Low similarity + high AI probability = likely synthetic impersonation.

### Feature 5: Shareable Report Export — ✅ Done

- **5.1 PDF Report** — Auto-generated PDF with report ID, file metadata, verdict, heatmap (placeholder), plain-English summary, model info, segment analysis table.
- **5.2 Shareable Link** — Each report gets a unique URL (`/shared/{report_id}`). Links expire after 30 days.

### Feature 6: REST API Access — 🚧 Not Started (P2)
### Feature 7: Batch Upload — 🚧 Not Started (P2)
### Feature 8: Browser Extension — 🚧 Not Started (P3)

---

## API Endpoints

| Method | Path | Feature | Description |
|--------|------|---------|-------------|
| `POST` | `/upload` | 1.1 | Upload audio file (max 100 MB) |
| `POST` | `/ingest-url` | 1.2 | Extract audio from HTTPS URL via yt-dlp |
| `GET`  | `/preview/{file_id}` | 1.3 | Stream uploaded audio for browser preview |
| `POST` | `/analyze/{file_id}` | 2 | Run full ML detection pipeline |
| `GET`  | `/analysis/{analysis_id}` | 2 | Fetch analysis results |
| `POST` | `/reports` | 5.1 | Generate PDF report + shareable link |
| `GET`  | `/reports/{report_id}/pdf` | 5.1 | Download PDF report |
| `GET`  | `/shared/{report_id}` | 5.2 | Fetch read-only shared report view |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, Vite, React Router 7 |
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Database | Supabase Postgres (primary) + SQLite (fallback) |
| Detection API | Resemble AI Detect (optional, highest accuracy) |
| ML Models | Wav2Vec2 (HuggingFace), PyTorch, Transformers, Accelerate |
| Audio Features | Librosa, SciPy, NumPy |
| Audio Extraction | yt-dlp, ffmpeg |
| PDF Generation | fpdf2 |
| HTTP Client | httpx (async, for Resemble API) |

---

## Source Control
git: Agam Iheanyi-Igwe (agam01)
