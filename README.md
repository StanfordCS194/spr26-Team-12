# Veritas — AI Voice Authentication Platform

AI-powered voice authentication platform that detects whether an audio clip of a public figure was generated or altered by AI. Designed for journalists, fact-checkers, campaign staff, and the informed public.

## Features

### Feature 1: Audio Upload & Ingestion (P0) — Implemented
The main entry point for all users. Accepts audio through multiple input methods with no barriers to use.

- **1.1 File Upload** — Drag-and-drop or select audio files (MP3, MP4, WAV, OGG, M4A). Max 100 MB. File type validated before upload with visual progress.
- **1.2 URL Input** — Paste a YouTube, Twitter/X, or direct media HTTPS link. Backend extracts audio via yt-dlp. Shows error if audio cannot be extracted.
- **1.3 Audio Preview** — Listen to audio before submission. Submit button disabled until the user has played the audio to confirm they have the right clip.

### Feature 2: AI/Human Detection Engine (P0) — Not Started
Core ML system that evaluates audio and returns a probability score for AI generation.

- **2.1 Preprocessing** — Normalize audio, remove silence, segment into 3-second non-overlapping windows. Generate spectrograms with MFCC and Spectral Flux features.
- **2.2 Model** — Fine-tuned transformer classifier (Wav2Vec 2.0 or Whisper encoder) trained on labeled political speeches, ensembled with a secondary CNN spectrogram classifier.
- **2.3 Output** — Overall probability score (0–100%), per-segment scores, binary verdict ("Likely Authentic" vs "Likely AI-Generated"), and confidence interval.

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
| Backend | Python 3.12+, FastAPI, Uvicorn |
| Database | SQLite (analyses + reports) |
| PDF Generation | fpdf2 |
| Audio Extraction | yt-dlp, ffmpeg |

## Requirements
- Python 3.12+
- Node 18+
- ffmpeg (`brew install ffmpeg`)

## Setup

### Backend
```bash
cd backend
python3 -m venv venv
venv/bin/pip install fastapi uvicorn python-multipart yt-dlp certifi fpdf2
venv/bin/uvicorn main:app --reload
```

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
| `POST` | `/analyze/{file_id}` | 2* | Run analysis (currently returns mock data) |
| `GET` | `/analysis/{analysis_id}` | 2* | Fetch analysis results |
| `POST` | `/reports` | 5 | Generate PDF report + shareable link |
| `GET` | `/reports/{report_id}/pdf` | 5 | Download report PDF |
| `GET` | `/shared/{report_id}` | 5 | Fetch data for shared report view |

\* Mock implementation — replace with real ML pipeline.

## Source Control
git: Agam Iheanyi-Igwe (agam01)
