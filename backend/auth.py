"""Optional shared-secret auth dependency for mutating endpoints.

When ``config.API_KEY`` is empty (the default for the public demo), the
dependency is a no-op so the deployed frontend keeps working without
secret rotation. When the env var is set, the ``X-API-Key`` header must
match or the request is rejected with 401.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException

from . import config


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if not config.API_KEY:
        return
    if not x_api_key or x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="missing or invalid API key")
