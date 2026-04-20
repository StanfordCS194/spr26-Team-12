"""
Feature 4 — Politician Identity Matching.

Wraps SpeechBrain's ECAPA-TDNN speaker encoder (Apache-2.0, 192-d
embeddings, trained on VoxCeleb 1+2). Cosine similarity against a
centroid embedding stored in SQLite.

Decision bands (after mapping cosine [-1, 1] -> [0, 100] via (s+1)*50):
    >= 75   "Strong match"
    45-75   "Possible match"
    <  45   "Does not match reference model"

We never present similarity in isolation. Combined with Feature 2's
overall_score, the frontend renders the verdict matrix from the plan.
"""

from __future__ import annotations

import os
from threading import Lock

import numpy as np
import soundfile as sf
import torch
import torchaudio

from models import SpeakerMatch
from database import get_speaker

_MODEL_DIR = os.path.join(os.path.dirname(__file__), "pretrained_models", "spkrec-ecapa-voxceleb")
_TARGET_SR = 16000
_MIN_SECONDS = 1.5  # R12: reject very short clips (ECAPA EER doubles below ~3s; 1.5s is a hard floor)

_encoder = None
_encoder_lock = Lock()


def load_encoder():
    """Lazy singleton ECAPA-TDNN encoder."""
    global _encoder
    if _encoder is not None:
        return _encoder
    with _encoder_lock:
        if _encoder is not None:
            return _encoder
        from speechbrain.inference.speaker import EncoderClassifier
        _encoder = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=_MODEL_DIR,
            run_opts={"device": "cpu"},
        )
    return _encoder


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    if norm < 1e-12:
        return v
    return v / norm


def _load_mono_16k(path: str) -> torch.Tensor:
    """Load any audio file as 1-channel 16 kHz float tensor (C, T)."""
    data, sr = sf.read(path, dtype="float32", always_2d=True)  # (T, C)
    sig = torch.from_numpy(data.T).contiguous()  # (C, T)
    if sig.shape[0] > 1:
        sig = sig.mean(dim=0, keepdim=True)
    if sr != _TARGET_SR:
        sig = torchaudio.functional.resample(sig, sr, _TARGET_SR)
    return sig


def embed_audio(path: str) -> np.ndarray:
    """Returns L2-normalized float32[192] embedding for the whole clip."""
    sig = _load_mono_16k(path)
    duration = sig.shape[1] / _TARGET_SR
    if duration < _MIN_SECONDS:
        raise ValueError(
            f"Audio too short for reliable speaker matching "
            f"({duration:.1f}s; need >= {_MIN_SECONDS}s)"
        )
    enc = load_encoder()
    with torch.no_grad():
        emb = enc.encode_batch(sig).squeeze().cpu().numpy().astype(np.float32)
    return _l2_normalize(emb)


def embed_to_bytes(emb: np.ndarray) -> bytes:
    return emb.astype(np.float32).tobytes()


def bytes_to_embed(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


# ── Decision bands ───────────────────────────────────────────────

STRONG_THRESHOLD = 75.0
POSSIBLE_THRESHOLD = 45.0


def _band(score: float) -> str:
    if score >= STRONG_THRESHOLD:
        return "Strong"
    if score >= POSSIBLE_THRESHOLD:
        return "Possible"
    return "No"


_INTERPRETATIONS = {
    "Strong":   "Strong acoustic match to the reference voice model for {name} (similarity {score:.1f}%). Combine with the AI-probability score for a verdict.",
    "Possible": "Partial match to the reference voice model for {name} (similarity {score:.1f}%). Could be a low-quality recording of the speaker, or a different speaker; combine with the AI-probability score before drawing conclusions.",
    "No":       "Voice does not match the reference model for {name} (similarity {score:.1f}%). Either the clip is of a different speaker, or it is a synthetic impersonation that did not preserve voice identity.",
}


def compare(audio_path: str, speaker_id: str) -> SpeakerMatch:
    """Embed probe, compare to stored centroid, return a SpeakerMatch."""
    speaker = get_speaker(speaker_id)
    if speaker is None:
        raise ValueError(f"Unknown speaker_id: {speaker_id}")

    ref = bytes_to_embed(speaker["embedding"])
    probe = embed_audio(audio_path)

    cosine = float(np.dot(probe, ref))            # both L2-normalized -> cosine
    cosine = max(-1.0, min(1.0, cosine))
    score = (cosine + 1.0) * 50.0                  # map to [0, 100]
    band = _band(score)

    return SpeakerMatch(
        claimed_speaker=speaker["name"],
        similarity_score=score,
        interpretation=_INTERPRETATIONS[band].format(name=speaker["name"], score=score),
    )


def warmup():
    """Pre-load the encoder so the first request isn't slow."""
    load_encoder()
