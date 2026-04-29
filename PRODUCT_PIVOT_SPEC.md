# Veritas Product Pivot Spec

## Working Title

**Veritas — Your fitness bro fact checker**

## Current Product Direction

Veritas is pivoting from a narrow supplement-claim checker into a broader
platform for fact-checking influencers, brands, and social media fitness
claims.

The new product asks:

> "Can we trust what this influencer or brand says about fitness, supplements,
> training, nutrition, recovery, or body transformation?"

Instead of checking one isolated supplement claim, Veritas should evaluate the
claims made by public fitness figures and brands over time, attach credible
sources, and compute reputation-style credibility scores.

## Product One-Liner

Veritas transcribes fitness content, extracts broscience claims, verifies them
against credible sources using multiple LLM search agents, and produces
claim-level verdicts plus credibility scores for influencers and brands.

## Target Users

### Primary Users

- Intermediate lifters who watch TikTok, Instagram, YouTube Shorts, podcasts,
  or fitness reels and want to know whether a claim is legit.
- Fitness consumers deciding whether to trust an influencer, supplement brand,
  course, coaching program, or product recommendation.
- Students or researchers studying misinformation in online fitness culture.

### Secondary Users

- Coaches who want to audit claims made by competitors or brands.
- Creators who want to prove their own credibility.
- Journalists or content moderators reviewing fitness misinformation patterns.

## Problem Statement

Fitness content is dominated by confident claims that are difficult for normal
users to verify:

- "This supplement doubles testosterone."
- "Seed oils destroy your hormones."
- "Training to failure is always necessary."
- "This brand's pre-workout burns fat by itself."
- "You can spot-reduce belly fat with this protocol."

These claims are usually spread through short clips, podcasts, reels, ads, and
brand pages. The user rarely has a transcript, a citation, or the research
literacy needed to assess the claim.

Veritas solves this by converting content into claims, checking those claims
against credible sources, and aggregating the results into credibility scores.

## Product Scope

### In Scope

- Fitness science
- Supplements
- Nutrition claims related to fitness, weight loss, muscle gain, performance,
  recovery, hormones, sleep, and body composition
- Training methodology claims
- Recovery claims
- Influencer statements
- Brand marketing claims
- Claims from audio clips, video clips, links, screenshots, pasted captions,
  and transcripts

### Out of Scope

- Medical diagnosis
- Personalized medical advice
- Emergency health advice
- Prescription-drug recommendations
- Legal claims
- Non-fitness political or cultural claims
- Claims about private individuals who are not public influencers or brands

## Core Product Principles

1. **Claim-first, not content-first**
   The system should break messy content into atomic claims before judging it.

2. **Evidence before opinion**
   Verdicts must cite sources and explain why the sources support, contradict,
   or fail to address a claim.

3. **Multiple model agreement**
   Important verdicts should not rely on one LLM. At least two independent
   search/verdict agents should agree on the relevant sources and conclusion.

4. **Do not hallucinate certainty**
   If evidence is weak, mixed, irrelevant, or unavailable, the UI should say so.

5. **Scores must be explainable**
   Influencer and brand credibility scores must be traceable back to individual
   claims and source-backed verdicts.

6. **Public-claim safety**
   The product should evaluate public claims, not insult people. Tone should be
   skeptical, precise, and evidence-driven.

---

# Feature 1: Audio/Video Claim Fact-Checking

## Goal

Allow a user to upload or paste an audio/video clip, transcribe it, extract the
fitness claims, find reliable sources, and return verdicts that confirm, deny,
or contextualize the claims.

## User Story

As a user, I want to upload a short influencer clip so Veritas can tell me what
claims were made and whether science supports them.

## Inputs

- Uploaded audio file
- Uploaded video file
- Link to TikTok / Instagram / YouTube / podcast clip, if technically feasible
- Pasted transcript
- Screenshot or caption text

## Output

A structured report containing:

- Original transcript
- Extracted claims
- Per-claim verdict
- Sources used
- Agreement status between LLM agents
- Confidence level
- Overall clip credibility summary

## Suggested Flow

```text
User uploads clip or link
        |
        v
Transcription service
        |
        v
Transcript cleanup
        |
        v
Claim extraction model
        |
        v
Claim normalization + deduplication
        |
        v
Two independent search agents
        |
        v
Source agreement check
        |
        v
Verdict generation
        |
        v
User-facing report
```

## Transcription Layer

### Recommended Providers

| Provider | Why Use It | Notes |
|---|---|---|
| Groq Whisper | Fast and cheap transcription | Good fit if the team already has Groq credits |
| OpenAI Whisper API | Reliable, simple API | Good fallback |
| Deepgram | Strong production transcription features | More setup, useful later |
| Local Whisper | No credits needed | Slower; not ideal if the team is moving to credits |

## Claim Extraction

The transcript should be converted into atomic factual claims.

Example transcript:

> "Bro, tongkat ali boosts testosterone by 200%, creatine makes you bald, and
> carbs after 8 PM turn into fat."

Extracted claims:

1. Tongkat ali boosts testosterone by 200%.
2. Creatine causes hair loss.
3. Eating carbohydrates after 8 PM causes fat gain.

## Claim Categories

Each claim should be tagged with one or more categories:

- Supplement
- Training
- Nutrition
- Weight loss
- Muscle gain
- Hormones
- Recovery
- Sleep
- Injury prevention
- Product marketing
- Medical/prescription boundary
- Out of scope

## Multi-LLM Search Requirement

The user specifically wants at least two LLMs doing web/source search, one of
which is Groq.

### Proposed Agents

| Agent | Provider | Role |
|---|---|---|
| Search Agent A | Groq | Fast first-pass source search and claim interpretation |
| Search Agent B | OpenAI / Anthropic / Gemini / Perplexity / Tavily-backed model | Independent source search and conclusion |
| Judge Agent | Optional third model | Resolves disagreement and generates final structured verdict |

## Two-Agent Agreement Rule

A claim should only receive a strong verdict if both search agents agree on:

1. The claim meaning
2. The main sources used
3. The evidence direction
4. The confidence level or at least the uncertainty band

If they disagree, the system should show a disagreement state instead of hiding
it.

## Source Agreement Levels

| Level | Meaning | UI Treatment |
|---|---|---|
| `strong_agreement` | Agents cite overlapping high-quality sources and reach same conclusion | Normal verdict card |
| `partial_agreement` | Agents agree on conclusion but use different sources | Verdict card with source diversity note |
| `source_disagreement` | Agents use conflicting sources | Yellow review-needed panel |
| `conclusion_disagreement` | Agents reach different verdicts | No final tier; show both sides |
| `insufficient_sources` | Neither agent finds enough credible sources | No-evidence panel |

## Source Quality Rules

Prefer:

- Meta-analyses
- Systematic reviews
- Randomized controlled trials
- Position stands from credible organizations
- NIH, PubMed, examine-style public summaries where licensing allows
- Government or academic sources

Avoid or down-rank:

- Supplement brand blogs
- Affiliate marketing pages
- Anonymous forum posts
- Single mechanistic animal studies when human outcome claims are being made
- Influencer articles citing no primary sources
- Sources that directly profit from the claim unless clearly disclosed

## Claim Verdict Schema

```json
{
  "claim_id": "claim_123",
  "raw_claim": "Creatine causes hair loss.",
  "normalized_claim": "Creatine supplementation causes hair loss in adult men.",
  "category": ["supplement", "hair_loss"],
  "status": "ok",
  "tier": 2,
  "verdict_label": "Weak evidence",
  "summary": "Evidence that creatine causes hair loss is weak and indirect.",
  "evidence_direction": "mostly_contradicted",
  "confidence": "high",
  "agent_agreement": "strong_agreement",
  "sources": [
    {
      "title": "Creatine supplementation and DHT study",
      "url": "https://...",
      "source_type": "rct",
      "year": 2009,
      "sample_size": 20,
      "relevance": "Measured DHT but did not measure hair loss."
    }
  ],
  "agent_a": {
    "provider": "groq",
    "conclusion": "weak evidence",
    "source_urls": ["https://..."]
  },
  "agent_b": {
    "provider": "openai_or_other",
    "conclusion": "weak evidence",
    "source_urls": ["https://..."]
  }
}
```

## Clip-Level Report Schema

```json
{
  "clip_id": "clip_123",
  "source_type": "audio_upload",
  "creator_name": "optional influencer name",
  "brand_name": "optional brand name",
  "transcript": "Full cleaned transcript...",
  "claims": [],
  "overall_summary": "The clip contains 5 checkable claims. 2 are contradicted, 1 is mixed, 2 lack evidence.",
  "clip_credibility_score": 61,
  "needs_human_review": false,
  "created_at": "2026-04-28T00:00:00Z"
}
```

## Feature 1 MVP Acceptance Criteria

- User can upload or paste a transcript/audio clip.
- System transcribes or accepts transcript text.
- System extracts at least 1-10 claims from the content.
- Each claim gets checked by two independent LLM search/verdict agents.
- UI shows whether agents agreed.
- UI shows at least 2-5 sources per checked claim when available.
- System avoids a final verdict if the agents strongly disagree.

---

# Feature 2: Credibility Score for Individual Influencers

## Goal

Create a reputation score for an influencer based on the accuracy, evidence
quality, and risk level of claims they make over time.

## User Story

As a user, I want to search an influencer and see whether their fitness claims
are generally reliable before I trust their advice or buy what they promote.

## Influencer Profile Page

Each influencer should have a profile page with:

- Name / handle
- Platforms
- Profile image, if available
- Total claims checked
- Overall credibility score
- Claim accuracy breakdown
- Most common claim categories
- Worst claims
- Best-supported claims
- Brand relationships or product promotions, if known
- Timeline of checked content

## Credibility Score Range

Use a 0-100 score.

| Score | Label | Meaning |
|---|---|---|
| 90-100 | Highly credible | Mostly source-backed, low exaggeration |
| 75-89 | Generally reliable | Some misses, but mostly defensible |
| 60-74 | Mixed | Useful sometimes, but needs checking |
| 40-59 | Low credibility | Frequent exaggeration or weak evidence |
| 0-39 | High misinformation risk | Repeated contradicted or risky claims |

## Scoring Inputs

A good influencer score should consider:

1. **Claim accuracy**
   How often claims are supported, mixed, contradicted, or unsupported.

2. **Evidence quality**
   Whether claims rely on strong human evidence or weak mechanistic reasoning.

3. **Risk level**
   Bad supplement advice is not as dangerous as recommending unsafe drug use.

4. **Overstatement penalty**
   "May help" is very different from "will double testosterone."

5. **Correction behavior**
   Does the influencer correct old misinformation?

6. **Commercial conflict**
   Is the influencer selling the thing they are making claims about?

7. **Recency**
   Recent claims should matter more than very old claims.

## Proposed Influencer Score Formula

```text
Influencer Score =
  100
  - Contradicted Claim Penalty
  - Unsupported Claim Penalty
  - Exaggeration Penalty
  - High-Risk Health Claim Penalty
  - Undisclosed Commercial Claim Penalty
  + Correction Credit
  + Evidence-Backed Claim Credit
```

## Claim Contribution Weights

| Claim Outcome | Score Impact |
|---|---:|
| Strongly supported | +2 |
| Moderately supported | +1 |
| Mixed / context-dependent | 0 |
| Weak evidence but framed cautiously | -1 |
| Weak evidence but framed strongly | -3 |
| Contradicted | -5 |
| Dangerous / medically risky | -8 |
| Repeated false claim after correction | -10 |

## Risk Multipliers

| Risk Type | Multiplier |
|---|---:|
| Low-risk training opinion | 1.0x |
| Supplement purchase claim | 1.2x |
| Nutrition restriction claim | 1.3x |
| Hormone claim | 1.5x |
| Injury or rehab claim | 1.7x |
| Prescription drug / steroid / SARM claim | 2.0x |

## Commercial Conflict Penalties

| Situation | Penalty |
|---|---:|
| Claim promotes own supplement brand | -3 |
| Affiliate link attached | -2 |
| Sponsorship disclosed | -1 |
| Sponsorship not disclosed but likely | -4 |
| No commercial relationship | 0 |

## Influencer Score Schema

```json
{
  "influencer_id": "inf_123",
  "display_name": "Example Fitness Creator",
  "handles": {
    "tiktok": "@example",
    "instagram": "@example",
    "youtube": "@example"
  },
  "credibility_score": 72,
  "score_label": "Mixed",
  "claims_checked": 47,
  "supported_claims": 18,
  "mixed_claims": 11,
  "unsupported_claims": 9,
  "contradicted_claims": 7,
  "high_risk_claims": 2,
  "top_categories": ["supplements", "hypertrophy", "hormones"],
  "commercial_conflict_rate": 0.34,
  "last_updated": "2026-04-28T00:00:00Z"
}
```

## Influencer Page UX

Recommended sections:

1. **Score header**
   Large score, label, and short explanation.

2. **Evidence breakdown**
   Bar chart showing supported / mixed / weak / contradicted.

3. **Claim feed**
   Each checked claim appears as a card with verdict and source links.

4. **Risk flags**
   Highlight high-risk topics: hormones, extreme dieting, SARMs, steroids,
   injury rehab, medical claims.

5. **Commercial context**
   Show when claims are tied to products, sponsorships, affiliate links, or the
   influencer's own brand.

6. **Trend over time**
   Score movement by month as more clips are checked.

## Feature 2 MVP Acceptance Criteria

- User can create or select an influencer profile.
- User can attach checked clips/claims to that influencer.
- System computes a 0-100 credibility score.
- Score page explains why the score is high or low.
- User can click from score components to the underlying claims.
- Score updates when new claims are added.

---

# Feature 3: Credibility Score for Individual Brands

## Goal

Score supplement and fitness brands based on the factual accuracy of their
marketing claims, product claims, influencer partnerships, and evidence quality.

## User Story

As a user, I want to search a supplement brand and see whether its claims are
scientifically supported before buying its products.

## Brand Profile Page

Each brand should have:

- Brand name
- Website
- Product categories
- Overall credibility score
- Claims checked
- Product-level claim breakdown
- Label transparency indicators
- Influencer partnership risk
- Evidence quality summary
- Red flags

## Brand Claim Sources

Claims can come from:

- Product pages
- Ads
- Supplement facts labels
- Landing pages
- Email copy
- TikTok/Instagram sponsored posts
- Influencer affiliate content
- Packaging screenshots
- Founder interviews

## Brand Score Inputs

1. **Marketing claim accuracy**
   Are product claims supported by evidence?

2. **Dose honesty**
   Does the product contain clinically relevant doses?

3. **Ingredient transparency**
   Are exact ingredient amounts shown, or hidden in proprietary blends?

4. **Evidence quality**
   Does the brand cite human evidence, or vague mechanistic claims?

5. **Exaggeration and guarantee language**
   "Supports performance" is different from "melts fat."

6. **Safety transparency**
   Does the brand mention risks, contraindications, caffeine amount, banned
   substances, third-party testing?

7. **Influencer network quality**
   Do partner influencers have low credibility scores?

## Proposed Brand Score Formula

```text
Brand Score =
  100
  - False Marketing Claim Penalty
  - Underdosed Product Penalty
  - Proprietary Blend Penalty
  - Missing Safety Disclosure Penalty
  - Low-Credibility Influencer Partner Penalty
  - Exaggerated Transformation Claim Penalty
  + Third-Party Testing Credit
  + Clinically Dosed Product Credit
  + Transparent Label Credit
```

## Brand Score Components

| Component | Weight |
|---|---:|
| Claim accuracy | 35% |
| Dose transparency | 20% |
| Evidence quality | 15% |
| Safety transparency | 10% |
| Influencer partner quality | 10% |
| Label/product transparency | 10% |

## Brand Score Labels

| Score | Label | Meaning |
|---|---|---|
| 90-100 | Research-backed | Transparent, evidence-aligned, low hype |
| 75-89 | Mostly credible | Some hype, but generally defensible |
| 60-74 | Mixed | Some good products, some weak claims |
| 40-59 | High hype | Frequent overclaims or weak dosing |
| 0-39 | Low trust | Contradicted claims, poor transparency, risky marketing |

## Brand Score Schema

```json
{
  "brand_id": "brand_123",
  "brand_name": "Example Supplements",
  "website": "https://example.com",
  "credibility_score": 58,
  "score_label": "High hype",
  "claims_checked": 32,
  "products_checked": 6,
  "average_dose_transparency": 0.61,
  "third_party_testing": false,
  "proprietary_blend_count": 3,
  "supported_claims": 8,
  "mixed_claims": 6,
  "unsupported_claims": 12,
  "contradicted_claims": 6,
  "influencer_partner_risk": "medium",
  "last_updated": "2026-04-28T00:00:00Z"
}
```

## Brand Page UX

Recommended sections:

1. **Brand score header**
   Score, label, short reason.

2. **Product table**
   Product name, claim count, dose transparency, claim accuracy.

3. **Claim evidence feed**
   Marketing claims with verdicts and sources.

4. **Label transparency panel**
   Clinically dosed vs underdosed ingredients, proprietary blends, third-party
   testing, stimulant disclosure.

5. **Influencer partnership panel**
   List creators promoting the brand and their credibility scores.

6. **Red flags**
   High-risk claims, unsupported hormone claims, fat-loss exaggeration,
   undisclosed sponsorship patterns.

## Feature 3 MVP Acceptance Criteria

- User can create or select a brand profile.
- User can attach product claims, product pages, screenshots, or influencer
  sponsored clips to the brand.
- System computes a 0-100 brand credibility score.
- Score explains claim accuracy, dose transparency, and marketing hype.
- User can click into the claims behind the score.

---

# Shared Data Model

## Core Entities

```text
Influencer
  has_many Clips
  has_many Claims
  has_many BrandRelationships

Brand
  has_many Products
  has_many Claims
  has_many InfluencerRelationships

Product
  belongs_to Brand
  has_many Claims
  has_many Ingredients

Clip
  belongs_to optional Influencer
  belongs_to optional Brand
  has_many Claims

Claim
  belongs_to Clip / Influencer / Brand / Product
  has_many Verdicts
  has_many Sources

Verdict
  belongs_to Claim
  has agent outputs, final conclusion, score impact

Source
  title, url, source type, year, authors, study metadata
```

## Suggested Tables

### `influencers`

- `id`
- `display_name`
- `platform_handles`
- `profile_url`
- `bio`
- `credibility_score`
- `score_label`
- `claims_checked_count`
- `last_scored_at`

### `brands`

- `id`
- `name`
- `website`
- `credibility_score`
- `score_label`
- `products_checked_count`
- `claims_checked_count`
- `last_scored_at`

### `clips`

- `id`
- `source_type`
- `source_url`
- `uploaded_file_path`
- `transcript`
- `influencer_id`
- `brand_id`
- `created_at`

### `claims`

- `id`
- `raw_text`
- `normalized_text`
- `category`
- `risk_level`
- `influencer_id`
- `brand_id`
- `product_id`
- `clip_id`
- `created_at`

### `verdicts`

- `id`
- `claim_id`
- `status`
- `tier`
- `summary`
- `confidence`
- `evidence_direction`
- `agent_agreement`
- `score_impact`
- `created_at`

### `agent_runs`

- `id`
- `claim_id`
- `provider`
- `model`
- `search_query`
- `raw_response`
- `conclusion`
- `source_urls`
- `created_at`

### `sources`

- `id`
- `title`
- `url`
- `source_type`
- `year`
- `authors`
- `sample_size`
- `population`
- `quality_score`

### `claim_sources`

- `claim_id`
- `source_id`
- `agent_run_id`
- `relevance_note`

---

# System Architecture for the Pivot

## High-Level Architecture

```text
Frontend
  Upload / paste / profile search
        |
        v
Backend API
  clip ingestion
  transcription
  claim extraction
  fact-check orchestration
  scoring services
        |
        v
External AI Providers
  Groq transcription/search/verdict model
  OpenAI/Anthropic/Gemini second verifier
  Optional search API: Tavily, SerpAPI, Brave, Perplexity
        |
        v
Storage
  Postgres or SQLite for MVP
  Object storage for uploads
  Vector store for sources and claims
```

## Recommended Provider Stack

Since the team is moving away from Ollama and will use credits:

| Task | Recommended Provider | Why |
|---|---|---|
| Transcription | Groq Whisper | Very fast, cheap, simple |
| Claim extraction | OpenAI or Groq | Structured JSON output |
| Search Agent A | Groq | Required by product direction, fast |
| Search Agent B | OpenAI / Anthropic / Gemini | Independent model family |
| Web search | Tavily / Brave / SerpAPI / Perplexity | Needed for fresh web sources |
| Final judge | OpenAI structured output or Anthropic | Better JSON reliability |
| Embeddings | OpenAI text-embedding-3-small or local bge later | Search/dedup/profile memory |

## API Endpoints for New Product

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/clips/upload` | Upload audio/video clip |
| `POST` | `/api/clips/transcribe` | Transcribe clip |
| `POST` | `/api/claims/extract` | Extract claims from transcript |
| `POST` | `/api/claims/{id}/fact-check` | Run two-agent fact check |
| `GET` | `/api/claims/{id}` | Get claim verdict |
| `POST` | `/api/influencers` | Create influencer profile |
| `GET` | `/api/influencers/{id}` | Get profile + score |
| `POST` | `/api/influencers/{id}/clips` | Attach clip to influencer |
| `POST` | `/api/influencers/{id}/score/recalculate` | Recompute credibility score |
| `POST` | `/api/brands` | Create brand profile |
| `GET` | `/api/brands/{id}` | Get brand profile + score |
| `POST` | `/api/brands/{id}/products` | Add product |
| `POST` | `/api/brands/{id}/score/recalculate` | Recompute brand score |

---

# User Experience Direction

## Main Navigation

1. **Check a Clip**
   Upload audio/video, paste link, paste transcript.

2. **Influencers**
   Search, create, and view influencer credibility profiles.

3. **Brands**
   Search, create, and view brand credibility profiles.

4. **Claims Library**
   Browse all checked claims and verdicts.

## Check a Clip Flow

1. User uploads clip.
2. UI shows transcription progress.
3. Transcript appears with highlighted claim candidates.
4. User can accept, edit, or remove extracted claims.
5. User clicks **Fact-check claims**.
6. UI shows per-claim search progress:
   - Groq searching
   - Second model searching
   - Comparing sources
   - Building verdict
7. Final report appears.
8. User can attach report to influencer or brand.

## Influencer Profile UX

Header:

- Name / handle
- Credibility score
- Label
- Number of claims checked
- Last updated

Main content:

- Score breakdown
- Claims by category
- Recent checked clips
- Worst claims
- Best-supported claims
- Brand relationships

## Brand Profile UX

Header:

- Brand name
- Credibility score
- Label
- Products checked
- Claims checked

Main content:

- Product credibility table
- Claim accuracy breakdown
- Dose transparency panel
- Sponsorship/influencer network
- Red flags

---

# MVP Roadmap

## Phase 0 — Documentation and Design

- Finalize product spec.
- Update README away from Ollama/local-only language.
- Decide provider stack: Groq + second model + search API.
- Define environment variables and API key setup.

## Phase 1 — Claim Checking From Transcript

Build the simplest version without uploads first.

Input:

- User pastes transcript.

System:

- Extract claims.
- Run two-agent search.
- Compare sources/conclusions.
- Render claim verdict cards.

Why first:

- Avoids audio/video complexity.
- Tests the most important product behavior.

## Phase 2 — Audio Transcription

Add audio upload and Groq Whisper transcription.

Input:

- `.mp3`, `.wav`, `.m4a`, `.mp4`

Output:

- Transcript + extracted claims.

## Phase 3 — Influencer Profiles

Add:

- Influencer creation/search
- Attach checked clips
- Score calculation
- Influencer score page

## Phase 4 — Brand Profiles

Add:

- Brand creation/search
- Product-level claims
- Brand score calculation
- Brand score page

## Phase 5 — Evidence and Source Quality Improvements

Add:

- Source deduplication
- Domain trust scoring
- PubMed integration
- Better paper metadata extraction
- Human review flagging

---

# Suggested MVP Demo Script

## Demo 1: Clip Claim Checking

1. Paste a fake influencer transcript:

   > "Creatine makes you go bald, BCAAs are required to build muscle, and
   > tongkat ali doubles testosterone."

2. Veritas extracts three claims.
3. Two agents search sources.
4. UI shows:
   - Creatine hair loss: weak evidence
   - BCAAs required: contradicted/weak
   - Tongkat doubles testosterone: contradicted/exaggerated
5. Report shows agent agreement and sources.

## Demo 2: Influencer Score

1. Create influencer: `@examplefitness`.
2. Attach 3 checked clips.
3. Score appears: `58 / 100 — High hype`.
4. Click score breakdown to show contradicted claims.

## Demo 3: Brand Score

1. Create brand: `Example Preworkout`.
2. Add product page claims.
3. System identifies exaggerated fat-loss and testosterone claims.
4. Brand score appears: `62 / 100 — Mixed`.

---

# Open Product Questions

1. Which second model should pair with Groq?
   - OpenAI, Anthropic, Gemini, or Perplexity?

2. Which web search API should we use?
   - Tavily, Brave Search, SerpAPI, Perplexity, or provider-native search?

3. Should users be able to manually edit extracted claims before fact-checking?
   - Recommended: yes, for MVP accuracy.

4. Should influencer/brand scores be public, private, or local-only for the
   class project?

5. Should we store uploaded clips, or delete them after transcription?
   - Recommended MVP: delete after transcription unless user saves report.

6. How should we handle satire, jokes, or obvious exaggeration?
   - Recommended: tag as `non_literal_or_context_needed`.

7. Should brand scores include ingredient dose verification?
   - Recommended: yes, but after core claim checking works.

---

# Implementation Notes for This Repository

The current repo already has useful pieces:

- React/Vite UI foundation
- FastAPI backend
- Claim extraction endpoint pattern
- Verdict schema pattern
- Evidence card UX pattern
- Theme system
- Source-backed verdict UI

Major changes needed:

- Replace Ollama client with credit-based model clients.
- Add Groq client for transcription and/or search/verdict generation.
- Add a second independent model client.
- Add web search integration.
- Add persistent storage for influencers, brands, clips, claims, verdicts,
  sources, and agent runs.
- Expand the frontend from one claim-checking page into a platform with
  clip checking, influencer profiles, brand profiles, and a claims library.

Recommended next technical step:

> Build Phase 1 first: pasted transcript → extracted claims → two-agent
> fact-check → verdict cards. Then add audio upload.

This keeps the pivot achievable while still proving the new product direction.
