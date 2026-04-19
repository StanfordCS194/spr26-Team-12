# Veritas — AI Voice Authentication Platform

## Requirements
- Python 3.12+
- Node 18+
- ffmpeg (`brew install ffmpeg`)

## Setup

### Backend
```bash
cd backend
python3 -m venv venv
venv/bin/pip install fastapi uvicorn python-multipart yt-dlp certifi
venv/bin/uvicorn main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173


Source Control with git: Agam Iheanyi-Igwe (agam01)