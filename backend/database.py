"""
Storage layer — primary: Supabase (Postgres), fallback: local SQLite.

On startup, init_db() reads SUPABASE_URL / SUPABASE_KEY from the environment
(populated from backend/.env via python-dotenv in main.py) and tries to reach
the cloud database.  If the env vars are absent, or the tables haven't been
created yet, it falls back to local SQLite with a clear log message.

To enable Supabase:
  1. Run backend/setup_supabase.sql once in the Supabase SQL Editor.
  2. Ensure backend/.env contains SUPABASE_URL and SUPABASE_KEY.
  3. Start the server — logs will confirm which backend is active.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ─── Supabase (optional, primary) ────────────────────────────────────────────

_supa = None        # supabase.Client instance
_supa_ok = False    # True once we've confirmed the tables exist


def _parse_dt(s: str) -> datetime:
    """
    Parse any ISO-8601 string — with or without timezone suffix — into a
    naive UTC datetime for expiry comparisons.
    """
    s = s.rstrip("Z")
    # strip +HH:MM or -HH:MM timezone offset
    for sep in ("+", "-"):
        idx = s.rfind(sep, 10)   # skip the date part's minus sign
        if idx != -1:
            s = s[:idx]
            break
    return datetime.fromisoformat(s)


def _init_supabase() -> None:
    global _supa, _supa_ok
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()

    if not url or not key:
        logger.info("SUPABASE_URL / SUPABASE_KEY not set — using local SQLite only")
        return

    try:
        from supabase import create_client   # lazy import so app starts without it
        _supa = create_client(url, key)

        # Probe: an empty SELECT confirms the table exists
        _supa.table("analyses").select("analysis_id").limit(0).execute()

        _supa_ok = True
        logger.info(
            "✅  Supabase connected (%s) — analyses and reports persist to cloud DB", url
        )
    except Exception as exc:
        logger.warning(
            "Supabase unavailable (%s).\n"
            "  → If tables are missing, run backend/setup_supabase.sql in the\n"
            "    Supabase SQL Editor (Dashboard → SQL Editor → New Query).\n"
            "  → Falling back to local SQLite for this session.",
            exc,
        )
        _supa = None
        _supa_ok = False


# ─── SQLite fallback ──────────────────────────────────────────────────────────

_DB_PATH = os.path.join(os.path.dirname(__file__), "veritas.db")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _create_sqlite_tables() -> None:
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
    conn.commit()
    conn.close()


# ─── Public API ───────────────────────────────────────────────────────────────

def init_db() -> None:
    """Initialise storage.  Call once at application startup."""
    _init_supabase()
    _create_sqlite_tables()   # always available as a fallback


# ── Feature 4: speaker reference index (SQLite-only) ──────────────────────────


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


def save_analysis(
    analysis_id: str, file_id: str, filename: str, result: dict
) -> None:
    now = datetime.utcnow().isoformat()

    if _supa_ok:
        try:
            _supa.table("analyses").insert({
                "analysis_id": analysis_id,
                "file_id":     file_id,
                "filename":    filename,
                "result_json": result,    # supabase-py serialises dicts → JSONB
                "created_at":  now,
            }).execute()
            return
        except Exception as exc:
            logger.warning(
                "Supabase save_analysis failed (%s) — writing to SQLite", exc
            )

    conn = _conn()
    conn.execute(
        "INSERT INTO analyses (analysis_id, file_id, filename, result_json, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (analysis_id, file_id, filename, json.dumps(result), now),
    )
    conn.commit()
    conn.close()


def get_analysis(analysis_id: str) -> dict | None:
    if _supa_ok:
        try:
            resp = (
                _supa.table("analyses")
                .select("*")
                .eq("analysis_id", analysis_id)
                .limit(1)
                .execute()
            )
            if resp.data:
                row = resp.data[0]
                # result_json is JSONB → already a dict; TEXT → needs parsing
                result = (
                    row["result_json"]
                    if isinstance(row["result_json"], dict)
                    else json.loads(row["result_json"])
                )
                return {**row, "result": result}
        except Exception as exc:
            logger.warning(
                "Supabase get_analysis failed (%s) — reading from SQLite", exc
            )

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


def save_report(
    report_id: str,
    analysis_id: str,
    file_id: str,
    filename: str,
    pdf_path: str,
) -> None:
    now = datetime.utcnow()
    expires = now + timedelta(days=30)
    now_s = now.isoformat()
    exp_s = expires.isoformat()

    if _supa_ok:
        try:
            _supa.table("reports").insert({
                "report_id":   report_id,
                "analysis_id": analysis_id,
                "file_id":     file_id,
                "filename":    filename,
                "pdf_path":    pdf_path,
                "created_at":  now_s,
                "expires_at":  exp_s,
            }).execute()
            return
        except Exception as exc:
            logger.warning(
                "Supabase save_report failed (%s) — writing to SQLite", exc
            )

    conn = _conn()
    conn.execute(
        "INSERT INTO reports"
        " (report_id, analysis_id, file_id, filename, pdf_path, created_at, expires_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (report_id, analysis_id, file_id, filename, pdf_path, now_s, exp_s),
    )
    conn.commit()
    conn.close()


def get_report(report_id: str) -> dict | None:
    if _supa_ok:
        try:
            resp = (
                _supa.table("reports")
                .select("*")
                .eq("report_id", report_id)
                .limit(1)
                .execute()
            )
            if resp.data:
                row = dict(resp.data[0])
                if _parse_dt(row["expires_at"]) < datetime.utcnow():
                    return None          # expired — treat as not found
                return row
        except Exception as exc:
            logger.warning(
                "Supabase get_report failed (%s) — reading from SQLite", exc
            )

    conn = _conn()
    row = conn.execute(
        "SELECT * FROM reports WHERE report_id = ?", (report_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    report = dict(row)
    if _parse_dt(report["expires_at"]) < datetime.utcnow():
        return None
    return report
