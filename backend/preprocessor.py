"""
Feature 2.1 — Audio Preprocessing

Loads an audio file, normalises it, removes silence, and chops it into
3-second non-overlapping windows ready for the detection engine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import librosa
import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000       # Hz — matches wav2vec2 / whisper input requirement
SEGMENT_SEC = 3.0          # window length in seconds
SILENCE_TOP_DB = 25        # trim frames quieter than this many dB below peak
MIN_SEGMENT_RATIO = 0.25   # drop final chunk if shorter than this fraction of SEGMENT_SEC


@dataclass(frozen=True)
class Segment:
    start_time: float     # seconds from the trimmed audio start
    end_time: float
    audio: np.ndarray     # float32 waveform at SAMPLE_RATE
    sample_rate: int


def load_and_preprocess(audio_path: str) -> tuple[np.ndarray, int]:
    """
    Load audio from *any* supported format, convert to mono 16 kHz,
    RMS-normalise, and trim leading/trailing silence.

    Returns (y_float32, sample_rate).
    """
    y, sr = librosa.load(audio_path, sr=SAMPLE_RATE, mono=True, dtype=np.float32)

    # RMS normalisation — keeps relative amplitude while standardising level
    rms = float(np.sqrt(np.mean(y ** 2)))
    if rms > 1e-7:
        y = y / rms * 0.1          # target RMS of 0.1

    # Trim leading/trailing silence
    y, _ = librosa.effects.trim(y, top_db=SILENCE_TOP_DB)

    if len(y) == 0:
        raise ValueError("Audio is silent after trimming; nothing to analyse.")

    logger.debug("Loaded %.2f s of audio from %s", len(y) / sr, audio_path)
    return y, sr


def segment_audio(y: np.ndarray, sr: int, seg_sec: float = SEGMENT_SEC) -> list[Segment]:
    """
    Split *y* into non-overlapping windows of *seg_sec* seconds.

    Generates a mel-spectrogram per segment for spectrogram-based features.
    The final chunk is included only if it is ≥ MIN_SEGMENT_RATIO × seg_sec long;
    if shorter, it is zero-padded to a full window.
    """
    seg_len = int(sr * seg_sec)
    min_len = int(seg_len * MIN_SEGMENT_RATIO)
    segments: list[Segment] = []

    for i, offset in enumerate(range(0, len(y), seg_len)):
        chunk = y[offset : offset + seg_len]
        if len(chunk) < min_len:
            logger.debug("Skipping short tail segment (%d samples)", len(chunk))
            continue
        if len(chunk) < seg_len:
            chunk = np.pad(chunk, (0, seg_len - len(chunk)), mode="constant")

        start_t = offset / sr
        end_t = min(offset / sr + seg_sec, len(y) / sr)
        segments.append(Segment(
            start_time=round(start_t, 2),
            end_time=round(end_t, 2),
            audio=chunk,
            sample_rate=sr,
        ))

    if not segments:
        raise ValueError("Audio too short to produce even one analysis segment.")

    logger.debug("Segmented into %d × %.0f s windows", len(segments), seg_sec)
    return segments
