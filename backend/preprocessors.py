"""Input pre-processors. Each converges to a clean text string."""
from __future__ import annotations

import io
import re
from typing import Optional, Tuple

from . import config


def process_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Empty input.")
    if len(text) > config.MAX_INPUT_CHARS:
        text = text[: config.MAX_INPUT_CHARS]
    return text


_URL_RE = re.compile(r"^https?://", re.I)


def detect_platform(url: str) -> str:
    u = url.lower()
    if "reddit.com" in u:
        return "reddit"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "tiktok.com" in u:
        return "tiktok"
    return "article"


async def process_url(url: str) -> Tuple[str, str]:
    """Return (text, platform).

    - article: scrape via trafilatura.
    - youtube/tiktok/reddit: download audio with yt-dlp, transcribe via OpenAI Whisper.
    Falls back to a stub string only if every path fails so the UI still progresses.
    """
    if not _URL_RE.match(url or ""):
        raise ValueError("Not a valid URL.")
    platform = detect_platform(url)
    text: Optional[str] = None

    if platform == "article":
        try:
            import trafilatura  # type: ignore

            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                text = trafilatura.extract(downloaded) or None
        except Exception:
            text = None
    elif platform == "youtube" and config.SERPAPI_API_KEY:
        # Use SerpAPI text transcript — faster and doesn't hit yt-dlp bot blocks.
        try:
            import httpx
            video_id_match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
            if not video_id_match:
                raise ValueError("Could not extract YouTube video ID from URL.")
            video_id = video_id_match.group(1)
            params = {
                "engine": "youtube_video_transcript",
                "v": video_id,
                "lang": "en",
                "api_key": config.SERPAPI_API_KEY,
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get("https://serpapi.com/search.json", params=params)
            if res.status_code == 200:
                segments = res.json().get("transcript", [])
                text = " ".join(s.get("snippet", "") for s in segments if s.get("snippet", "").strip()) or None
        except Exception:
            text = None
        # Fall back to yt-dlp if SerpAPI returned nothing.
        if not text:
            try:
                import asyncio
                from .pipeline import youtube_audio, transcriber
                max_bytes = config.MAX_AUDIO_MB * 1024 * 1024
                data, filename, mime = await asyncio.to_thread(youtube_audio.download_audio, url, max_bytes)
                text = await transcriber.transcribe_audio(filename, mime, data)
            except Exception as exc:
                raise ValueError(f"Could not transcribe youtube link: {exc}")
    else:
        # video / social platforms — fetch audio and transcribe.
        try:
            import asyncio

            from .pipeline import youtube_audio
            from .pipeline import transcriber

            max_bytes = config.MAX_AUDIO_MB * 1024 * 1024
            data, filename, mime = await asyncio.to_thread(
                youtube_audio.download_audio, url, max_bytes
            )
            text = await transcriber.transcribe_audio(filename, mime, data)
        except Exception as exc:
            # Surface the real error to the API caller so users know why.
            raise ValueError(f"Could not transcribe {platform} link: {exc}")

    if not text:
        text = f"Claim from {platform} link: {url}"
    return text[: config.MAX_INPUT_CHARS], platform


def process_screenshot(image_bytes: bytes) -> str:
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore

        img = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(img)
        text = (text or "").strip()
        if text:
            return text[: config.MAX_INPUT_CHARS]
    except Exception:
        pass
    # graceful fallback (OCR not installed or failed)
    return "Screenshot uploaded — OCR unavailable in this environment. Please paste claim text."
