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
    """)
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
