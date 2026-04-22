import os

from supabase import create_client

_client = None


def _sb():
    global _client
    if _client is None:
        _client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _client


def upload_heatmap(analysis_id: str, png_bytes: bytes) -> str:
    path = f"{analysis_id}.png"
    _sb().storage.from_("heatmaps").upload(
        path, png_bytes, {"content-type": "image/png"}
    )
    return _sb().storage.from_("heatmaps").get_public_url(path)


def upload_report_pdf(report_id: str, pdf_bytes: bytes) -> str:
    path = f"{report_id}.pdf"
    _sb().storage.from_("reports").upload(
        path, pdf_bytes, {"content-type": "application/pdf"}
    )
    return _sb().storage.from_("reports").get_public_url(path)
