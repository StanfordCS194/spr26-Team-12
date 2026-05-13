"""Audio transcription helpers.

Supports two providers, both speaking OpenAI's /v1/audio/transcriptions
contract:

  - "openai"  -> https://api.openai.com/v1/audio/transcriptions (Whisper-1)
  - "groq"    -> https://api.groq.com/openai/v1/audio/transcriptions
                 (whisper-large-v3, free tier available)

Provider is selected by config.TRANSCRIPTION_PROVIDER, which defaults to
"groq" when GROQ_API_KEY is set, else "openai". This lets us keep the
side-panel live-recording path working with a free Groq key when the team
doesn't have OpenAI credit available.
"""
from __future__ import annotations

import httpx

from .. import config


class TranscriptionUnavailable(RuntimeError):
    pass


def _resolve_provider() -> tuple[str, str, str, str]:
    """Return (provider_name, api_key, url, model) based on current config.

    Falls back to whichever provider actually has a key configured, even if
    the user set TRANSCRIPTION_PROVIDER to the other one.
    """
    provider = (config.TRANSCRIPTION_PROVIDER or "").lower() or "openai"
    if provider == "groq" and not config.GROQ_API_KEY and config.OPENAI_API_KEY:
        provider = "openai"
    elif provider == "openai" and not config.OPENAI_API_KEY and config.GROQ_API_KEY:
        provider = "groq"

    if provider == "groq":
        return (
            "groq",
            config.GROQ_API_KEY,
            "https://api.groq.com/openai/v1/audio/transcriptions",
            config.GROQ_WHISPER_MODEL,
        )
    return (
        "openai",
        config.OPENAI_API_KEY,
        "https://api.openai.com/v1/audio/transcriptions",
        config.OPENAI_WHISPER_MODEL,
    )


async def transcribe_audio(filename: str, content_type: str, data: bytes) -> str:
    provider, api_key, url, model = _resolve_provider()
    if not api_key:
        raise TranscriptionUnavailable(
            "Audio transcription requires GROQ_API_KEY (recommended, free tier) "
            "or OPENAI_API_KEY in backend/.env."
        )
    if not data:
        raise ValueError("Empty audio file.")
    max_bytes = config.MAX_AUDIO_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise ValueError(f"Audio file is too large. Max size is {config.MAX_AUDIO_MB} MB.")

    files = {
        "file": (filename or "audio.mp3", data, content_type or "application/octet-stream"),
    }
    form = {
        "model": model,
        "response_format": "json",
        "temperature": "0",
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=config.TRANSCRIPTION_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers=headers, data=form, files=files)
            response.raise_for_status()
            payload = response.json()
            transcript = str(payload.get("text", "")).strip()
            if not transcript:
                raise TranscriptionUnavailable(
                    f"{provider.capitalize()} transcription returned an empty transcript."
                )
            return transcript
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        raise TranscriptionUnavailable(
            f"{provider.capitalize()} transcription failed: {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise TranscriptionUnavailable(
            f"{provider.capitalize()} transcription request failed: {exc}"
        ) from exc
