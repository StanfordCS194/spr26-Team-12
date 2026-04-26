"""
Feature 2 — AI / Human Detection Engine

Architecture
────────────
Primary model  (60 % weight when available)
    facebook/wav2vec2-base fine-tuned for deepfake detection
    (dima806/deepfake-vs-real-audio-detection via HuggingFace)
    Falls back gracefully when torch / transformers are absent or the
    first download fails.

Secondary model  (40 % weight — always runs)
    Ensemble of two acoustic analysers:
      · AcousticAnalyser  — classic speech-science features (MFCC deltas,
                             pitch jitter, spectral flux, RMS dynamics, ZCR)
      · SpectrogramCNN     — mel-spectrogram band analysis, harmonic
                             structure, and temporal frame-correlation
                             (mirrors what a CNN learns from spectrograms)

Output  (Feature 2.3)
    DetectionResult contains overall_score, verdict, 95 % CI,
    per-segment scores with top-3 explainability contributors, and
    a plain-English summary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import librosa
import numpy as np

from preprocessor import Segment, load_and_preprocess, segment_audio

logger = logging.getLogger(__name__)

VERDICT_THRESHOLD = 50.0   # ≥ this → "Likely AI-Generated"
MIN_CI_HALF_WIDTH = 2.5    # minimum ± width for the confidence interval
MAX_SEGMENTS = 100         # ~5 min at 3 s/segment — caps memory on very long files


# ─────────────────────────────────────────────────────────────────────────────
# Data contracts
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SegmentResult:
    start_time: float
    end_time: float
    confidence_score: float       # 0–100 likelihood of AI generation
    contributors: list[str]       # top-3 human-readable feature labels


@dataclass
class DetectionResult:
    overall_score: float
    verdict: str                  # "Likely Authentic" | "Likely AI-Generated"
    confidence_low: float
    confidence_high: float
    segments: list[SegmentResult]
    summary: str
    model_used: str


# ─────────────────────────────────────────────────────────────────────────────
# Acoustic Feature Analyser  (Feature 2.1 derived features + Feature 2.2)
# ─────────────────────────────────────────────────────────────────────────────

# For each feature: (tts_upper, real_lower) — linear ramp between the two.
# score = clip((real_lower − observed) / (real_lower − tts_upper), 0, 1)
# → 1.0 means strongly AI-like, 0.0 means clearly natural.
_ACOUSTIC_THRESHOLDS: dict[str, tuple[float, float]] = {
    #                              TTS-like  Natural
    "pitch_stability":             (0.02,    0.22),   # F0 coefficient of variation — modern TTS can reach 0.10+
    "spectral_flux_regularity":    (0.25,    1.20),   # spectral-flux CV — modern TTS can reach 0.70+
    "mfcc_delta_flatness":         (0.50,    2.50),   # MFCC-delta CV — wider to catch subtle uniformity
    "energy_envelope_flatness":    (0.08,    0.70),   # RMS-energy CV — modern TTS improving at dynamics
    "spectral_centroid_stability": (0.05,    0.40),   # spectral-centroid CV — wider range
    "zcr_uniformity":              (0.30,    1.80),   # ZCR CV — wider range
}

_ACOUSTIC_WEIGHTS: dict[str, float] = {
    "pitch_stability":             0.28,
    "spectral_flux_regularity":    0.20,
    "mfcc_delta_flatness":         0.20,
    "energy_envelope_flatness":    0.14,
    "spectral_centroid_stability": 0.10,
    "zcr_uniformity":              0.08,
}

_ACOUSTIC_LABELS: dict[str, tuple[str, str]] = {
    # (AI-like label, Natural label)
    "pitch_stability":             ("Unusual pitch stability (low F0 jitter)",
                                    "Natural pitch variation"),
    "spectral_flux_regularity":    ("Spectral smoothing artifact detected",
                                    "Natural spectral variation"),
    "mfcc_delta_flatness":         ("Unnaturally uniform formant transitions",
                                    "Natural coarticulation patterns"),
    "energy_envelope_flatness":    ("Flat energy envelope — missing natural dynamics",
                                    "Natural energy dynamics"),
    "spectral_centroid_stability": ("Spectral centroid unusually stable",
                                    "Normal spectral movement"),
    "zcr_uniformity":              ("Unnatural voiced/unvoiced transition pattern",
                                    "Normal ZCR variation"),
}


def _linear_score(value: float, tts_upper: float, real_lower: float) -> float:
    """Map *value* to [0, 1] where 1 = strongly AI-like."""
    if real_lower <= tts_upper:
        return 0.5
    return float(np.clip((real_lower - value) / (real_lower - tts_upper), 0.0, 1.0))


def _acoustic_features(y: np.ndarray, sr: int) -> dict[str, float]:
    """Return a dict of raw feature values (not scores) for *y*."""
    feats: dict[str, float] = {}

    # ── Pitch (F0) coefficient of variation ───────────────────────────────
    try:
        f0, _, _ = librosa.pyin(
            y,
            fmin=float(librosa.note_to_hz("C2")),
            fmax=float(librosa.note_to_hz("C7")),
            sr=sr,
            fill_na=None,
        )
        f0_v = f0[~np.isnan(f0)] if f0 is not None else np.array([])
        if len(f0_v) > 10:
            feats["pitch_stability"] = float(np.std(f0_v) / (np.mean(f0_v) + 1e-9))
        else:
            feats["pitch_stability"] = 0.07   # neutral when no voiced frames
    except Exception:
        feats["pitch_stability"] = 0.07

    # ── Spectral flux CV ───────────────────────────────────────────────────
    stft_mag = np.abs(librosa.stft(y, n_fft=512))
    flux = np.sqrt(np.sum(np.diff(stft_mag, axis=1) ** 2, axis=0) + 1e-12)
    feats["spectral_flux_regularity"] = float(np.std(flux) / (np.mean(flux) + 1e-9))

    # ── MFCC delta CV ──────────────────────────────────────────────────────
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    d_mfcc = librosa.feature.delta(mfcc)
    feats["mfcc_delta_flatness"] = float(
        np.std(d_mfcc) / (np.mean(np.abs(d_mfcc)) + 1e-9)
    )

    # ── RMS energy CV ──────────────────────────────────────────────────────
    rms = librosa.feature.rms(y=y)[0]
    feats["energy_envelope_flatness"] = float(
        np.std(rms) / (np.mean(rms) + 1e-9)
    )

    # ── Spectral centroid CV ───────────────────────────────────────────────
    sc = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    feats["spectral_centroid_stability"] = float(np.std(sc) / (np.mean(sc) + 1e-9))

    # ── Zero-crossing rate CV ──────────────────────────────────────────────
    zcr = librosa.feature.zero_crossing_rate(y)[0]
    feats["zcr_uniformity"] = float(np.std(zcr) / (np.mean(zcr) + 1e-9))

    return feats


def acoustic_score(y: np.ndarray, sr: int) -> tuple[float, list[str]]:
    """
    Return (ai_probability_0_100, top_3_contributors) from acoustic features.
    """
    raw = _acoustic_features(y, sr)
    logger.info("acoustic raw features: %s", {k: round(v, 4) for k, v in raw.items()})

    scored: dict[str, float] = {
        name: _linear_score(raw[name], *_ACOUSTIC_THRESHOLDS[name])
        for name in _ACOUSTIC_THRESHOLDS
    }
    logger.info("acoustic scored features: %s", {k: round(v, 3) for k, v in scored.items()})

    total_weight = sum(_ACOUSTIC_WEIGHTS.values())
    combined = sum(scored[k] * _ACOUSTIC_WEIGHTS[k] for k in scored) / total_weight

    # Top-3 contributors (highest individual AI-likelihood scores)
    ranked = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
    contributors = [
        _ACOUSTIC_LABELS[k][0] if v >= 0.5 else _ACOUSTIC_LABELS[k][1]
        for k, v in ranked[:3]
    ]

    return float(np.clip(combined * 100, 0, 100)), contributors


# ─────────────────────────────────────────────────────────────────────────────
# Spectrogram CNN Analyser  (secondary — always runs)
# ─────────────────────────────────────────────────────────────────────────────

def spectrogram_cnn_score(y: np.ndarray, sr: int) -> tuple[float, list[str]]:
    """
    Mel-spectrogram analysis that mirrors learned CNN patterns:
      · Frequency-band energy ratios
      · Frame-to-frame temporal correlation (too regular = AI)
      · Harmonic-to-percussive ratio (TTS is unnaturally clean)
      · Spectral contrast stability
    Returns (ai_probability_0_100, top_3_contributors).
    """
    mel = librosa.feature.melspectrogram(
        y=y, sr=sr, n_mels=128, n_fft=2048, hop_length=512
    )
    mel_db = librosa.power_to_db(mel, ref=np.max)

    cnn_scores: dict[str, float] = {}

    # ── Band energy ratio ──────────────────────────────────────────────────
    # TTS often has less natural high-frequency drop-off
    low_mean = mel_db[:40].mean()    # ~0–2.5 kHz  (negative dB values)
    mid_mean = mel_db[40:90].mean()  # ~2.5–5.6 kHz
    high_mean = mel_db[90:].mean()   # 5.6 kHz+
    # Real speech: large gap (low_mean - high_mean ≈ 20–40 dB)
    # TTS: smaller gap (~5–18 dB), more uniform energy across bands
    band_gap = float(low_mean - high_mean)   # positive = natural roll-off
    cnn_scores["band_energy_ratio"] = float(np.clip(1.0 - (band_gap - 5) / 30, 0, 1))

    # ── Temporal correlation of mel frames ─────────────────────────────────
    # TTS produces frames that are too similar (columns in mel-DB are too correlated)
    # Note: adjacent mel frames are ALWAYS highly correlated (>0.90) in any
    # speech, so raw avg_corr is non-discriminative.  We map from the
    # discriminative range: real ≈ 0.75–0.90, TTS ≈ 0.92–0.99.
    n_frames = min(mel_db.shape[1] - 1, 30)
    if n_frames > 0:
        corrs = []
        for t in range(n_frames):
            c = float(np.corrcoef(mel_db[:, t], mel_db[:, t + 1])[0, 1])
            if not np.isnan(c):
                corrs.append(abs(c))
        avg_corr = float(np.mean(corrs)) if corrs else 0.85
        # Map [0.75, 0.98] → [0, 1]  where high correlation = AI-like
        cnn_scores["temporal_frame_correlation"] = float(
            np.clip((avg_corr - 0.75) / 0.23, 0, 1)
        )
    else:
        cnn_scores["temporal_frame_correlation"] = 0.5

    # ── Harmonic cleanness ─────────────────────────────────────────────────
    # TTS is nearly free of breath noise and aperiodic components
    try:
        harmonic, percussive = librosa.effects.hpss(y)
        harm_rms = float(np.sqrt(np.mean(harmonic ** 2)) + 1e-9)
        perc_rms = float(np.sqrt(np.mean(percussive ** 2)) + 1e-9)
        hnr = harm_rms / perc_rms
        # Natural speech: hnr typically 3–10; TTS: 15–50
        cnn_scores["harmonic_cleanness"] = float(np.clip((hnr - 5) / 20, 0, 1))
    except Exception:
        cnn_scores["harmonic_cleanness"] = 0.5

    # ── Spectral contrast stability ────────────────────────────────────────
    sc_contrast = librosa.feature.spectral_contrast(y=y, sr=sr, n_bands=6)
    sc_cv = float(np.std(sc_contrast) / (np.mean(np.abs(sc_contrast)) + 1e-9))
    # Real speech: sc_cv typically 0.8–1.5 (more variation)
    # TTS: sc_cv typically 0.3–0.7 (more uniform contrast)
    cnn_scores["spectral_contrast_stability"] = float(
        np.clip(1 - (sc_cv - 0.3) / 1.0, 0, 1)
    )

    combined = float(np.mean(list(cnn_scores.values())))

    cnn_labels = {
        "band_energy_ratio":            ("Unnatural high-frequency energy distribution",
                                         "Natural spectral roll-off"),
        "temporal_frame_correlation":   ("Mel frames too temporally uniform (TTS pattern)",
                                         "Natural frame-to-frame variation"),
        "harmonic_cleanness":           ("Unusually clean harmonic structure (no breath noise)",
                                         "Natural aperiodic components present"),
        "spectral_contrast_stability":  ("Spectral contrast too stable across bands",
                                         "Natural spectral contrast variation"),
    }
    ranked = sorted(cnn_scores.items(), key=lambda kv: kv[1], reverse=True)
    contributors = [
        cnn_labels[k][0] if v >= 0.5 else cnn_labels[k][1]
        for k, v in ranked[:3]
    ]

    return float(np.clip(combined * 100, 0, 100)), contributors


# ─────────────────────────────────────────────────────────────────────────────
# Primary: Wav2Vec2 Deepfake Classifier  (optional — loads lazily)
# ─────────────────────────────────────────────────────────────────────────────

_W2V2_PIPE = None
_W2V2_ATTEMPTED = False
_W2V2_MODEL = "MelodyMachine/Deepfake-audio-detection-V2"


def _get_w2v2_pipe():
    """Lazy-load the HuggingFace wav2vec2 pipeline; returns None on failure."""
    global _W2V2_PIPE, _W2V2_ATTEMPTED
    if _W2V2_ATTEMPTED:
        return _W2V2_PIPE
    _W2V2_ATTEMPTED = True
    try:
        from transformers import pipeline as hf_pipeline  # noqa: PLC0415

        _W2V2_PIPE = hf_pipeline(
            "audio-classification",
            model=_W2V2_MODEL,
            device=-1,           # CPU inference
            trust_remote_code=False,
        )
        logger.info("Loaded primary wav2vec2 model (%s)", _W2V2_MODEL)
    except Exception as exc:
        logger.warning(
            "Primary wav2vec2 model unavailable — using acoustic ensemble only. "
            "Reason: %s", exc
        )
        _W2V2_PIPE = None
    return _W2V2_PIPE


def wav2vec2_score(y: np.ndarray, sr: int) -> Optional[float]:
    """
    Run the fine-tuned wav2vec2 deepfake classifier on a segment.
    Returns ai_probability_0_100 or None if model is unavailable.
    """
    pipe = _get_w2v2_pipe()
    if pipe is None:
        return None
    try:
        results = pipe({"array": y.astype(np.float32), "sampling_rate": int(sr)})
        logger.info("wav2vec2 raw output: %s", results)
        # Expect labels "FAKE" / "REAL" (model-dependent capitalisation)
        for r in results:
            if r["label"].upper() in ("FAKE", "SPOOF", "AI"):
                return float(r["score"] * 100)
        # If we only see a REAL label, invert it
        for r in results:
            if r["label"].upper() in ("REAL", "HUMAN", "GENUINE"):
                return float((1 - r["score"]) * 100)
        logger.warning("wav2vec2 labels not recognised: %s", [r["label"] for r in results])
        return None
    except Exception as exc:
        logger.debug("wav2vec2 inference error: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Ensemble & Output  (Feature 2.3)
# ─────────────────────────────────────────────────────────────────────────────

def _merge_contributors(
    acou_contributors: list[str],
    cnn_contributors: list[str],
    w2v2_score_val: Optional[float],
) -> list[str]:
    """Deduplicate and return the top-3 contributor strings."""
    seen: set[str] = set()
    merged: list[str] = []
    for c in acou_contributors + cnn_contributors:
        if c not in seen:
            seen.add(c)
            merged.append(c)
        if len(merged) == 3:
            break
    if w2v2_score_val is not None and len(merged) < 3:
        merged.append("Neural wav2vec2 deepfake classifier score")
    return merged[:3] or ["Audio characteristics within natural range"] * 3


def _fmt_time(seconds: float) -> str:
    """Format seconds as M:SS for the plain-English summary."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


def _plain_english_summary(
    segments: list[SegmentResult],
    overall_score: float,
    model_used: str,
) -> str:
    high = [s for s in segments if s.confidence_score >= 70]
    med  = [s for s in segments if 40 <= s.confidence_score < 70]

    if overall_score < VERDICT_THRESHOLD:
        verdict_phrase = "no strong indicators of AI generation were found"
        tone = "Acoustic properties are consistent with natural human speech."
    elif overall_score < 70:
        verdict_phrase = "moderate indicators of potential AI generation were detected"
        tone = "Results are ambiguous — independent verification is recommended."
    else:
        verdict_phrase = "strong indicators of AI generation were detected"
        tone = (
            "These findings are consistent with neural text-to-speech synthesis "
            "or AI voice cloning."
        )

    if high:
        t0 = _fmt_time(high[0].start_time)
        t1 = _fmt_time(high[-1].end_time)
        # Collect unique top contributors from the highest-scoring segments
        seen_feats: set[str] = set()
        unique_feats: list[str] = []
        for seg in high[:3]:
            for feat in seg.contributors:
                if feat not in seen_feats:
                    seen_feats.add(feat)
                    unique_feats.append(feat)
                if len(unique_feats) == 3:
                    break
            if len(unique_feats) == 3:
                break
        feat_str = "; ".join(unique_feats) if unique_feats else "unusual spectral properties"
        hotspot = (
            f" Segment(s) {t0}–{t1} displayed the highest AI probability "
            f"({high[0].confidence_score:.0f}%), exhibiting: {feat_str.lower()}."
        )
    elif med:
        hotspot = (
            f" {len(med)} segment(s) showed moderate AI characteristics "
            f"(40–69% probability)."
        )
    else:
        hotspot = ""

    return (
        f"Analysis of {len(segments)} segment(s) indicates that {verdict_phrase}. "
        f"Overall AI-generation probability: {overall_score:.1f}% "
        f"(95% CI: varies by segment).{hotspot} "
        f"{tone} "
        f"[Veritas | {model_used}]"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def analyze(audio_path: str) -> DetectionResult:
    """
    Full Feature 2 pipeline:
        1. Preprocess audio (2.1)
        2. Score each 3-second segment with the ensemble model (2.2)
        3. Aggregate scores → overall result with CI and verdict (2.3)
    """
    # ── 2.1 Preprocessing ────────────────────────────────────────────────
    y, sr = load_and_preprocess(audio_path)
    segments = segment_audio(y, sr)

    if len(segments) > MAX_SEGMENTS:
        logger.warning(
            "Audio produced %d segments; capping at %d for memory safety",
            len(segments), MAX_SEGMENTS,
        )
        segments = segments[:MAX_SEGMENTS]

    # Determine which models are active
    has_w2v2 = _get_w2v2_pipe() is not None

    if has_w2v2:
        model_name = (
            "Wav2Vec2 Deepfake Classifier (dima806) + "
            "Acoustic Feature Ensemble + CNN Spectrogram Analysis"
        )
        # Ensemble weights: wav2vec2 60 %, acoustic 25 %, CNN 15 %
        w_w2v2, w_acou, w_cnn = 0.60, 0.25, 0.15
    else:
        model_name = "Acoustic Feature Ensemble + CNN Spectrogram Analysis"
        # Acoustic 60 %, CNN 40 %
        w_w2v2, w_acou, w_cnn = 0.00, 0.60, 0.40

    # ── 2.2 Per-segment scoring ───────────────────────────────────────────
    seg_results: list[SegmentResult] = []

    for seg in segments:
        acou_val, acou_contrib = acoustic_score(seg.audio, seg.sample_rate)
        cnn_val, cnn_contrib = spectrogram_cnn_score(seg.audio, seg.sample_rate)
        w2v2_val = wav2vec2_score(seg.audio, seg.sample_rate) if has_w2v2 else None

        if w2v2_val is not None:
            final = w_w2v2 * w2v2_val + w_acou * acou_val + w_cnn * cnn_val
        else:
            total_fallback = w_acou + w_cnn
            final = (w_acou / total_fallback) * acou_val + (w_cnn / total_fallback) * cnn_val
        logger.info(
            "seg %.1f-%.1fs | acou=%.1f cnn=%.1f w2v2=%s final=%.1f",
            seg.start_time, seg.end_time,
            acou_val, cnn_val,
            f"{w2v2_val:.1f}" if w2v2_val is not None else "N/A",
            final,
        )

        contributors = _merge_contributors(acou_contrib, cnn_contrib, w2v2_val)

        seg_results.append(SegmentResult(
            start_time=seg.start_time,
            end_time=seg.end_time,
            confidence_score=round(float(np.clip(final, 0, 100)), 1),
            contributors=contributors,
        ))

    # ── 2.3 Aggregate output ──────────────────────────────────────────────
    scores = np.array([s.confidence_score for s in seg_results], dtype=np.float64)
    overall = float(np.clip(scores.mean(), 0, 100))

    # 95 % Wald confidence interval on the mean, with a minimum half-width
    n = len(scores)
    sem = float(scores.std(ddof=0) / np.sqrt(n)) if n > 1 else MIN_CI_HALF_WIDTH
    half_width = max(1.96 * sem, MIN_CI_HALF_WIDTH)

    ci_low = round(float(np.clip(overall - half_width, 0, 100)), 1)
    ci_high = round(float(np.clip(overall + half_width, 0, 100)), 1)

    verdict = "Likely AI-Generated" if overall >= VERDICT_THRESHOLD else "Likely Authentic"
    summary = _plain_english_summary(seg_results, overall, model_name)

    return DetectionResult(
        overall_score=round(overall, 1),
        verdict=verdict,
        confidence_low=ci_low,
        confidence_high=ci_high,
        segments=seg_results,
        summary=summary,
        model_used=model_name,
    )
