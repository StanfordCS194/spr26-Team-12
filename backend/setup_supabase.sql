-- ============================================================
-- Veritas — Supabase database setup
-- ============================================================
-- Run this ONCE in the Supabase SQL Editor:
--   Dashboard → SQL Editor → New Query → paste → Run
--
-- The backend uses a service_role key which bypasses Row Level
-- Security, so no RLS policies are needed for the app to work.
-- ============================================================

-- analyses: one row per ML detection run (Feature 2.3 output)
CREATE TABLE IF NOT EXISTS analyses (
    analysis_id TEXT        PRIMARY KEY,
    file_id     TEXT        NOT NULL,
    filename    TEXT        NOT NULL,
    result_json JSONB       NOT NULL,   -- full AnalysisResult payload
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- reports: shareable links generated from analyses (Feature 5)
CREATE TABLE IF NOT EXISTS reports (
    report_id   TEXT        PRIMARY KEY,
    analysis_id TEXT        NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
    file_id     TEXT        NOT NULL,
    filename    TEXT        NOT NULL,
    pdf_path    TEXT        NOT NULL,   -- local server path to the generated PDF
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL    -- 30-day TTL enforced at application layer
);

-- Speed up common lookups
CREATE INDEX IF NOT EXISTS idx_analyses_file_id     ON analyses(file_id);
CREATE INDEX IF NOT EXISTS idx_reports_analysis_id  ON reports(analysis_id);
CREATE INDEX IF NOT EXISTS idx_reports_expires_at   ON reports(expires_at);
