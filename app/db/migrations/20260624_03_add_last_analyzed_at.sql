-- Migration: Add last_analyzed_at column to company_profiles
-- Tracks when the brand analysis LLM step last ran.

ALTER TABLE company_profiles
    ADD COLUMN IF NOT EXISTS last_analyzed_at TIMESTAMPTZ;

-- Notify PostgREST to pick up the new column
NOTIFY pgrst, 'reload schema';
