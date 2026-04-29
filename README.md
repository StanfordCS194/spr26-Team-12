# Veritas — Your fitness bro fact checker

Veritas is pivoting into a platform for fact-checking fitness influencers,
brands, and broscience claims. The first MVP path is:

> upload audio/video clip → transcribe → extract claims → fact-check claims →
> show sources and agreement

See [PRODUCT_PIVOT_SPEC.md](PRODUCT_PIVOT_SPEC.md) for the full product plan:
audio transcription, internal source cross-checking, influencer credibility
scores, and brand credibility scores.

## Current Status

This repo currently contains the earlier supplement-claim checker plus the
first cleanup for the new pivot.

What works now:

- React/Vite UI with text, audio, link, and screenshot input tabs
- FastAPI backend
- Demo cache for showcase supplement verdicts
- Audio upload endpoint wired for cloud transcription
- Provider-neutral text generation client
- Four verdict statuses: `ok`, `out_of_scope`, `no_evidence`, `system_error`

What is next:

- Replace single-claim flow with transcript → multiple claims
- Add internal source cross-checking
- Add agreement-gated verdict judging
- Add influencer and brand profile scoring

## Prerequisites

- Python 3.9+
- Node 18+
- API credits/keys for the live MVP:
  - Audio transcription provider key
  - Text reasoning provider key
  - Optional search key: `TAVILY_API_KEY` or `BRAVE_SEARCH_API_KEY`

Ollama is no longer required.

## Environment

Copy the example env file and fill in keys as needed:

```bash
cp .env.example .env
```

`.env` is git-ignored. Do not commit real API keys.

For quick shell testing, export directly:

```bash
export GROQ_API_KEY="..."
export OPENAI_API_KEY="..."
export DEMO_MODE=false
```

Important vars:

| Var | Purpose |
|---|---|
| `DEMO_MODE` | `true` uses cached showcase responses; `false` uses configured providers |
| `PRIMARY_LLM_PROVIDER` | Default text model provider, currently `openai` |
| `SECONDARY_LLM_PROVIDER` | Second verifier provider, currently `groq` |
| `GROQ_API_KEY` | Required for audio transcription |
| `OPENAI_API_KEY` | Required for OpenAI extraction/verdict generation |
| `SEARCH_PROVIDER` | Planned source search provider (`tavily`, `brave`, etc.) |
| `MAX_AUDIO_MB` | Upload limit for audio/video files |

## Run Locally

Backend:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

The Vite dev server proxies `/api/*` to `http://localhost:8000`.

## Audio MVP Flow

1. Add `GROQ_API_KEY` to your environment.
2. Start backend and frontend.
3. Open the **Audio** tab.
4. Upload an audio/video clip.
5. Veritas transcribes the file and receives a transcript.
6. The transcript enters the existing extraction/verdict path.

For now, the UI still returns a single extracted claim. The next implementation
step is changing this to transcript → multiple claims → agreement-gated checks.

## Demo Claims

Without API keys, demo mode still works for a few showcase claims:

- `bro creatine causes hair loss`
- `ashwagandha boosts testosterone 40%`
- `do BCAAs build muscle if I eat enough protein`
- `beta-alanine helps high reps?`
- `does caffeine improve strength`
- `tongkat ali 200% testosterone boost real?`

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health, demo flag, and provider configuration status |
| `POST` | `/api/process/text` | Normalize raw pasted text |
| `POST` | `/api/process/audio` | Transcribe audio/video through the configured provider |
| `POST` | `/api/process/url` | Process a URL into text placeholder |
| `POST` | `/api/process/screenshot` | Process screenshot placeholder |
| `POST` | `/api/claims/extract` | Extract multiple editable claims from transcript |
| `POST` | `/api/clip-report` | Search sources and return one Veritas rating when the evidence is clear enough |
| `POST` | `/api/extract` | Legacy: extract one claim from text |
| `POST` | `/api/verdict` | Legacy: produce a verdict for one extracted claim |

## Repo Layout

```text
backend/
  main.py                 FastAPI routes
  config.py               credit-provider config and upload limits
  models.py               API schemas
  preprocessors.py        text/url/screenshot preprocessing
  pipeline/
    ai_client.py          provider-neutral text generation helper
    transcriber.py        audio transcription helper
    source_search.py      Tavily web search or PubMed fallback
    clip_checker.py       multi-claim extraction, verifiers, agreement judge
    extractor.py          current single-claim extraction
    verdict.py            current single-claim verdict path
    retriever.py          seed-corpus keyword retrieval
    demo_cache.py         showcase verdict cache
frontend/
  src/App.jsx             UI input flow, now including Audio tab
  src/VerdictCard.jsx     status-aware verdict renderer
  src/styles.css          light/dark theme system
PRODUCT_PIVOT_SPEC.md     full pivot spec and roadmap
.env.example              provider-key setup template
```

## Cleanup Done From Pivot

- Removed local Ollama dependency and client code
- Replaced local-model config with cloud provider config
- Added audio transcription endpoint
- Added multi-claim extraction and clip-report endpoints
- Added source search with Tavily support and PubMed fallback
- Added internal cross-checking + agreement judge pipeline
- Added frontend audio upload tab
- Added frontend claim review/edit and clip report UI
- Added `.env.example`
- Updated README to match the credit-based MVP direction

## Next Build Decision

Before adding influencer/brand scoring, build Feature 1 properly:

1. Transcript/audio input
2. Multi-claim extraction
3. User claim review/edit step
4. Internal evidence cross-checking
5. Agreement judge
6. Single user-facing Veritas rating
7. Clip-level report

That proves the core product before we attach scores to people and brands.
