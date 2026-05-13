"""Resolve a real product hero image (og:image / twitter:image) for a URL.

Strategy:
- For each product page URL, do one lightweight HTTP GET with a browser-like
  User-Agent and short timeout.
- Parse Open Graph / Twitter Card meta tags from the HTML head with a
  regex (no extra dependencies).
- Persist results to a small JSON cache so we only fetch each URL once
  per process / restart cycle.
- Return the original placeholder URL if anything fails — the frontend
  also has an onError fallback to a brand-initial backdrop, so broken
  images never break the layout.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Optional
from urllib.parse import urljoin

import httpx

from .. import config

_CACHE_PATH = config.DATA_DIR / "product_image_cache.json"
_CACHE_LOCK = threading.Lock()
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_META_PATTERNS = [
    re.compile(
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
]


def _load_cache() -> dict:
    if not _CACHE_PATH.exists():
        return {}
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=2, sort_keys=True)
    except OSError:
        pass


def _extract_image(html: str, base_url: str) -> Optional[str]:
    head = html[:60000]  # only scan the head/early body
    for pattern in _META_PATTERNS:
        match = pattern.search(head)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return urljoin(base_url, candidate)
    return None


def resolve_image(url: str, *, fallback: str = "") -> str:
    """Return a real product image URL when one can be discovered, else fallback.

    Cached per-URL across calls (and across server restarts via JSON file).
    """
    if not url:
        return fallback
    with _CACHE_LOCK:
        cache = _load_cache()
        cached = cache.get(url)
        if isinstance(cached, dict) and "image" in cached:
            return cached.get("image") or fallback

    image: Optional[str] = None
    try:
        with httpx.Client(
            timeout=6.0,
            follow_redirects=True,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
        ) as client:
            response = client.get(url)
            if response.status_code < 400 and "text/html" in response.headers.get(
                "content-type", ""
            ):
                image = _extract_image(response.text, str(response.url))
    except Exception:
        image = None

    with _CACHE_LOCK:
        cache = _load_cache()
        cache[url] = {"image": image or ""}
        _save_cache(cache)

    return image or fallback
