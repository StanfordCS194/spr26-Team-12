"""
Offline reference voice index builder.

Reads backend/data/speakers.csv (speaker_id,name,role,sources) where
`sources` is a `|`-separated list of either:
  - local audio paths (anything torchaudio can read), or
  - HTTPS URLs (downloaded via yt-dlp).

For each speaker:
  1. Resolve every source -> 16 kHz mono WAV in the cache dir.
  2. Window the audio into 5-second non-overlapping chunks.
  3. Embed each chunk with ECAPA-TDNN, L2-normalize.
  4. Average -> centroid -> L2-normalize again.
  5. Persist via database.upsert_speaker().

Run:
    venv/bin/python build_speaker_index.py
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
import tempfile

import certifi
import numpy as np
import torch
import torchaudio

from database import init_db, upsert_speaker
from speaker_match import (
    _TARGET_SR, _l2_normalize, _load_mono_16k,
    embed_to_bytes, load_encoder,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CSV_PATH = os.path.join(DATA_DIR, "speakers.csv")
CACHE_DIR = os.path.join(DATA_DIR, "ref_cache")
YTDLP = os.path.join(os.path.dirname(__file__), "venv/bin/yt-dlp")
SSL_ENV = {**os.environ, "SSL_CERT_FILE": certifi.where()}

CHUNK_SECONDS = 5.0
MIN_TOTAL_SECONDS = 3.0  # demo bar; production should be >= 30s


def resolve_source(src: str, dest_dir: str) -> str | None:
    """Return a path to a local audio file for `src`, or None on failure."""
    if os.path.isfile(src):
        return src
    if src.startswith("https://"):
        out = os.path.join(dest_dir, "src.wav")
        try:
            subprocess.run(
                [YTDLP, "-x", "--audio-format", "wav", "-o", out, src],
                env=SSL_ENV, check=True, capture_output=True, timeout=180,
            )
            return out
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"  ! yt-dlp failed for {src}: {e}", file=sys.stderr)
            return None
    print(f"  ! source not found: {src}", file=sys.stderr)
    return None


def chunk_embeddings(path: str, encoder) -> tuple[list[np.ndarray], float]:
    """Return (list_of_192d_embeddings, used_seconds).

    Splits into 5s non-overlapping chunks. If the clip is shorter than the
    window but at least _MIN_SECONDS long, embed the whole clip as one chunk.
    """
    from speaker_match import _MIN_SECONDS
    sig = _load_mono_16k(path)  # (1, T)
    total = sig.shape[1] / _TARGET_SR
    win = int(CHUNK_SECONDS * _TARGET_SR)
    embs: list[np.ndarray] = []
    used = 0.0
    with torch.no_grad():
        if sig.shape[1] >= win:
            for start in range(0, sig.shape[1] - win + 1, win):
                chunk = sig[:, start:start + win]
                e = encoder.encode_batch(chunk).squeeze().cpu().numpy().astype(np.float32)
                embs.append(_l2_normalize(e))
                used += CHUNK_SECONDS
        elif total >= _MIN_SECONDS:
            e = encoder.encode_batch(sig).squeeze().cpu().numpy().astype(np.float32)
            embs.append(_l2_normalize(e))
            used = total
    return embs, used


def build_one(row: dict, encoder) -> bool:
    sid = row["speaker_id"].strip()
    name = row["name"].strip()
    role = row.get("role", "").strip()
    sources = [s.strip() for s in row["sources"].split("|") if s.strip()]
    print(f"\n→ {sid} ({name}) — {len(sources)} source(s)")

    all_embs: list[np.ndarray] = []
    total_sec = 0.0
    used_sources: list[str] = []

    for i, src in enumerate(sources):
        with tempfile.TemporaryDirectory(dir=CACHE_DIR) as tmp:
            local = resolve_source(src, tmp)
            if not local:
                continue
            try:
                embs, secs = chunk_embeddings(local, encoder)
            except Exception as e:
                print(f"  ! embed failed for {src}: {e}", file=sys.stderr)
                continue
            if not embs:
                print(f"  ! source {src} too short for {CHUNK_SECONDS}s window")
                continue
            all_embs.extend(embs)
            total_sec += secs
            used_sources.append(src)
            print(f"  ✓ {src}: {len(embs)} chunks, {secs:.1f}s")

    if total_sec < MIN_TOTAL_SECONDS:
        print(f"  ✗ skipping {sid}: only {total_sec:.1f}s of usable audio "
              f"(need >= {MIN_TOTAL_SECONDS}s)")
        return False

    centroid = _l2_normalize(np.mean(np.stack(all_embs), axis=0))
    upsert_speaker(
        speaker_id=sid,
        name=name,
        role=role,
        embedding=embed_to_bytes(centroid),
        n_clips=len(used_sources),
        duration_sec=total_sec,
        source=" | ".join(used_sources),
    )
    print(f"  ✓ stored centroid from {len(all_embs)} chunks / {total_sec:.1f}s")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=CSV_PATH)
    args = parser.parse_args()

    if not os.path.isfile(args.csv):
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(CACHE_DIR, exist_ok=True)
    init_db()
    encoder = load_encoder()

    ok, fail = 0, 0
    with open(args.csv) as f:
        for row in csv.DictReader(f):
            if build_one(row, encoder):
                ok += 1
            else:
                fail += 1

    print(f"\nDone: {ok} indexed, {fail} skipped.")
    # don't leave partial caches on disk
    shutil.rmtree(CACHE_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
