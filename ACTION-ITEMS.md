# Action Items for Team

Feature 5 (Shareable Report Export) has been built end-to-end and is working with mock analysis data. Here's what each person needs to know to build off of this.

---

## What's Already Done

- **Feature 1** (Audio Upload & Ingestion) — fully working
- **Feature 5** (Shareable Report Export) — fully working with mock data
  - PDF generation (placeholder layout, awaiting Figma branding)
  - Shareable links with 30-day expiry
  - Read-only shared report web view
  - SQLite database for analyses and reports
  - Frontend results page with verdict, heatmap, segment table, export/share buttons

The mock analysis endpoint (`POST /analyze/{file_id}`) returns realistic fake data so you can test the full flow right now.

---

## For the ML/Detection Team (Feature 2)

Your job is to replace the mock analysis in `backend/main.py` with the real ML pipeline.

### What to do

1. Open `backend/main.py` and find the `analyze()` function (line ~140)
2. Replace the mock data with your real preprocessing + model inference
3. Return an `AnalysisResult` object — this is the contract defined in `backend/models.py`

### The data contract you need to fill

```python
# backend/models.py — AnalysisResult

analysis_id: str          # generate with uuid4
file_id: str              # passed in from the upload
filename: str             # the audio filename
overall_score: float      # 0-100, probability of AI generation
verdict: str              # "Likely Authentic" or "Likely AI-Generated"
confidence_low: float     # lower bound of confidence interval
confidence_high: float    # upper bound of confidence interval
segments: list[SegmentAnalysis]  # per-3s-window scores + top contributors
summary: str              # plain English paragraph (Feature 3.2)
model_used: str           # e.g. "Wav2Vec 2.0 (fine-tuned) + CNN Ensemble"
speaker_match: Optional[SpeakerMatch]  # from Feature 4, or None
analyzed_at: str          # ISO-8601 timestamp
```

Each `SegmentAnalysis` needs:
```python
start_time: float         # e.g. 0.0
end_time: float           # e.g. 3.0
confidence_score: float   # 0-100
contributors: list[str]   # top 3 reasons for the score
```

### Important
- Do NOT change the `AnalysisResult` shape without updating the report generator and frontend
- The `save_analysis()` call at the end of `analyze()` must stay — it stores results for the report system
- If you add new fields to the model, add them as `Optional` so existing code doesn't break

---

## For the Heatmap/Explainability Team (Feature 3)

### Frontend heatmap
The frontend heatmap visualization is already built in `frontend/src/ResultsPage.jsx`. It reads from the `segments` array in the analysis result. As long as Feature 2 returns proper `SegmentAnalysis` objects, the heatmap will render automatically with green-to-red coloring.

### Plain English summary
The `summary` field in `AnalysisResult` is displayed on the results page and included in the PDF report. Your job is to generate this string in the analysis pipeline. Make it citable — journalists will copy-paste it into articles.

### PDF heatmap
The PDF currently shows a gray placeholder box where the heatmap image should go. Once you have a way to render the heatmap as an image (e.g. matplotlib), update `backend/report_pdf.py` in the `generate_pdf()` function — look for the "heatmap placeholder" section. Replace the placeholder `rect()` with `pdf.image(heatmap_path, ...)`.

---

## For the Speaker Identity Team (Feature 4)

### What to do
1. Build the reference voice index (ECAPA-TDNN embeddings for ~200 politicians)
2. Add speaker verification logic
3. Fill in the `SpeakerMatch` object in the analysis pipeline:

```python
# backend/models.py — SpeakerMatch

claimed_speaker: str      # e.g. "Sen. Jane Smith"
similarity_score: float   # 0-100, cosine similarity
interpretation: str       # e.g. "Low similarity — voice does not match reference model"
```

### Where it shows up
- The results page renders the speaker match section automatically if `speaker_match` is not None
- The PDF report includes it in a "Speaker Identity Match" section
- The shared report view shows it read-only

Set `speaker_match=None` in the `AnalysisResult` if the user didn't select a speaker — the UI handles this gracefully.

---

## For the Branding/Design Team

### PDF report
The PDF generator is in `backend/report_pdf.py`. The `VeritasReport` class has `header()` and `footer()` methods — swap in the Figma-designed logo and brand colors there. Current brand color in the PDF table headers is `rgb(139, 26, 26)` matching the frontend.

To add a logo: use `pdf.image("path/to/logo.png", x, y, w)` in the `header()` method.

### Frontend
All styles are in `frontend/src/App.css`. Brand color is `#8b1a1a` throughout.

---

## File Map

```
backend/
  main.py           ← API endpoints (mock analysis lives here)
  models.py          ← Data contracts (AnalysisResult, SegmentAnalysis, etc.)
  database.py        ← SQLite layer (analyses + reports tables)
  report_pdf.py      ← PDF generation (placeholder layout)
  veritas.db         ← Auto-created on first run (gitignored)

frontend/src/
  App.jsx            ← Router (/, /results/:id, /shared/:id)
  App.css            ← All styles
  UploadPage.jsx     ← File upload + URL input + preview
  ResultsPage.jsx    ← Analysis results + heatmap + export/share
  SharedReportPage.jsx ← Read-only shared report view
```

---

## How to Test the Full Flow

1. Start backend: `cd backend && venv/bin/uvicorn main:app --reload`
2. Start frontend: `cd frontend && npm run dev`
3. Open http://localhost:5173
4. Upload any audio file (MP3, WAV, etc.)
5. Play the audio, then click "Submit for Analysis"
6. See mock results → click "Export Report" → download PDF or copy share link
7. Open the share link in an incognito window to see the read-only view

---

Questions? Ping Agam.
