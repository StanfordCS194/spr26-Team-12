"""
Feature: Transcript Fact-Check
Transcribes audio with Whisper, then checks factual consistency of claims
against public record using Gemini 2.0 Flash with Google Search grounding.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.request

import certifi

logger = logging.getLogger(__name__)

# ── Whisper (lazy load) ───────────────────────────────────────────────────────

_WHISPER_MODEL = None


def _get_whisper():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    try:
        import whisper

        # Fix SSL for model download on macOS
        ctx = ssl.create_default_context(cafile=certifi.where())
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx)
        )
        urllib.request.install_opener(opener)

        logger.info("Loading Whisper small model...")
        _WHISPER_MODEL = whisper.load_model("small")
        logger.info("Whisper model loaded")
    except Exception as exc:
        logger.warning("Whisper unavailable: %s", exc)
        _WHISPER_MODEL = None
    return _WHISPER_MODEL


# ── Groq (lazy load) ─────────────────────────────────────────────────────────

_GROQ_CLIENT = None


def _get_groq():
    global _GROQ_CLIENT
    if _GROQ_CLIENT is not None:
        return _GROQ_CLIENT
    try:
        from groq import Groq

        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            logger.warning("GROQ_API_KEY not set — fact-check disabled")
            return None
        _GROQ_CLIENT = Groq(api_key=api_key)
        logger.info("Groq client configured")
    except Exception as exc:
        logger.warning("Groq unavailable: %s", exc)
        _GROQ_CLIENT = None
    return _GROQ_CLIENT


# ── Public API ────────────────────────────────────────────────────────────────

def transcribe(audio_path: str) -> str | None:
    """Transcribe audio file using Whisper. Returns transcript or None."""
    model = _get_whisper()
    if model is None:
        return None
    try:
        result = model.transcribe(audio_path, language="en")
        transcript = result["text"].strip()
        logger.info("Transcribed %d chars", len(transcript))
        return transcript
    except Exception as exc:
        logger.warning("Transcription failed: %s", exc)
        return None


def fact_check(transcript: str, claimed_speaker: str | None = None, claimed_date: str | None = None) -> dict | None:
    """
    Send transcript to Groq (Llama 3.3 70B) for fact-checking.
    Returns a dict matching the FactCheck model, or None on failure.
    """
    client = _get_groq()
    if client is None:
        return None
    if not transcript or len(transcript.strip()) < 20:
        return None

    speaker_part = f"The speaker is {claimed_speaker}" if claimed_speaker else "The speaker is unidentified"
    date_part = f", speaking on or around {claimed_date}" if claimed_date else ""
    speaker_context = speaker_part + date_part + "."

    prompt = f"""You are a political fact-checker analyzing an audio transcript.

{speaker_context}

Transcript:
\"\"\"{transcript}\"\"\"

Instructions:
1. Identify up to 5 specific factual claims in this transcript.
2. For each claim, verify it against your knowledge of public record.
3. Return ONLY valid JSON in this exact format:

{{
  "claims": [
    {{
      "claim": "exact quote or close paraphrase of the claim",
      "verdict": "Verified" | "False" | "Misleading" | "Unverifiable",
      "explanation": "1-2 sentence explanation with evidence",
      "sources": ["source name or URL"]
    }}
  ],
  "consistency_score": <0-100, how consistent overall with public record>,
  "summary": "2-3 sentence plain English summary of findings"
}}

If the transcript contains no verifiable factual claims (e.g. it is music or noise), return:
{{"claims": [], "consistency_score": 50, "summary": "No verifiable factual claims found in transcript."}}
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        text = response.choices[0].message.content.strip()
        data = json.loads(text)
        data["transcript"] = transcript
        data["claimed_speaker"] = claimed_speaker
        return data
    except Exception as exc:
        logger.warning("Fact-check failed: %s", exc)
        return None
