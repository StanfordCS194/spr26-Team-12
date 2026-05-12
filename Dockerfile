# Veritas backend — runs on Render's Docker runtime.
#
# Includes ffmpeg so yt-dlp / audio preprocessing works.
# Render injects $PORT at runtime; we bind uvicorn to it.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps for audio extraction + transcription preprocessing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for layer caching.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r backend/requirements.txt

# Now copy the application code.
COPY backend/ ./backend/

# Render sets $PORT at runtime (typically 10000); default to 8000 for local docker test.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
