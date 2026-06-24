-- Migration: Add competitor_mentions table for Competitor Intelligence feature
-- Tracks competitor mentions detected across social platforms with sentiment analysis.

CREATE TABLE IF NOT EXISTS competitor_mentions (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    opportunity_id BIGINT REFERENCES opportunities(id) ON DELETE SET NULL,
    competitor_name TEXT NOT NULL,
    sentiment TEXT NOT NULL DEFAULT 'negative',       -- negative, neutral, positive
    sentiment_score REAL DEFAULT 0.0,                 -- -1.0 to 1.0
    complaint_category TEXT,                          -- support, pricing, quality, reliability, features, ux, delivery, trust, none
    complaint_detail TEXT,
    source_platform TEXT DEFAULT 'reddit',
    source_url TEXT,
    post_title TEXT,
    post_body TEXT,
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_competitor_mentions_project
    ON competitor_mentions(project_id);
CREATE INDEX IF NOT EXISTS idx_competitor_mentions_competitor
    ON competitor_mentions(competitor_name);
CREATE INDEX IF NOT EXISTS idx_competitor_mentions_sentiment
    ON competitor_mentions(project_id, sentiment);
CREATE INDEX IF NOT EXISTS idx_competitor_mentions_detected
    ON competitor_mentions(project_id, detected_at DESC);

-- Notify PostgREST to pick up the new table
NOTIFY pgrst, 'reload schema';
