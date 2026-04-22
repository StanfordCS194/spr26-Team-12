import json
import os
from datetime import datetime, timedelta

from supabase import create_client

_client = None


def _sb():
    global _client
    if _client is None:
        _client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _client


def init_db():
    pass


def save_analysis(analysis_id: str, file_id: str, filename: str, result: dict):
    _sb().table("analyses").insert({
        "analysis_id": analysis_id,
        "file_id": file_id,
        "filename": filename,
        "result_json": json.dumps(result),
        "created_at": datetime.utcnow().isoformat(),
    }).execute()


def get_analysis(analysis_id: str) -> dict | None:
    resp = _sb().table("analyses").select("*").eq("analysis_id", analysis_id).execute()
    if not resp.data:
        return None
    row = resp.data[0]
    row["result"] = json.loads(row["result_json"])
    return row


def save_report(report_id: str, analysis_id: str, file_id: str, filename: str, pdf_url: str):
    now = datetime.utcnow()
    expires = now + timedelta(days=30)
    _sb().table("reports").insert({
        "report_id": report_id,
        "analysis_id": analysis_id,
        "file_id": file_id,
        "filename": filename,
        "pdf_url": pdf_url,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
    }).execute()


def get_report(report_id: str) -> dict | None:
    resp = _sb().table("reports").select("*").eq("report_id", report_id).execute()
    if not resp.data:
        return None
    report = resp.data[0]
    if datetime.fromisoformat(report["expires_at"]) < datetime.utcnow():
        return None
    return report
