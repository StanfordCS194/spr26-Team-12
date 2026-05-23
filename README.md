# Veritas — Your fitness bro fact checker

Veritas is pivoting into a platform for fact-checking fitness influencers,
brands, and broscience claims. The first MVP path is:

> upload audio/video clip → transcribe → extract claims → fact-check claims →
> show sources and agreement

See [PRODUCT_PIVOT_SPEC.md](PRODUCT_PIVOT_SPEC.md) for the full product plan:
audio transcription, internal source cross-checking, influencer credibility
scores, and brand credibility scores.

## Current Status

Veritas is a deployed MVP for the CS194 team project.

What works now:

- React/Vite UI: fact-check flow (text, audio, link, screenshot) plus **Influencers** and **Products** credibility views
- FastAPI backend with multi-claim extraction, dual-agent clip reports, and credibility scoring
- Chrome extension (popup + side panel) for quick scans and handoff to the web app
- Production deploy: frontend on Vercel, backend on Render (see [DEPLOY.md](DEPLOY.md))
- Demo mode and seeded influencer/product data when API keys are not set

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

After transcription, use **Extract claims** → select claims → **Run clip report**.
Include a **creator name** on the report so the Influencers leaderboard updates.

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
| `POST` | `/api/clip-report` | Search sources, judge agreement, return per-claim ratings (updates credibility ledger when `creator_name` is set) |
| `POST` | `/api/claims/quick-scan` | Lightweight claim flags for the Chrome extension overlay |
| `GET` | `/api/influencers` | List influencers with aggregated credibility scores |
| `GET` | `/api/influencers/{slug}` | Influencer detail, claim history, score breakdown |
| `GET` | `/api/products` | List supplements/products with credibility scores |
| `GET` | `/api/products/{product_id}` | Product detail and endorsement history |
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
    credibility.py        influencer + product scoring ledger
  influencers.py          legacy Feature 2 API module (credibility_store)
frontend/
  src/App.jsx             fact-check UI, influencers/products tabs, extension handoff
  src/VerdictCard.jsx     status-aware verdict renderer
  src/styles.css          light/dark theme system
chrome-extension/         browser extension (see chrome-extension/README.md)
DEPLOY.md                 Render + Vercel deployment guide
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

## Source Control

Team members who have merged PRs: Kennaissa Nabi, and others listed in GitHub pull request history.

## Next steps

- Live transcript scanning and richer extension UX (see open PRs)
- Stronger source-quality filtering and human review workflows
- Move credibility ledger from JSON files to a persistent database on Render
