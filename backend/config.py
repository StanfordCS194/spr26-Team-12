"""Runtime configuration.

Defaults keep the demo path working with no API keys, but live MVP work now
uses credit-based providers instead of a local Ollama model.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent


def _load_dotenv() -> None:
	# Check backend/.env first, then project root .env
	env_path = BASE_DIR / ".env"
	if not env_path.exists():
		env_path = PROJECT_DIR / ".env"
	if not env_path.exists():
		return
	for raw_line in env_path.read_text(encoding="utf-8").splitlines():
		line = raw_line.strip()
		if not line or line.startswith("#") or "=" not in line:
			continue
		key, value = line.split("=", 1)
		key = key.strip()
		value = value.strip().strip('"').strip("'")
		os.environ.setdefault(key, value)


_load_dotenv()

# When true, /extract and /verdict serve cached showcase responses and graceful
# fallback panels. Set false only when provider API keys are configured.
DEMO_MODE: bool = os.getenv("DEMO_MODE", "true").lower() in ("1", "true", "yes")

# Public Vite/React URL (e.g. Vercel). Returned in /api/health for the Chrome extension "Open full app".
# Default matches the team's Vercel production domain; override with PUBLIC_WEB_APP_URL in .env / Render.
_pub_web = (os.getenv("PUBLIC_WEB_APP_URL") or "").strip().rstrip("/")
PUBLIC_WEB_APP_URL: str = _pub_web or "https://veritas-ruby.vercel.app"

# Credit-based model providers.
PRIMARY_LLM_PROVIDER: str = os.getenv("PRIMARY_LLM_PROVIDER", "openai").lower()
SECONDARY_LLM_PROVIDER: str = os.getenv("SECONDARY_LLM_PROVIDER", "openai").lower()
SEARCH_PROVIDER: str = os.getenv("SEARCH_PROVIDER", "tavily").lower()

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_TEXT_MODEL: str = os.getenv("OPENAI_TEXT_MODEL", "gpt-4o-mini")
OPENAI_WHISPER_MODEL: str = os.getenv("OPENAI_WHISPER_MODEL", "whisper-1")

# Groq: free-tier-friendly OpenAI-compatible API with Whisper-large-v3 for
# audio transcription. If GROQ_API_KEY is set, the transcriber will prefer
# Groq over OpenAI unless TRANSCRIPTION_PROVIDER overrides it.
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_WHISPER_MODEL: str = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")
TRANSCRIPTION_PROVIDER: str = os.getenv(
	"TRANSCRIPTION_PROVIDER",
	"groq" if os.getenv("GROQ_API_KEY") else "openai",
).lower()

TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
BRAVE_SEARCH_API_KEY: str = os.getenv("BRAVE_SEARCH_API_KEY", "")

# Active prompt versions.
EXTRACT_PROMPT: str = os.getenv("EXTRACT_PROMPT", "extract_v1.txt")
VERDICT_PROMPT: str = os.getenv("VERDICT_PROMPT", "verdict_v1.txt")

PROMPTS_DIR = BASE_DIR / "prompts"
DATA_DIR = BASE_DIR / "data"
CORPUS_DIR = DATA_DIR / "corpus"
CACHED_VERDICTS_PATH = DATA_DIR / "cached_verdicts.json"

MAX_INPUT_CHARS = 2000
MAX_AUDIO_MB = int(os.getenv("MAX_AUDIO_MB", "25"))
TRANSCRIPTION_TIMEOUT_SECONDS = float(os.getenv("TRANSCRIPTION_TIMEOUT_SECONDS", "120"))

# Optional shared secret. If set, /api/clip-report and influencer mutations
# require the X-API-Key header to match. If unset (default), endpoints stay
# open so the deployed demo keeps working without secret rotation.
API_KEY: str = os.getenv("VERITAS_API_KEY", "")

# Comma-separated list of allowed CORS origins. "*" (default) keeps the
# extension and any deploy preview working. Set to e.g.
# "https://veritas-ruby.vercel.app,chrome-extension://<id>" in prod.
CORS_ALLOW_ORIGINS = [
	o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()
] or ["*"]
