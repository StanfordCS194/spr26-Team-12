# Veritas — AI Voice Authentication Platform

AI-powered voice authentication platform that detects whether an audio clip of a public figure was generated or altered by AI. Designed for journalists, fact-checkers, campaign staff, and the informed public.

## Features

### Feature 1: Audio Upload & Ingestion (P0) — Implemented
The main entry point for all users. Accepts audio through multiple input methods with no barriers to use.

- **1.1 File Upload** — Drag-and-drop or select audio files (MP3, MP4, WAV, OGG, M4A). Max 100 MB. File type validated before upload with visual progress.
- **1.2 URL Input** — Paste a YouTube, Twitter/X, or direct media HTTPS link. Backend extracts audio via yt-dlp. Shows error if audio cannot be extracted.
- **1.3 Audio Preview** — Listen to audio before submission. Submit button disabled until the user has played the audio to confirm they have the right clip.

### Feature 2: AI/Human Detection Engine (P0) — Implemented

Core ML system that evaluates audio and returns a probability score for AI generation.

- **2.1 Preprocessing** — RMS-normalise, mono 16 kHz resample, trim silence, segment into 3-second non-overlapping windows. MFCC (13 coefficients + deltas), Spectral Flux, pitch (F0/pyin), ZCR, and RMS energy extracted per segment. (`backend/preprocessor.py`)
- **2.2 Model** — Three-component ensemble in `backend/detector.py`:
  - **Primary (60 %)**: `dima806/deepfake-vs-real-audio-detection` — Wav2Vec 2.0 base fine-tuned for deepfake audio classification (auto-downloads via HuggingFace on first run, ~400 MB). Falls back gracefully to acoustic-only if unavailable.
  - **Acoustic ensemble (25 % / 60 % fallback)**: Six speech-science features with research-calibrated thresholds — pitch stability (F0 CV), spectral-flux regularity, MFCC-delta flatness, RMS energy CV, spectral-centroid stability, ZCR uniformity.
  - **CNN spectrogram analyser (15 % / 40 % fallback)**: Mel-spectrogram band-energy ratio, frame temporal correlation, harmonic-to-percussive ratio, spectral-contrast stability.
- **2.3 Output** — Overall AI probability (0–100%), per-segment scores with top-3 explainability contributors, binary verdict ("Likely Authentic" vs "Likely AI-Generated"), 95 % Wald confidence interval, plain-English citable summary.

### Feature 3: Confidence Heatmap & Explainability (P1) — Not Started
Translates per-segment scores into a visual timeline so users can see where anomalies were detected.

- **3.1 Visual Heatmap** — Timeline bar colored green (authentic) to red (AI-generated). Hover to see exact probability and top 3 score contributors per segment.
- **3.2 Plain English Summary** — Auto-generated one-paragraph summary of findings with citable language for news articles.

### Feature 4: Politician Identity Matching (P1) — Not Started
Compares uploaded audio against a reference voice model for the claimed speaker.

- **4.1 Reference Voice Index** — ~200 political leaders indexed from C-SPAN / government archives using ECAPA-TDNN speaker verification.
- **4.2 Speaker Similarity Score** — Cosine similarity against the reference voice, presented alongside the AI detection score. Low similarity + high AI probability = likely synthetic impersonation.

### Feature 5: Shareable Report Export (P1) — Implemented
Generate and share organized reports for editorial or legal documentation.

- **5.1 PDF Report** — Auto-generated PDF with report ID, audio metadata, verdict, heatmap (placeholder), plain English summary, model info, and segment analysis table. Branding TBD (Figma).
- **5.2 Shareable Link** — Each report gets a unique URL to a read-only web view. Links expire after 30 days. Can be embedded in articles or shared with editors.

### Feature 6: REST API Access (P2) — Not Started
API endpoint for Trust & Safety teams to submit audio programmatically for moderation pipelines.

### Feature 7: Batch Upload (P2) — Not Started
Process multiple clips at once for Trust & Safety analysts.

### Feature 8: Browser Extension (P3) — Not Started
Right-click any audio on a webpage to check it.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, Vite, React Router |
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Detection — Primary | Wav2Vec 2.0 (`dima806/deepfake-vs-real-audio-detection`) |
| Detection — Secondary | Acoustic features + CNN spectrogram analysis (librosa) |
| Database | SQLite (analyses + reports) |
| PDF Generation | fpdf2 |
| Audio Extraction | yt-dlp, ffmpeg |

## Requirements
- Python 3.10+
- Node 18+
- ffmpeg (`brew install ffmpeg`)
- ~2 GB disk for HuggingFace model cache (downloaded on first analysis)

## Setup

### Backend
```bash
cd backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/uvicorn main:app --reload
```

The Wav2Vec2 deepfake detection model (~400 MB) downloads automatically from HuggingFace on the first `/analyze` call. Subsequent runs use the local cache. Analysis without the model (acoustic-only fallback) works immediately.

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## API Endpoints

| Method | Path | Feature | Description |
|--------|------|---------|-------------|
| `POST` | `/upload` | 1 | Upload an audio file |
| `POST` | `/ingest-url` | 1 | Extract audio from HTTPS URL |
| `GET` | `/preview/{file_id}` | 1 | Stream uploaded audio for preview |
| `POST` | `/analyze/{file_id}` | 2 | Run real ML analysis (preprocessing → ensemble → verdict) |
| `GET` | `/analysis/{analysis_id}` | 2 | Fetch analysis results |
| `POST` | `/reports` | 5 | Generate PDF report + shareable link |
| `GET` | `/reports/{report_id}/pdf` | 5 | Download report PDF |
| `GET` | `/shared/{report_id}` | 5 | Fetch data for shared report view |

## Source Control
git: Agam Iheanyi-Igwe (agam01)

Henok Tewolde
Kamal Eissa
