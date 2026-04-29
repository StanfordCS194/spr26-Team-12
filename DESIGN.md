# Supplement fact-checker — original design doc

> **Superseded direction:** This file documents the original local supplement
> checker. The current product pivot is the influencer/brand broscience
> fact-checking platform in [PRODUCT_PIVOT_SPEC.md](PRODUCT_PIVOT_SPEC.md).

A local-first RAG system that fact-checks fitness supplement claims against curated research. Built as a 5-person school project, demo-only, $0 cost.

---

## 1. Problem statement and target user

### The problem

People starting a fitness journey encounter supplement claims constantly — TikTok, YouTube, Reddit, gym buddies, supplement labels. The vast majority of these claims are "bro science": confident assertions with no citation, often built on a misread of one small study. Verifying them requires reading research papers, which most people will not do.

### Target user

Intermediate lifters (have lifted for 6 months or more). This is the highest-leverage group because:

- They already know the basic vocabulary (creatine, protein, "stack")
- They are actively making purchase decisions about supplements
- They are the most exposed to bro science from gym culture and social media
- They are skeptical enough to want verification, but not skeptical enough to read papers

We deliberately do not target beginners (who need broader education first) or advanced lifters (who already evaluate research themselves).

### Success criterion

A user pastes a claim from a TikTok or article and receives, within 30 seconds, a verdict that:

1. Tells them what the evidence actually shows
2. Cites the studies it used
3. Honestly reports when evidence is weak rather than fabricating confidence

---

## 2. System architecture

### Pipeline overview

The system has three input modes that converge into a single backend pipeline. Once each mode produces clean text, all downstream processing is identical.

```
Text mode      ──┐
Link mode      ──┼──> raw text ──> /extract ──> /verdict ──> verdict card
Screenshot     ──┘
```

### Layered architecture

```
┌─────────────────────────────────────────────┐
│  Frontend (React + Vite + Tailwind)         │
│  - Tabs (text, link, screenshot)            │
│  - Verdict card                             │
│  - Local history (localStorage)             │
└─────────────────────────────────────────────┘
                     │ HTTP
┌─────────────────────────────────────────────┐
│  API layer (FastAPI)                        │
│  - /extract endpoint                        │
│  - /verdict endpoint                        │
│  - Input pre-processors                     │
└─────────────────────────────────────────────┘
                     │
┌─────────────────────────────────────────────┐
│  Pipeline                                   │
│  - Claim extraction (LLM call)              │
│  - Embedding + retrieval                    │
│  - Re-ranking                               │
│  - Verdict generation (LLM call)            │
│  - JSON validation + retry                  │
└─────────────────────────────────────────────┘
                     │
┌─────────────────────────────────────────────┐
│  Models + storage                           │
│  - Llama 3.1 8B Instruct (Ollama)           │
│  - bge-small-en-v1.5 (embeddings)           │
│  - ms-marco-MiniLM-L-6-v2 (re-ranker)       │
│  - ChromaDB (vector store)                  │
│  - Curated corpus (50+ sources)             │
└─────────────────────────────────────────────┘
```

### Why two endpoints instead of one or SSE

We chose two-endpoint design (POST `/extract` then POST `/verdict`) over a single combined endpoint or Server-Sent Events because:

- Single endpoint creates ~22 seconds of dead air before the user sees anything. They will refresh and kill inference mid-flight.
- SSE is overkill for two events; it adds reconnect logic, EventSource lifecycle handling, and complications around POST bodies. Justified only if we add token-by-token streaming.
- Two endpoints give us the best perceived latency win (header at ~3s, full verdict at ~22s) with the simplest code path. Both endpoints are independently cacheable.

---

## 3. API contracts

### POST /extract

Extracts a clean atomic claim from messy user input.

**Request:**

```python
class ExtractRequest(BaseModel):
    raw_text: str  # max 2000 chars, validated
    source: Literal["text", "link", "screenshot"]  # for analytics only
```

**Response:**

```python
class ExtractResponse(BaseModel):
    extracted_claim: str  # one sentence, e.g. "Ashwagandha increases testosterone..."
    request_id: str  # used by frontend to call /verdict
    extraction_time_ms: int
```

**Latency target:** under 3 seconds.

### POST /verdict

Generates a full verdict from an extracted claim.

**Request:**

```python
class VerdictRequest(BaseModel):
    extracted_claim: str
    request_id: str  # links back to /extract for caching/analytics
```

**Response:** see Section 4 — the verdict JSON schema is the response body.

**Latency target:** under 25 seconds on CPU, under 5 seconds on GPU.

### Input pre-processors (internal endpoints)

Three internal helpers run before `/extract` based on the input mode:

- `process_text(raw)` — strips whitespace, validates length, returns string
- `process_url(url)` — detects platform (article / Reddit / YouTube), routes to appropriate scraper, returns extracted text
- `process_screenshot(image)` — runs Tesseract OCR, returns extracted text + confidence

Each is a plain Python function called by the route handler. They all return a string that goes into `/extract`.

---

## 4. Verdict JSON schema

This is what the verdict LLM returns and what the frontend renders.

```python
class EvidenceItem(BaseModel):
    source_title: str  # e.g. "Lopresti et al. — Ashwagandha and testosterone"
    source_url: str
    study_type: Literal[
        "meta_analysis",
        "rct",
        "observational",
        "review",
        "fact_sheet",
        "position_stand",
        "animal",
        "in_vitro",
    ]
    year: int
    sample_size: Optional[int]  # null if not applicable
    population: Optional[str]   # e.g. "stressed adult men"
    relevance_note: str  # one sentence: why this source matters

class Verdict(BaseModel):
    extracted_claim: str
    tier: Literal[1, 2, 3, 4, 5]
    # 1 = contradicted, 2 = weak, 3 = mixed, 4 = moderate, 5 = strong support
    summary: str  # one sentence, plain English
    effect_size: str  # e.g. "~10-15% increase" or "no measurable effect"
    dose: str       # e.g. "300-600 mg/day for 8 weeks" or "varies"
    population: str # e.g. "studied in stressed/infertile men"
    confidence: Literal["low", "medium", "high"]  # how confident we are in the tier
    why: str  # 2-3 sentence reasoning the LLM produced
    evidence: List[EvidenceItem]  # 3-5 items
    request_id: str
    generation_time_ms: int
```

### Tier definitions

| Tier | Label | Meaning |
|------|-------|---------|
| 1 | Contradicted | Multiple solid studies show the opposite |
| 2 | Weak | Little or low-quality evidence supports the claim |
| 3 | Mixed | Studies disagree; effect depends heavily on population/dose |
| 4 | Moderate | Several RCTs or one meta-analysis support the claim |
| 5 | Strong | Multiple meta-analyses or position stands consistently support |

### Confidence vs. tier (these are different)

- **Tier** = what the evidence says about the claim
- **Confidence** = how sure we are that the tier is right

A "weak evidence" verdict with "high confidence" means: we are sure the evidence is weak. This is a correct, defensible answer — not a hedge.

---

## 5. Corpus document structure

The corpus is the technical centerpiece of this project. Quality of retrieval is bounded by quality of the corpus.

### Document metadata schema

Each ingested source has metadata stored alongside the text in ChromaDB:

```python
class CorpusDoc(BaseModel):
    doc_id: str  # stable hash of source_url + supplement
    supplement: str  # e.g. "ashwagandha", "creatine"
    source_title: str
    source_url: str
    study_type: Literal[...]  # same enum as EvidenceItem.study_type
    year: int
    sample_size: Optional[int]
    population: Optional[str]  # e.g. "trained men 20-35"
    effect_direction: Optional[Literal["positive", "negative", "null", "mixed"]]
    notes: str  # human-curator notes, max 200 chars
    full_text: str  # the chunked content, concatenated
```

### Chunking strategy

Each document is split into chunks of 300-500 tokens with 50-token overlap. Each chunk inherits the parent document's full metadata. This way the LLM always knows the study type, year, and sample size of every chunk it reads.

### Source coverage (target: 50-60 documents)

We aim for 8-10 documents per supplement, covering 8-10 supplements:

- Creatine
- Ashwagandha
- Beta-alanine
- BCAAs
- Citrulline malate
- Caffeine
- Whey protein / protein timing
- Tongkat ali
- Pre-workout (caffeine + beta-alanine + citrulline stack)
- Fish oil

Per supplement, the ideal mix:

- 1-2 NIH ODS fact sheets (public domain)
- 2-3 RCTs from PubMed (abstract only, public domain)
- 1 meta-analysis if available
- 1 ISSN position stand if applicable
- 1 Cochrane abstract if applicable

### Source licensing

- PubMed abstracts: public domain, free to ingest
- NIH ODS fact sheets: public domain, free to ingest
- ISSN position stands: open access; check individual CC license, attribute in UI
- Cochrane: abstracts only (full text is paywalled)
- Examine.com: explicitly excluded due to redistribution restrictions

All sources display as clickable links in the verdict card so users can verify and we attribute properly.

---

## 6. RAG design choices

### Embedding model: bge-small-en-v1.5

384-dimensional, ~130 MB, fast on CPU. We will A/B test against `pritamdeka/S-PubMedBert-MS-MARCO` on our retrieval eval and pick the winner.

### Vector store: ChromaDB (local)

Persists to disk. No separate server needed. Embedded directly in the FastAPI process.

### Retrieval k

- Initial vector search: top 20 chunks
- After re-ranking: top 5 chunks passed to verdict LLM

### Re-ranker: ms-marco-MiniLM-L-6-v2

Cross-encoder, ~80 MB. Re-ranks the top 20 from initial search to top 5 by computing direct (claim, chunk) relevance scores. Adds ~50ms but meaningfully improves which chunks reach the LLM.

### Why this matters technically

The accuracy of a RAG system is bounded by what reaches the LLM. We are deliberately investing in retrieval quality (biomedical-aware embeddings, re-ranker, rich metadata) rather than a bigger model, because retrieval quality is the larger lever on a quantized 8B model.

---

## 7. Prompt strategy

### Claim extraction prompt

```
You are a claim extractor for a supplement fact-checking tool. Given the
user's input below, output a single sentence stating the claim in clean,
verifiable form. Focus on:
- Which supplement
- What effect
- What magnitude (if stated)
- What population (if stated)

Output ONLY the claim sentence. No preamble, no quotation marks.

Input: {raw_text}
Output:
```

Expected output: one sentence, e.g. "Ashwagandha increases testosterone by 40% in healthy adult men."

### Verdict prompt

```
You are a fitness supplement fact-checker. Evaluate the following claim using
ONLY the evidence provided. If the evidence is insufficient or off-topic, say
so honestly — do not fabricate.

Claim: {extracted_claim}

Evidence:
[1] type={study_type} year={year} n={sample_size} population={population}
{chunk_text}

[2] ...

Output a JSON object with these exact keys:
- tier: integer 1-5
- summary: one sentence, plain English
- effect_size: short phrase, human-readable
- dose: short phrase
- population: short phrase
- confidence: "low" | "medium" | "high"
- why: 2-3 sentences explaining the reasoning
- evidence_used: list of integer indices [1, 2, 3] you actually drew on

Output only the JSON. No preamble.
```

### JSON validation + retry

After receiving the LLM output:

1. Try to parse as JSON.
2. If it fails, retry once with the prompt: "Your previous response was not valid JSON. Output only valid JSON matching the schema above."
3. If it fails again, return a graceful "low confidence — system error" verdict to the frontend rather than a 500.

We expect ~5-10% retry rate with quantized 8B models.

### Prompt versioning

Prompts live in `backend/prompts/` as text files (`extract_v1.txt`, `verdict_v1.txt`, ...). Versioning is by filename, with the active version selected in config. This lets us A/B test prompts and roll back cleanly.

---

## 8. Frontend component breakdown

### Pages (just one)

- `App.tsx` — single-page app, state machine: `idle → extracting → extracted → verdicting → done | error`

### Components

```
<App>
  <Header />            // logo, "Built with Meta Llama 3" footer link
  <InputPanel>          // shown in `idle` state
    <Tabs />            //   text | link | screenshot
    <TextInput />       //   textarea, submit button
    <LinkInput />       //   URL field with platform detection pill
    <ScreenshotInput /> //   dropzone + paste handler + OCR confirm
  </InputPanel>
  <ProgressPanel />     // shown in `extracting | verdicting` states
                        //   shows extracted claim header as soon as available
  <VerdictCard />       // shown in `done` state
    <TierIndicator />   //   5-bar tier visualization
    <Summary />
    <ContextGrid />     //   effect size, dose, population, confidence
    <EvidenceList>      //   list of sources with study-type tags
      <EvidenceItem />
    </EvidenceList>
  </VerdictCard>
  <HistoryStrip />      // chips of recent claims, from localStorage
  <ErrorPanel />        // shown in `error` state
</App>
```

### State management

`useState` for the state machine. No Redux, no Zustand. The state is small enough.

### Data fetching

Plain `fetch()` with `AbortController` so the user can cancel mid-request. Two sequential calls:

```typescript
const extractRes = await fetch('/api/extract', {...});
setExtractedClaim(extractRes.extracted_claim);
const verdictRes = await fetch('/api/verdict', {body: extractRes.request_id, ...});
setVerdict(verdictRes);
```

### History

Last 10 extracted claims stored in `localStorage`. No backend persistence.

---

## 9. Demo plan

### Live demo flow (5 minutes)

| Time | What | Notes |
|------|------|-------|
| 0:00 | Problem framing | Show TikTok screenshot of bro-science claim |
| 0:30 | Approach | Show pipeline diagram on slide |
| 1:00 | Live demo: claim 1 | Use a cached showcase claim — predictable timing |
| 2:30 | Technical depth | Retrieval eval table, latency breakdown |
| 4:00 | Live demo: claim 2 | A harder claim where system honestly returns "weak evidence" |
| 5:00 | Q&A | Prepared answers for common questions |

### Showcase claims (pre-cached, pre-tested)

1. "Creatine causes hair loss" → tier 2 (weak), one small DHT study, no hair-loss measurement
2. "Ashwagandha boosts testosterone 40%" → tier 2 (weak), small effect in stressed/infertile men only
3. "BCAAs build muscle" → tier 2-3 (weak/mixed), redundant if protein intake is adequate
4. "Beta-alanine improves high-rep performance" → tier 4 (moderate), supported by multiple RCTs
5. "Caffeine improves strength performance" → tier 5 (strong), backed by ISSN position stand
6. (Edge case) "Tongkat ali boosts testosterone 200%" → tier 1 (contradicted) or tier 2 (weak)

The system runs each claim live during development. For the demo, we toggle to "demo mode" which serves the cached results instantly. This is honest — we built it; we are showing what it produces.

### Demo mode toggle

A config flag `DEMO_MODE=true` causes the backend to:

1. Hash the extracted claim
2. Look up in a JSON file of cached responses
3. Return the cached verdict immediately if found
4. Fall back to live inference if not cached

This guarantees demo timing but allows graceful behavior on unexpected questions during Q&A.

### Backup recording

A 90-second screen recording of the full demo working perfectly. If anything fails on stage, we play the video and continue narrating.

### Demo machine

Whoever has the most RAM (16GB minimum, 32GB ideal). All demo dependencies installed. Tested at the venue if possible. No active OS updates pending. Wifi disabled during demo (everything runs locally) to avoid distractions.

---

## 10. Eval methodology

### Retrieval eval

Hand-label 30-50 (claim, expected_source_ids) pairs. Run retrieval, measure:

- **Recall@5**: fraction of expected sources that appear in top 5 retrieved chunks
- **Recall@20**: fraction in top 20 (pre-rerank)
- **MRR**: mean reciprocal rank of the first expected source

Run before and after each retrieval change (embedding model, chunk size, re-ranker). Record results in a table.

### End-to-end verdict eval

Hand-label 20-30 (claim, expected_tier, expected_evidence_set) tuples. Run the full pipeline. Measure:

- **Tier accuracy**: fraction of verdicts within ±1 tier of expected
- **Evidence overlap**: Jaccard similarity between actual cited evidence and expected set
- **JSON validity rate**: fraction of verdicts that parse on first try

### Reporting in writeup

Include a results table like:

| Configuration | Recall@5 | Tier acc | JSON valid |
|---|---|---|---|
| baseline (bge-small) | 0.74 | 0.62 | 0.91 |
| + PubMedBert | 0.81 | 0.68 | 0.91 |
| + re-ranker | 0.87 | 0.74 | 0.91 |

This is the single most credible technical artifact in the writeup.

### Latency breakdown (also for the writeup)

| Stage | CPU time | % of total |
|---|---|---|
| Claim extraction (LLM) | 2.1s | 9% |
| Embedding | 0.04s | <1% |
| Vector search | 0.01s | <1% |
| Re-ranker | 0.05s | <1% |
| Verdict (LLM) | 19.5s | 88% |
| JSON validation | 0.3s | 1% |
| **Total** | **~22s** | 100% |

---

## 11. Five-person task breakdown

### Person 1 — Backend lead

Owns: FastAPI app, route handlers, prompt files, JSON validation + retry, error handling.

Specifically:

- `/extract` and `/verdict` route handlers
- Pydantic models for all request/response shapes
- Calls to Ollama HTTP API for inference
- Prompt versioning system (`prompts/extract_v*.txt`)
- Retry logic on JSON parse failure
- Demo mode toggle and cached-response logic

### Person 2 — RAG / corpus lead

Owns: corpus, ChromaDB ingestion, retrieval logic, embeddings, re-ranking, eval harness.

Specifically:

- Manual curation of 50-60 corpus documents with metadata
- Ingestion script (chunk → embed → store in ChromaDB)
- Embedding A/B test (bge-small vs PubMedBert)
- Re-ranker integration
- Hand-labeled eval set (30-50 retrieval + 20-30 end-to-end)
- Eval harness that produces the comparison table for the writeup

This is the largest workload and the most graded-relevant role.

### Person 3 — Input pipeline

Owns: all three input modes' pre-processing, scrapers, OCR.

Specifically:

- Text input validation
- URL detector + routers (article via trafilatura, Reddit via JSON API, YouTube via youtube-transcript-api)
- Tesseract OCR pipeline
- Image upload handling, base64 decoding, format validation
- Cmd+V paste support for screenshots
- Test cases for the demo URLs and screenshots

### Person 4 — Frontend lead

Owns: React app, all components, state machine, fetch logic.

Specifically:

- Vite + React + Tailwind setup
- All UI components (input panel, verdict card, progress panel)
- State machine implementation
- `fetch()` with AbortController
- localStorage history
- Tab UI and platform-detection pill
- Dropzone + paste handler

### Person 5 — Infra / quality

Owns: dev environment, Docker, eval harness CI, demo robustness, writeup support.

Specifically:

- Docker compose for the full stack (dev only — production deployment not required)
- Ollama + model setup script (single command spins up the demo)
- Demo mode toggle + cached responses JSON
- Backup demo recording
- Latency profiling
- The writeup tables (eval results, latency breakdown)
- Test runner for the eval harness

---

## 12. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM hangs during live demo | Medium | High | Demo mode + backup video |
| Scrapers break before demo | Medium | Medium | Cache demo URLs locally; don't live-fetch |
| OCR fails on demo screenshot | Low | Medium | Pre-test demo screenshots; user-edit step is the safety net |
| Verdict quality is poor on showcase claims | Medium | High | Iterate on prompts + corpus until showcase claims look great; this is the single most important success criterion |
| JSON parse failures > 10% | Low | Medium | Retry logic + graceful fallback verdict |
| Demo machine RAM exhausted | Low | High | Only run necessary services during demo; close Chrome |
| Embedding A/B inconclusive | Medium | Low | Default to bge-small; report findings honestly in writeup |
| Team member sick on demo day | Low | High | Two team members rehearse the demo; either can present |
| Wifi at venue is bad | High | Low | Everything runs locally; wifi only needed for backup video |
| Audience asks question we can't answer | High | Low | Prepare answers for top 5 questions; "we'd address that with more time" is acceptable |

---

## Appendix A — Tech stack summary

| Layer | Choice | Why |
|---|---|---|
| LLM inference | Llama 3.1 8B Instruct via Ollama (Q4_K_M) | Fits 16GB RAM, free, strong reasoning |
| Embeddings | bge-small-en-v1.5 (with PubMedBert A/B) | Fast on CPU, good baseline; A/B for technical depth |
| Re-ranker | ms-marco-MiniLM-L-6-v2 | Adds accuracy for ~80MB cost |
| Vector DB | ChromaDB local | No separate server, persists to disk |
| Backend | FastAPI + Pydantic | Native to Python ML stack, automatic OpenAPI docs |
| Frontend | React + Vite + Tailwind | Standard, well-known, fast dev cycle |
| OCR | Tesseract | Free, local, good enough for demo |
| Scrapers | trafilatura, youtube-transcript-api, Reddit JSON | All free, no API keys |
| Storage | localStorage (frontend), ChromaDB (corpus) | No database needed |
| Hosting | localhost during demo | $0 |

Total cost: $0.

---

## Appendix B — What we deliberately did NOT include

For the technical writeup and Q&A, having clear answers about scope is important. We deliberately scoped out:

- User accounts and authentication (no users in MVP)
- Production deployment (demo only)
- Cloud hosting (everything runs locally)
- Mobile app (web only)
- Custom-trained models (RAG with general LLM is enough)
- TikTok and Instagram URL scraping (brittle; screenshot mode bridges this gap)
- Examine.com content (licensing)
- Personalized recommendations or "should YOU take this" advice (medical liability)
- Affiliate links or product purchases (trust)
- Multilingual support (English only)
- Real-time scientific paper updates (corpus is curated, manually refreshed)

These are all reasonable v2 directions. None are required for the demo.
