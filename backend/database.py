import json
import os
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "veritas.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS analyses (
            analysis_id TEXT PRIMARY KEY,
            file_id     TEXT NOT NULL,
            filename    TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reports (
            report_id   TEXT PRIMARY KEY,
            analysis_id TEXT NOT NULL,
            file_id     TEXT NOT NULL,
            filename    TEXT NOT NULL,
            pdf_path    TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            FOREIGN KEY (analysis_id) REFERENCES analyses(analysis_id)
        );
        CREATE TABLE IF NOT EXISTS speakers (
            speaker_id   TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            role         TEXT,
            embedding    BLOB NOT NULL,
            n_clips      INTEGER NOT NULL,
            duration_sec REAL NOT NULL,
            source       TEXT,
            created_at   TEXT NOT NULL
        );
    """)
    conn.close()


# ── Feature 4: speaker reference index ───────────────────────────


def list_speakers() -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT speaker_id, name, role FROM speakers ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_speaker(speaker_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM speakers WHERE speaker_id = ?", (speaker_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_speaker(
    speaker_id: str,
    name: str,
    role: str,
    embedding: bytes,
    n_clips: int,
    duration_sec: float,
    source: str,
):
    conn = _conn()
    conn.execute(
        "INSERT OR REPLACE INTO speakers "
        "(speaker_id, name, role, embedding, n_clips, duration_sec, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            speaker_id, name, role, embedding,
            n_clips, duration_sec, source,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def save_analysis(analysis_id: str, file_id: str, filename: str, result: dict):
    conn = _conn()
    conn.execute(
        "INSERT INTO analyses (analysis_id, file_id, filename, result_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (analysis_id, file_id, filename, json.dumps(result), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_analysis(analysis_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM analyses WHERE analysis_id = ?", (analysis_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    data["result"] = json.loads(data["result_json"])
    return data


def save_report(report_id: str, analysis_id: str, file_id: str, filename: str, pdf_path: str):
    now = datetime.utcnow()
    expires = now + timedelta(days=30)
    conn = _conn()
    conn.execute(
        "INSERT INTO reports (report_id, analysis_id, file_id, filename, pdf_path, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (report_id, analysis_id, file_id, filename, pdf_path, now.isoformat(), expires.isoformat()),
    )
    conn.commit()
    conn.close()


def get_report(report_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM reports WHERE report_id = ?", (report_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    report = dict(row)
    if datetime.fromisoformat(report["expires_at"]) < datetime.utcnow():
        return None
    return report
