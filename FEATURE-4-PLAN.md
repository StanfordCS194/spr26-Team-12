# Feature 4 — Politician Identity Matching: Research & Implementation Plan

> Goal: Given an uploaded audio clip and a *claimed* politician, output a calibrated similarity score and a human-readable interpretation. Combined with Feature 2's AI-probability score, this lets a journalist distinguish *"AI-generated impersonation"* from *"authentic recording I just don't recognize"*.

---

## 1. State of the Art (2024–2026)

### 1.1 Speaker Verification (SV) backbones

| Model | Year | Vox1-O EER | Notes |
|---|---|---|---|
| x-vector (TDNN) | 2018 | ~3.1% | Legacy baseline. |
| **ECAPA-TDNN** | 2020 | 0.87% | Desplanques et al., Interspeech 2020. SpeechBrain checkpoint widely used. Apache-2.0. |
| ResNet34-LM (WeSpeaker) | 2023 | ~0.6% | Wang et al., ICASSP 2023. Used by `pyannote.audio`. CC-BY-4.0. |
| SKA-TDNN | 2023 | ~0.7% | Selective Kernel Attention TDNN. |
| **WavLM-Large + ECAPA** | 2024 | **0.39%** | ESPnet-SPK (Jung et al., Interspeech 2024). SOTA, but ~316M params. |
| ReDimNet-B6 | 2024 | 0.37% | Reshape-Dimension net. SOTA on Vox1-O, lighter. |

**Choice for v1: ECAPA-TDNN via SpeechBrain** (`speechbrain/spkrec-ecapa-voxceleb`).
- 14.7M params, runs at >10× real-time on CPU.
- 192-dim embedding, cosine similarity.
- Apache-2.0 license, ~1.7M downloads/month → battle-tested.
- The 0.5% EER gap vs. SOTA does not matter for a UI score that we threshold into 3 buckets.

**Upgrade path to v2:** swap to `pyannote/wespeaker-voxceleb-resnet34-LM` (better EER, drop-in) or to a WavLM frontend if GPU is available.

### 1.2 The "voice cloning" problem

Recent papers establish two facts that directly shape this feature:

1. **Modern TTS clones (XTTSv2, ElevenLabs, OpenAI Voice Engine, F5-TTS 2024) score *above* the SV decision threshold against the target speaker.** Müller et al. (Interspeech 2024, "Does Audio Deepfake Detection Generalize?") and the **ASVspoof 5** challenge (2024) confirm cosine similarity of cloned audio to the target often exceeds 0.65 — the same range as a genuine recording in noisy conditions.
2. **Stand-alone SV is therefore *not* a deepfake detector.** It is a *necessary* but not sufficient signal. The ASVspoof community has pivoted to **SASV (Spoofing-Aware Speaker Verification)** systems that *jointly* score `(speaker_match, spoof_probability)`.

**Implication for Veritas:** We never present `similarity_score` alone as a verdict. The UI / PDF must show the **2-D combination** with Feature 2's AI score.

### 1.3 Calibration

Raw cosine similarity is not a probability. Two best-practice fixes from the literature:

- **Score normalization (AS-Norm / S-Norm):** subtract the mean cosine of an impostor cohort, divide by std. Reduces speaker- and channel-bias. (Matejka et al., Odyssey 2017; still standard in 2024 NIST SRE submissions.)
- **PLDA or logistic calibration:** map cosine → log-likelihood ratio → probability. We use a lightweight logistic calibration (BOSARIS toolkit-style) trained on a held-out genuine/impostor split.

For v1 we ship **AS-Norm + a 3-bucket display** (Strong / Possible / No match). PLDA is v2.

---

## 2. The Decision Matrix (the actual product)

This is the user-facing logic. Both axes come from already-defined fields in [`backend/models.py`](backend/models.py).

|                        | **AI score low (<30%)** | **AI score mid (30–70%)** | **AI score high (>70%)** |
|------------------------|-------------------------|---------------------------|--------------------------|
| **Sim high (>75)**     | ✅ Authentic, matches   | ⚠ Inconclusive — re-check | 🚨 **Likely cloned voice of claimed speaker** |
| **Sim mid (45–75)**    | ⚠ Could be authentic, low-quality clip | ⚠ Inconclusive | 🚨 Suspected clone |
| **Sim low (<45)**      | ❓ Authentic but **wrong speaker** (mislabeled clip) | ❓ Wrong speaker, possibly synthetic | 🚨 **Synthetic + not the claimed speaker** |

This matrix is the deliverable. We store it as a table in code and surface the right cell on the results page.

---

## 3. Minimum Real-World Demo

What "working in real life" means for the demo:
1. User uploads a real C-SPAN clip of, e.g., **President Biden**.
2. User selects "Joe Biden" from the dropdown.
3. UI shows: AI score ~10%, similarity ~85%, verdict cell **✅ Authentic, matches**.
4. User uploads an **ElevenLabs clone of Biden** (publicly available demo clips exist).
5. UI shows: AI score ~80% (from Feature 2 mock or real), similarity ~70%, verdict cell **🚨 Likely cloned voice**.
6. User uploads a clip of Obama but selects "Biden" → similarity ~25%, cell **❓ Wrong speaker**.

To hit (1)–(6) we need: 5–10 indexed politicians with ≥30s of clean reference speech each. **Don't try to ship 200 on day 1.**

---

## 4. Implementation Plan

### Phase 0 — Decisions (frozen)
- Encoder: `speechbrain/spkrec-ecapa-voxceleb` (Apache-2.0, 192-d, 16 kHz mono).
- Distance: cosine on L2-normalized embeddings, then AS-Norm.
- Display thresholds (post-AS-Norm cosine, mapped to 0–100 via `(s+1)*50`):
  `≥75` Strong · `45–75` Possible · `<45` No match.
- Storage: SQLite BLOB (float32[192], 768 B/speaker). 200 speakers ≈ 150 KB.
- Reference audio policy: store **embeddings only**, not raw audio (license-safe, GDPR-safe).

### Phase 1 — Backend data layer
File: [`backend/database.py`](backend/database.py)
```sql
CREATE TABLE IF NOT EXISTS speakers (
    speaker_id   TEXT PRIMARY KEY,    -- slug, e.g. "biden-joe"
    name         TEXT NOT NULL,
    role         TEXT,                -- "47th US President"
    embedding    BLOB NOT NULL,       -- np.float32[192].tobytes()
    cohort_mean  BLOB,                -- per-speaker AS-Norm stats (optional v1)
    cohort_std   BLOB,
    n_clips      INTEGER NOT NULL,
    duration_sec REAL NOT NULL,
    source       TEXT,                -- "C-SPAN VOD #12345"
    created_at   TEXT NOT NULL
);
```
Helpers: `list_speakers()`, `get_speaker(id)`, `upsert_speaker(...)`, `iter_speakers()`.

### Phase 2 — Reference index builder (offline)
File: `backend/build_speaker_index.py` (new)
1. Read `backend/data/speakers.csv`: `speaker_id,name,role,urls` (urls pipe-separated).
2. For each speaker:
   - Download each URL with `yt-dlp -x --audio-format wav`.
   - Resample to 16 kHz mono via `torchaudio.functional.resample`.
   - VAD-trim silence with `silero-vad` (MIT, 1.8 MB).
   - Reject if total clean speech < 30 s.
   - Window into 5-second non-overlapping chunks; embed each; L2-normalize; **average** → centroid; L2-normalize again.
3. Build a **global impostor cohort** (~200 random VoxCeleb embeddings shipped as a fixture) for AS-Norm.
4. `upsert_speaker(...)`.

Runtime: ~1–2 min/speaker on CPU. Re-runnable, idempotent.

### Phase 3 — Inference module
File: `backend/speaker_match.py` (new)
```python
def load_encoder() -> EncoderClassifier: ...                    # lazy singleton
def embed_audio(path: str) -> np.ndarray: ...                   # → float32[192], L2-normed
def as_norm(score: float, probe_emb, ref_emb, cohort) -> float
def compare(audio_path: str, speaker_id: str) -> SpeakerMatch:
    ref = get_speaker(speaker_id)
    probe = embed_audio(audio_path)
    raw = float(np.dot(probe, ref.embedding))                   # cosine, [-1,1]
    norm = as_norm(raw, probe, ref.embedding, COHORT)
    score_0_100 = float((norm + 1) * 50)
    band = "Strong" if score_0_100 >= 75 else "Possible" if score_0_100 >= 45 else "No"
    interpretation = INTERPRETATION_TEMPLATES[band].format(name=ref.name, score=score_0_100)
    return SpeakerMatch(claimed_speaker=ref.name,
                        similarity_score=score_0_100,
                        interpretation=interpretation)
```

### Phase 4 — API
File: [`backend/main.py`](backend/main.py)
- Add `GET /speakers` → `[{speaker_id, name, role}]` for the dropdown.
- Change `POST /analyze/{file_id}` to accept optional body:
  ```python
  class AnalyzeRequest(BaseModel):
      claimed_speaker_id: Optional[str] = None
  ```
  In `analyze()`, after locating the file, if `claimed_speaker_id` is provided, call `speaker_match.compare(path, id)` and assign to `result.speaker_match`.
- Add FastAPI `@app.on_event("startup")` to warm-load the encoder + cohort once.

### Phase 5 — Frontend
File: [`frontend/src/UploadPage.jsx`](frontend/src/UploadPage.jsx)
- On mount, `GET /speakers`.
- Add a `<select>` "Claimed speaker (optional)" with a "— None —" default.
- Pass `{ claimed_speaker_id }` JSON in the analyze call.

File: [`frontend/src/ResultsPage.jsx`](frontend/src/ResultsPage.jsx)
- Already renders `speaker_match`. Add the **decision matrix cell** above it: a colored banner derived from `(overall_score, speaker_match.similarity_score)`.

No PDF / shared-view changes — those already render `SpeakerMatch`.

### Phase 6 — Tests
- `tests/test_speaker_match.py`:
  - Embed two crops of the same clip → similarity > 90.
  - Embed two unrelated VoxCeleb clips → similarity < 50.
  - AS-Norm reduces variance across 50 impostor pairs (assert std drops ≥30%).
- Integration: seed DB with one centroid, hit `/analyze` with the source clip → expect `Strong` band.

### Phase 7 — Docs
- Update [README.md](README.md) with new endpoint, new env deps, and `python build_speaker_index.py` instructions.
- Note in [ACTION-ITEMS.md](ACTION-ITEMS.md) that Feature 4 is shipped.

---

## 5. Risks, Cons, and Mitigations

| # | Risk | Why it matters | Mitigation |
|---|------|----------------|------------|
| R1 | **TTS clones beat the SV threshold** (Müller 2024, ASVspoof 5) | Headline failure — we tell users "matches Biden" for a fake | Never display `similarity` without `overall_score`. The decision matrix in §2 is enforced server-side; the UI cannot render a "match" verdict alone. |
| R2 | **Cross-channel mismatch**: phone-quality clip vs. broadcast reference | Same speaker scores low → false "wrong speaker" | (a) AS-Norm partly handles it. (b) Build reference centroids from *multiple* sources per speaker (broadcast + interview + phone if available). (c) Show a "Low audio quality" warning when SNR < 10 dB (compute via webrtcvad energy ratio). |
| R3 | **Demographic bias**: VoxCeleb is skewed white/male/English | Higher EER for under-represented voices → unfair false negatives | Document the limitation in the UI ("Reference model trained on English-language public speech"). Roadmap: evaluate on the **VoxBlink2** (2024) and **CommonVoice** test slices, report per-subgroup EER. |
| R4 | **Reference index drift / poisoning** | A bad clip in the index permanently corrupts a centroid | Build script keeps per-clip embeddings on disk (`.npz`) and rebuilds centroids deterministically. Hash + log every source URL. Code review required for `speakers.csv` PRs. |
| R5 | **Adversarial audio** (imperceptible perturbations targeting ECAPA) | Demonstrated against ECAPA in Kreuk et al. and follow-ups | Out of scope for v1. Mitigation v2: input pre-processing (MP3 re-encode at 64 kbps strips most adversarial perturbations — Hussain et al. 2021). |
| R6 | **Legal / IP**: distributing politician voice data | Even fair-use clips have licensing edges | Store **embeddings only**, never raw audio. Embeddings are non-invertible to intelligible speech (verified by attempts in Pizarro et al. 2023, output is unintelligible noise). Document this policy in README. |
| R7 | **Privacy / chilling effect**: building a "voice index of politicians" | Could be reframed as surveillance tooling | Limit scope to **public officials acting in official capacity**. Public-figure carve-out is the same legal basis news photographers use. Add a clear scope statement. No private individuals. |
| R8 | **Cold start latency**: SpeechBrain loads ~80 MB on first call | First request takes 5–10 s | `@app.on_event("startup")` warms encoder + cohort. Add `/healthz` that returns 503 until warm. |
| R9 | **Dependency weight**: `torch` + `speechbrain` ≈ 800 MB | Slows CI, bloats Docker | Use `torch --index-url https://download.pytorch.org/whl/cpu` (CPU wheel ~200 MB). Pin in a separate `backend/requirements-ml.txt` so Feature 1/5 contributors don't need it. |
| R10 | **Calibration drift**: thresholds tuned on VoxCeleb may not match political broadcast audio | Bands feel wrong in practice | Ship a `tools/calibrate.py` that takes a labeled CSV (`audio_path,speaker_id,is_genuine`) and refits the band thresholds. Re-run quarterly. |
| R11 | **User picks wrong speaker on purpose** | Trolling / misuse | Read-only audit log (already in `analyses` table via `created_at`). Rate limit `/analyze` per IP at the reverse proxy in production. |
| R12 | **Confident wrong answer on very short clips (<3 s)** | ECAPA EER doubles below 3 s (Snyder et al.) | Reject probe < 2 s of clean speech (post-VAD) with a clear "Audio too short for reliable speaker matching" message. Still run Feature 2. |

---

## 6. Day-by-day Build Order (single dev, ~5 working days)

| Day | Deliverable | Done when… |
|---|---|---|
| 1 | Phase 1 + 2 skeleton; ECAPA loads in a script; embed one clip end-to-end | `python -c "from speaker_match import embed_audio; print(embed_audio('test.wav').shape)"` → `(192,)` |
| 2 | Build index for 5 politicians with 2 clips each; verify intra-speaker cosine > inter-speaker cosine | Notebook plot shows clean separation |
| 3 | Phase 4 API + warmup; Postman test of `GET /speakers` and `POST /analyze` with `claimed_speaker_id` | `SpeakerMatch` appears in JSON response |
| 4 | Phase 5 frontend dropdown + decision-matrix banner | Manual flow §3 steps (1)–(3) work in the browser |
| 5 | Phase 6 tests; AS-Norm; risk mitigations R8/R12; README | `pytest` green; cold start < 1 s after warmup |

---

## 7. Open Questions to Resolve Before Day 1

1. **Initial speaker list** — who are the 5–10 launch politicians? (Suggest: current US president, VP, House/Senate leaders of both parties → 6 names, all have abundant C-SPAN footage.)
2. **GPU available for index build?** Not required (CPU is fine for 200 speakers) but cuts build time 5×.
3. **Are we OK declaring "English-language public officials only" as the v1 scope** in the UI? This is the cleanest legal posture.
4. **Where do raw downloaded clips live during indexing?** Suggest `/tmp/veritas/refs/` with a `.gitignore`d cache, deleted after centroid is committed.

---

## 8. References

1. Desplanques, B., Thienpondt, J., Demuynck, K. (2020). *ECAPA-TDNN: Emphasized Channel Attention, Propagation and Aggregation in TDNN Based Speaker Verification.* Interspeech 2020. arXiv:2005.07143.
2. Jung, J.-W. et al. (2024). *ESPnet-SPK: full pipeline speaker embedding toolkit…* Interspeech 2024. arXiv:[2401.17230](https://arxiv.org/abs/2401.17230).
3. Wang, H. et al. (2023). *Wespeaker: A research and production oriented speaker embedding learning toolkit.* ICASSP 2023.
4. Müller, N. et al. (2024). *Does Audio Deepfake Detection Generalize?* Interspeech 2024.
5. Wang, X. et al. (2024). *ASVspoof 5: Crowdsourced Speech Data, Deepfakes, and Adversarial Attacks at Scale.* ASVspoof Workshop 2024.
6. Matejka, P. et al. (2017). *Analysis of Score Normalization in Multilingual Speaker Recognition.* Odyssey 2017. (AS-Norm.)
7. Hussain, S. et al. (2021). *WaveGuard: Understanding and Mitigating Audio Adversarial Examples.* USENIX Security.
8. Pizarro, M. et al. (2023). *Privacy Analysis of Speaker Embeddings.* Interspeech 2023.
9. SpeechBrain model card: <https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb>.
10. pyannote / WeSpeaker model card: <https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM>.
