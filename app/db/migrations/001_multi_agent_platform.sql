-- ============================================================================
-- Multi-agent platform schema expansion
-- ============================================================================
-- Date:     2026-06-07
-- Author:   RedditFlow engineering (Phase 1 — Agent 2)
-- Concern:  Adds company-centric tables, feedback tracking, analytics events,
--           and agent-run logging for the multi-agent platform. Also expands
--           the existing `opportunities` and `projects` tables with new
--           columns for platform-aware processing.
--
-- Safety:   Idempotent. All CREATE TABLE use IF NOT EXISTS. All indexes
--           use IF NOT EXISTS. Column additions are wrapped in DO blocks
--           that check information_schema before altering. Re-running is a
--           no-op.
-- ============================================================================

-- ============================================================================
-- 1. New tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS company_profiles (
    id                  SERIAL PRIMARY KEY,
    workspace_id        INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    website_url         TEXT,
    description         TEXT,
    category            TEXT,
    target_audience     TEXT,
    geography           TEXT,
    language            TEXT DEFAULT 'en',
    features            JSONB DEFAULT '[]',
    benefits            JSONB DEFAULT '[]',
    pain_points         JSONB DEFAULT '[]',
    competitors         JSONB DEFAULT '[]',
    brand_voice         TEXT,
    forbidden_claims    JSONB DEFAULT '[]',
    preferred_cta       TEXT,
    extracted_summary   TEXT,
    extracted_keywords  JSONB DEFAULT '[]',
    extracted_pain_points JSONB DEFAULT '[]',
    extracted_competitors JSONB DEFAULT '[]',
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS brand_keywords (
    id                  SERIAL PRIMARY KEY,
    company_id          INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    keyword             TEXT NOT NULL,
    type                TEXT NOT NULL DEFAULT 'core',
    weight              REAL DEFAULT 1.0,
    source              TEXT,
    times_matched       INTEGER DEFAULT 0,
    times_approved      INTEGER DEFAULT 0,
    times_rejected      INTEGER DEFAULT 0,
    is_enabled          BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sources (
    id                  SERIAL PRIMARY KEY,
    company_id          INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    platform            TEXT NOT NULL,
    source_name         TEXT NOT NULL,
    source_url          TEXT,
    status              TEXT DEFAULT 'active',
    priority            INTEGER DEFAULT 50,
    config_json         JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id                  SERIAL PRIMARY KEY,
    company_id          INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    agent_name          TEXT NOT NULL,
    started_at          TIMESTAMPTZ DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    status              TEXT DEFAULT 'running',
    items_fetched       INTEGER DEFAULT 0,
    items_kept          INTEGER DEFAULT 0,
    items_rejected      INTEGER DEFAULT 0,
    error_message       TEXT,
    logs_json           JSONB DEFAULT '[]',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feedback (
    id                  SERIAL PRIMARY KEY,
    opportunity_id      INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    company_id          INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    action              TEXT NOT NULL,
    reason              TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analytics_events (
    id                  SERIAL PRIMARY KEY,
    company_id          INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    opportunity_id      INTEGER REFERENCES opportunities(id) ON DELETE SET NULL,
    event_type          TEXT NOT NULL,
    metadata_json       JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- 2. Expand existing tables
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'opportunities' AND column_name = 'platform'
    ) THEN
        ALTER TABLE opportunities ADD COLUMN platform TEXT DEFAULT 'reddit';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'opportunities' AND column_name = 'agent_name'
    ) THEN
        ALTER TABLE opportunities ADD COLUMN agent_name TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'opportunities' AND column_name = 'semantic_similarity'
    ) THEN
        ALTER TABLE opportunities ADD COLUMN semantic_similarity REAL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'opportunities' AND column_name = 'reason_relevant'
    ) THEN
        ALTER TABLE opportunities ADD COLUMN reason_relevant TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'opportunities' AND column_name = 'risk_flags'
    ) THEN
        ALTER TABLE opportunities ADD COLUMN risk_flags JSONB DEFAULT '[]';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'opportunities' AND column_name = 'matched_keywords'
    ) THEN
        ALTER TABLE opportunities ADD COLUMN matched_keywords JSONB DEFAULT '[]';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'opportunities' AND column_name = 'intent'
    ) THEN
        ALTER TABLE opportunities ADD COLUMN intent TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'opportunities' AND column_name = 'rejection_reason'
    ) THEN
        ALTER TABLE opportunities ADD COLUMN rejection_reason TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'opportunities' AND column_name = 'opportunity_type'
    ) THEN
        ALTER TABLE opportunities ADD COLUMN opportunity_type TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'opportunities' AND column_name = 'draft_article'
    ) THEN
        ALTER TABLE opportunities ADD COLUMN draft_article TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'opportunities' AND column_name = 'draft_post'
    ) THEN
        ALTER TABLE opportunities ADD COLUMN draft_post TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'opportunities' AND column_name = 'engagement_score'
    ) THEN
        ALTER TABLE opportunities ADD COLUMN engagement_score REAL DEFAULT 0;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'projects' AND column_name = 'company_id'
    ) THEN
        ALTER TABLE projects ADD COLUMN company_id INTEGER;
    END IF;
END $$;

-- ============================================================================
-- 3. Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_opportunities_platform ON opportunities(platform);
CREATE INDEX IF NOT EXISTS idx_opportunities_agent_name ON opportunities(agent_name);
CREATE INDEX IF NOT EXISTS idx_opportunities_intent ON opportunities(intent);
CREATE INDEX IF NOT EXISTS idx_brand_keywords_company_id ON brand_keywords(company_id);
CREATE INDEX IF NOT EXISTS idx_brand_keywords_type ON brand_keywords(type);
CREATE INDEX IF NOT EXISTS idx_sources_company_id ON sources(company_id);
CREATE INDEX IF NOT EXISTS idx_sources_platform ON sources(platform);
CREATE INDEX IF NOT EXISTS idx_agent_runs_company_id ON agent_runs(company_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status);
CREATE INDEX IF NOT EXISTS idx_feedback_company_id ON feedback(company_id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_company_id ON analytics_events(company_id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_event_type ON analytics_events(event_type);

-- ============================================================================
-- 4. PostgREST cache invalidation
-- ============================================================================

NOTIFY pgrst, 'reload schema';
