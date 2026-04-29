"""Credit-based AI provider helpers.

This replaces the old local Ollama path. The MVP uses raw HTTP calls instead
of SDKs so setup stays light: users only need API keys in env vars.
"""
from __future__ import annotations

import json
from typing import Optional

import httpx

from .. import config


async def generate_text(
    prompt: str,
    *,
    provider: Optional[str] = None,
    system: str = "Return concise, source-grounded fitness fact-checking output.",
    json_mode: bool = False,
    temperature: float = 0.2,
    timeout: float = 60.0,
) -> Optional[str]:
    selected = (provider or config.PRIMARY_LLM_PROVIDER).lower()
    if selected == "openai":
        return await _openai_chat(
            prompt,
            system=system,
            json_mode=json_mode,
            temperature=temperature,
            timeout=timeout,
        )
    if selected == "groq":
        return await _groq_chat(
            prompt,
            system=system,
            json_mode=json_mode,
            temperature=temperature,
            timeout=timeout,
        )
    return None


async def _openai_chat(
    prompt: str,
    *,
    system: str,
    json_mode: bool,
    temperature: float,
    timeout: float,
) -> Optional[str]:
    if not config.OPENAI_API_KEY:
        return None
    payload = {
        "model": config.OPENAI_TEXT_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip() or None
    except Exception:
        return None


async def _groq_chat(
    prompt: str,
    *,
    system: str,
    json_mode: bool,
    temperature: float,
    timeout: float,
) -> Optional[str]:
    if not config.GROQ_API_KEY:
        return None
    payload = {
        "model": config.GROQ_TEXT_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {config.GROQ_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip() or None
    except Exception:
        return None


def parse_json_loose(text: str) -> Optional[dict]:
    """Parse JSON, tolerating prose wrapped around the first object block."""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None
