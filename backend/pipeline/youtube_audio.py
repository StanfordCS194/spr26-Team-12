"""Download audio from YouTube/TikTok/Reddit links via yt-dlp.

Returns the raw bytes plus a sensible filename + content-type so the
OpenAI Whisper transcription path can consume it without any ffmpeg
postprocessing (we deliberately avoid re-encoding so the server does
not need ffmpeg installed).
"""
from __future__ import annotations

import os
import tempfile
from typing import Tuple


class YouTubeDownloadError(RuntimeError):
    pass


# Map common audio container extensions to content-types for the transcription API.
_MIME_BY_EXT = {
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "mp3": "audio/mpeg",
    "webm": "audio/webm",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "wav": "audio/wav",
    "aac": "audio/aac",
}


def download_audio(url: str, max_bytes: int) -> Tuple[bytes, str, str]:
    """Return (data, filename, content_type) for the audio track of *url*.

    Picks the smallest reasonable audio-only stream (prefers m4a, falls
    back to anything yt-dlp can fetch as a single file) so we don't need
    ffmpeg to merge separate video+audio streams.
    """
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise YouTubeDownloadError(
            "yt-dlp is not installed; cannot fetch audio from video links."
        ) from exc

    with tempfile.TemporaryDirectory(prefix="ytdl_") as tmpdir:
        outtmpl = os.path.join(tmpdir, "audio.%(ext)s")
        base_opts = {
            # prefer a single audio-only file in m4a; fall back to the
            # smallest audio-only stream; final fallback is the smallest
            # progressive (audio+video) file so we don't need ffmpeg to
            # demux.
            "format": "bestaudio[ext=m4a]/bestaudio[acodec!=none]/worstaudio/worst",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "restrictfilenames": True,
            "retries": 2,
            "socket_timeout": 30,
            # do NOT call ffmpeg postprocessors; we only have the raw stream.
        }

        # YouTube frequently 403s the default web client; rotate through
        # known-working player clients. Other extractors ignore this arg.
        client_attempts = [
            {"youtube": {"player_client": ["android"]}},
            {"youtube": {"player_client": ["ios"]}},
            {"youtube": {"player_client": ["tv"]}},
            {},  # default — needed for non-YouTube extractors
        ]

        info = None
        last_err: Exception | None = None
        for extractor_args in client_attempts:
            opts = dict(base_opts)
            if extractor_args:
                opts["extractor_args"] = extractor_args
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                if os.listdir(tmpdir):
                    last_err = None
                    break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                # clean any partial files before retrying
                for f in os.listdir(tmpdir):
                    try:
                        os.remove(os.path.join(tmpdir, f))
                    except OSError:
                        pass
                continue
        if last_err is not None and not os.listdir(tmpdir):
            raise YouTubeDownloadError(f"yt-dlp failed: {last_err}") from last_err

        # locate the downloaded file
        files = sorted(os.listdir(tmpdir))
        if not files:
            raise YouTubeDownloadError("yt-dlp produced no output file.")
        # If multiple, pick the largest (the actual media file)
        downloaded = max(
            (os.path.join(tmpdir, f) for f in files),
            key=lambda p: os.path.getsize(p),
        )
        size = os.path.getsize(downloaded)
        if size <= 0:
            raise YouTubeDownloadError("Downloaded audio file is empty.")
        if size > max_bytes:
            mb = max_bytes / (1024 * 1024)
            raise YouTubeDownloadError(
                f"Video audio is too large ({size / (1024*1024):.1f} MB); "
                f"limit is {mb:.0f} MB. Try a shorter clip."
            )

        ext = os.path.splitext(downloaded)[1].lstrip(".").lower() or "m4a"
        mime = _MIME_BY_EXT.get(ext, "application/octet-stream")
        title = ""
        if isinstance(info, dict):
            title = str(info.get("title") or "").strip()
        safe_title = "".join(c for c in title if c.isalnum() or c in ("-", "_")) or "video"
        filename = f"{safe_title[:60]}.{ext}"

        with open(downloaded, "rb") as fh:
            data = fh.read()

    return data, filename, mime
