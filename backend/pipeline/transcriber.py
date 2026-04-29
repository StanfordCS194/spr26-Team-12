"""Audio transcription helpers for the Feature 1 MVP."""
from __future__ import annotations

import httpx

from .. import config


class TranscriptionUnavailable(RuntimeError):
    pass


async def transcribe_audio(filename: str, content_type: str, data: bytes) -> str:
    if not config.GROQ_API_KEY:
        raise TranscriptionUnavailable("GROQ_API_KEY is required for audio transcription.")
    if not data:
        raise ValueError("Empty audio file.")
    max_bytes = config.MAX_AUDIO_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise ValueError(f"Audio file is too large. Max size is {config.MAX_AUDIO_MB} MB.")

    files = {
        "file": (filename or "audio.mp3", data, content_type or "application/octet-stream"),
    }
    form = {
        "model": config.GROQ_TRANSCRIPTION_MODEL,
        "response_format": "json",
        "temperature": "0",
    }
    headers = {"Authorization": f"Bearer {config.GROQ_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=config.TRANSCRIPTION_TIMEOUT_SECONDS) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers=headers,
                data=form,
                files=files,
            )
            response.raise_for_status()
            payload = response.json()
            transcript = str(payload.get("text", "")).strip()
            if not transcript:
                raise TranscriptionUnavailable("Groq returned an empty transcript.")
            return transcript
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        raise TranscriptionUnavailable(f"Groq transcription failed: {detail}") from exc
    except httpx.HTTPError as exc:
        raise TranscriptionUnavailable(f"Groq transcription request failed: {exc}") from exc
