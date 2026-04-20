"""
Rigorous Feature 4 test suite.

Run with:
    cd backend && venv/bin/python -m pytest tests/ -v -s

Or as a script:
    cd backend && venv/bin/python tests/test_feature_4.py
"""

from __future__ import annotations

import io
import os
import sys
import shutil
import tempfile
import wave

# make backend/ importable when running this file directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pytest

# Use a throw-away SQLite db so we don't touch the dev one.
_TMP_DB_DIR = tempfile.mkdtemp(prefix="veritas_test_")
os.environ["VERITAS_DB"] = os.path.join(_TMP_DB_DIR, "test.db")

import database  # noqa: E402
database.DB_PATH = os.environ["VERITAS_DB"]

import speaker_match  # noqa: E402
from speaker_match import (  # noqa: E402
    embed_audio, embed_to_bytes, bytes_to_embed,
    compare, _band, _l2_normalize,
    STRONG_THRESHOLD, POSSIBLE_THRESHOLD,
)
from database import (  # noqa: E402
    init_db, upsert_speaker, list_speakers, get_speaker,
)

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "samples")
SPK1_A = os.path.join(SAMPLES_DIR, "spk1_snt1.wav")
SPK1_B = os.path.join(SAMPLES_DIR, "spk1_snt2.wav")
SPK2_A = os.path.join(SAMPLES_DIR, "spk2_snt1.wav")
SPK2_B = os.path.join(SAMPLES_DIR, "spk2_snt2.wav")


@pytest.fixture(scope="module", autouse=True)
def _setup():
    init_db()
    yield
    shutil.rmtree(_TMP_DB_DIR, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────
# 1. Embedding contract
# ─────────────────────────────────────────────────────────────────

def test_embedding_shape_and_dtype():
    e = embed_audio(SPK1_A)
    assert e.shape == (192,)
    assert e.dtype == np.float32


def test_embedding_is_l2_normalized():
    e = embed_audio(SPK1_A)
    assert abs(np.linalg.norm(e) - 1.0) < 1e-5


def test_embedding_deterministic():
    e1 = embed_audio(SPK1_A)
    e2 = embed_audio(SPK1_A)
    np.testing.assert_allclose(e1, e2, atol=1e-5)


# ─────────────────────────────────────────────────────────────────
# 2. The whole point: same speaker > different speaker
# ─────────────────────────────────────────────────────────────────

def _cos(a, b):
    return float(np.dot(a, b))


def test_same_speaker_higher_than_different_speaker():
    e1a, e1b = embed_audio(SPK1_A), embed_audio(SPK1_B)
    e2a, e2b = embed_audio(SPK2_A), embed_audio(SPK2_B)

    intra1 = _cos(e1a, e1b)
    intra2 = _cos(e2a, e2b)
    inter  = np.mean([_cos(e1a, e2a), _cos(e1a, e2b),
                      _cos(e1b, e2a), _cos(e1b, e2b)])

    print(f"\nintra-spk1={intra1:.3f}  intra-spk2={intra2:.3f}  inter={inter:.3f}")
    assert intra1 > inter + 0.1, "Same-speaker similarity should beat cross-speaker by a clear margin"
    assert intra2 > inter + 0.1


def test_identical_clip_scores_perfect():
    e1, e2 = embed_audio(SPK1_A), embed_audio(SPK1_A)
    assert _cos(e1, e2) > 0.999


# ─────────────────────────────────────────────────────────────────
# 3. Decision band thresholds
# ─────────────────────────────────────────────────────────────────

def test_band_thresholds():
    assert _band(STRONG_THRESHOLD)       == "Strong"
    assert _band(STRONG_THRESHOLD - 0.01) == "Possible"
    assert _band(POSSIBLE_THRESHOLD)     == "Possible"
    assert _band(POSSIBLE_THRESHOLD - 0.01) == "No"
    assert _band(0.0)                    == "No"
    assert _band(100.0)                  == "Strong"


# ─────────────────────────────────────────────────────────────────
# 4. SQLite round-trip preserves embedding bit-exact
# ─────────────────────────────────────────────────────────────────

def test_db_roundtrip_bit_exact():
    e = embed_audio(SPK1_A)
    upsert_speaker("rt-spk", "Roundtrip", "test", embed_to_bytes(e),
                   n_clips=1, duration_sec=3.0, source="local")
    row = get_speaker("rt-spk")
    assert row is not None
    e2 = bytes_to_embed(row["embedding"])
    np.testing.assert_array_equal(e, e2)


def test_list_speakers_includes_inserted():
    names = {s["speaker_id"] for s in list_speakers()}
    assert "rt-spk" in names


# ─────────────────────────────────────────────────────────────────
# 5. compare() end-to-end against a stored centroid
# ─────────────────────────────────────────────────────────────────

def _seed_speaker(speaker_id, name, *clip_paths):
    """Build a centroid from one or more clips and store it."""
    embs = [embed_audio(p) for p in clip_paths]
    centroid = _l2_normalize(np.mean(np.stack(embs), axis=0))
    upsert_speaker(speaker_id, name, "test", embed_to_bytes(centroid),
                   n_clips=len(clip_paths), duration_sec=3.0 * len(clip_paths),
                   source="local")


def test_compare_strong_match_for_same_speaker():
    _seed_speaker("spk1", "Speaker One", SPK1_A)
    sm = compare(SPK1_B, "spk1")
    print(f"\nstrong-match similarity = {sm.similarity_score:.1f}")
    assert sm.claimed_speaker == "Speaker One"
    assert sm.similarity_score >= STRONG_THRESHOLD, \
        f"Same-speaker should clear Strong band, got {sm.similarity_score:.1f}"
    assert "Strong" in sm.interpretation or "match" in sm.interpretation.lower()


def test_compare_no_match_for_different_speaker():
    _seed_speaker("spk1", "Speaker One", SPK1_A, SPK1_B)
    sm = compare(SPK2_A, "spk1")
    print(f"\nno-match similarity = {sm.similarity_score:.1f}")
    assert sm.similarity_score < STRONG_THRESHOLD, \
        f"Different speaker should NOT hit Strong band, got {sm.similarity_score:.1f}"


def test_compare_unknown_speaker_raises():
    with pytest.raises(ValueError):
        compare(SPK1_A, "this-id-does-not-exist")


# ─────────────────────────────────────────────────────────────────
# 6. R12 — short-clip rejection
# ─────────────────────────────────────────────────────────────────

def _write_silence_wav(path: str, seconds: float, sr: int = 16000):
    n = int(seconds * sr)
    samples = (np.zeros(n, dtype=np.int16)).tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(samples)


def test_short_clip_rejected():
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    try:
        _write_silence_wav(path, 1.0)  # < 2s threshold
        with pytest.raises(ValueError, match="too short"):
            embed_audio(path)
    finally:
        os.unlink(path)


# ─────────────────────────────────────────────────────────────────
# 7. End-to-end via FastAPI TestClient
# ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    # We must import main *after* DB_PATH is patched.
    import main  # noqa: F401
    from fastapi.testclient import TestClient
    return TestClient(main.app)


def _upload_wav(client, path: str) -> str:
    with open(path, "rb") as fh:
        r = client.post(
            "/upload",
            files={"file": (os.path.basename(path), fh, "audio/wav")},
        )
    assert r.status_code == 200, r.text
    return r.json()["file_id"]


def test_api_speakers_endpoint(client):
    # Make sure we have at least one speaker indexed
    _seed_speaker("api-spk1", "API Speaker One", SPK1_A, SPK1_B)
    r = client.get("/speakers")
    assert r.status_code == 200
    ids = {s["speaker_id"] for s in r.json()}
    assert "api-spk1" in ids


def test_api_analyze_with_claimed_speaker_returns_match(client):
    _seed_speaker("api-spk1", "API Speaker One", SPK1_A, SPK1_B)
    file_id = _upload_wav(client, SPK1_A)  # use same clip as reference
    r = client.post(
        f"/analyze/{file_id}",
        json={"claimed_speaker_id": "api-spk1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["speaker_match"] is not None
    sm = body["speaker_match"]
    print(f"\nAPI strong sim = {sm['similarity_score']:.1f}")
    assert sm["similarity_score"] >= STRONG_THRESHOLD
    assert sm["claimed_speaker"] == "API Speaker One"


def test_api_analyze_without_claimed_speaker_omits_match(client):
    file_id = _upload_wav(client, SPK1_A)
    r = client.post(f"/analyze/{file_id}", json={"claimed_speaker_id": None})
    assert r.status_code == 200, r.text
    assert r.json()["speaker_match"] is None


def test_api_analyze_no_body_still_works_back_compat(client):
    """Existing callers that don't send a body must keep working."""
    file_id = _upload_wav(client, SPK1_A)
    r = client.post(f"/analyze/{file_id}")
    assert r.status_code == 200, r.text
    assert r.json()["speaker_match"] is None


def test_api_analyze_wrong_speaker_low_match(client):
    _seed_speaker("api-spk2", "API Speaker Two", SPK2_A, SPK2_B)
    file_id = _upload_wav(client, SPK1_A)  # spk1 audio, but claim spk2
    r = client.post(
        f"/analyze/{file_id}",
        json={"claimed_speaker_id": "api-spk2"},
    )
    assert r.status_code == 200
    sm = r.json()["speaker_match"]
    print(f"\nAPI wrong-speaker sim = {sm['similarity_score']:.1f}")
    assert sm["similarity_score"] < STRONG_THRESHOLD


def test_api_analyze_unknown_speaker_id_404(client):
    file_id = _upload_wav(client, SPK1_A)
    r = client.post(
        f"/analyze/{file_id}",
        json={"claimed_speaker_id": "no-such-speaker"},
    )
    assert r.status_code == 404


def test_api_short_clip_returns_400(client):
    """R12: very short clips must be rejected with a clear error."""
    _seed_speaker("api-spk1", "API Speaker One", SPK1_A)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        short_path = f.name
    try:
        _write_silence_wav(short_path, 1.0)
        with open(short_path, "rb") as fh:
            up = client.post("/upload",
                             files={"file": ("short.wav", fh, "audio/wav")})
        file_id = up.json()["file_id"]
        r = client.post(
            f"/analyze/{file_id}",
            json={"claimed_speaker_id": "api-spk1"},
        )
        assert r.status_code == 400
        assert "too short" in r.json()["detail"].lower()
    finally:
        os.unlink(short_path)


# ─────────────────────────────────────────────────────────────────
# 8. Report integration — Feature 4 must flow through to the PDF
# ─────────────────────────────────────────────────────────────────

def test_report_includes_speaker_match(client):
    _seed_speaker("api-spk1", "API Speaker One", SPK1_A, SPK1_B)
    file_id = _upload_wav(client, SPK1_A)
    a = client.post(f"/analyze/{file_id}",
                    json={"claimed_speaker_id": "api-spk1"}).json()
    r = client.post("/reports", json={"analysis_id": a["analysis_id"]})
    assert r.status_code == 200
    rep = r.json()
    pdf = client.get(rep["pdf_url"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:4] == b"%PDF"
    assert len(pdf.content) > 1000


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
