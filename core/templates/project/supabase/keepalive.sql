-- Keepalive log table
-- Prevents compute pause on serverless Postgres (Neon, etc.) that hibernates
-- databases after 7+ days of no queries.
--
-- Create ONCE per Supabase project. All apps sharing the project
-- write to this single table via their respective keepalive endpoints.
--
-- Migration: apply via Supabase SQL editor or migration tooling.

CREATE TABLE IF NOT EXISTS _keepalive_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts timestamptz NOT NULL DEFAULT now(),
  source text NOT NULL
);

-- Index for cleanup queries
CREATE INDEX IF NOT EXISTS idx_keepalive_log_ts ON _keepalive_log (ts DESC);
