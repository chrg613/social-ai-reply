-- ============================================================================
-- Fix ALL missing schema elements — run this in Supabase SQL editor
-- ============================================================================
-- Date:     2026-06-17
-- Safety:   All ADD COLUMN use IF NOT EXISTS checks; CREATE TABLE uses
--           IF NOT EXISTS. Re-running is a no-op.
-- ============================================================================

-- ============================================================================
-- 1. Add missing columns to existing tables
-- ============================================================================

-- personas_v1: source, is_active, preferred_subreddits
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'personas_v1' AND column_name = 'is_active') THEN
        ALTER TABLE personas_v1 ADD COLUMN is_active BOOLEAN DEFAULT TRUE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'personas_v1' AND column_name = 'source') THEN
        ALTER TABLE personas_v1 ADD COLUMN source TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'personas_v1' AND column_name = 'preferred_subreddits') THEN
        ALTER TABLE personas_v1 ADD COLUMN preferred_subreddits JSONB DEFAULT '[]';
    END IF;
END $$;

-- discovery_keywords: source, is_active
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'discovery_keywords' AND column_name = 'source') THEN
        ALTER TABLE discovery_keywords ADD COLUMN source TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'discovery_keywords' AND column_name = 'is_active') THEN
        ALTER TABLE discovery_keywords ADD COLUMN is_active BOOLEAN DEFAULT TRUE;
    END IF;
END $$;

-- monitored_subreddits: activity_score, is_active
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'monitored_subreddits' AND column_name = 'activity_score') THEN
        ALTER TABLE monitored_subreddits ADD COLUMN activity_score INTEGER DEFAULT 0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'monitored_subreddits' AND column_name = 'is_active') THEN
        ALTER TABLE monitored_subreddits ADD COLUMN is_active BOOLEAN DEFAULT TRUE;
    END IF;
END $$;

-- brand_profiles: website_url
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'brand_profiles' AND column_name = 'website_url') THEN
        ALTER TABLE brand_profiles ADD COLUMN website_url TEXT;
    END IF;
END $$;

-- reply_drafts: source_prompt, version, status
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'reply_drafts' AND column_name = 'source_prompt') THEN
        ALTER TABLE reply_drafts ADD COLUMN source_prompt TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'reply_drafts' AND column_name = 'version') THEN
        ALTER TABLE reply_drafts ADD COLUMN version INTEGER DEFAULT 1;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'reply_drafts' AND column_name = 'status') THEN
        ALTER TABLE reply_drafts ADD COLUMN status TEXT DEFAULT 'draft';
    END IF;
END $$;

-- opportunities: buying_stage
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'opportunities' AND column_name = 'buying_stage') THEN
        ALTER TABLE opportunities ADD COLUMN buying_stage TEXT;
    END IF;
END $$;

-- scan_runs: completed_at, search_window_hours, posts_scanned, opportunities_found
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'scan_runs' AND column_name = 'completed_at') THEN
        ALTER TABLE scan_runs ADD COLUMN completed_at TIMESTAMPTZ;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'scan_runs' AND column_name = 'search_window_hours') THEN
        ALTER TABLE scan_runs ADD COLUMN search_window_hours INTEGER DEFAULT 72;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'scan_runs' AND column_name = 'posts_scanned') THEN
        ALTER TABLE scan_runs ADD COLUMN posts_scanned INTEGER DEFAULT 0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'scan_runs' AND column_name = 'opportunities_found') THEN
        ALTER TABLE scan_runs ADD COLUMN opportunities_found INTEGER DEFAULT 0;
    END IF;
END $$;

-- prompt_templates: is_default
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'prompt_templates' AND column_name = 'is_default') THEN
        ALTER TABLE prompt_templates ADD COLUMN is_default BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

-- ============================================================================
-- 2. Create missing tables
-- ============================================================================

-- activity_logs
CREATE TABLE IF NOT EXISTS activity_logs (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id         INTEGER REFERENCES account_users(id) ON DELETE SET NULL,
    action          TEXT NOT NULL,
    entity_type     TEXT,
    entity_id       TEXT,
    metadata_json   JSONB DEFAULT '{}',
    ip_address      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_activity_logs_workspace_id ON activity_logs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_activity_logs_created_at ON activity_logs(created_at DESC);

-- notifications
CREATE TABLE IF NOT EXISTS notifications (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id         INTEGER REFERENCES account_users(id) ON DELETE CASCADE,
    type            TEXT NOT NULL DEFAULT 'info',
    title           TEXT NOT NULL,
    message         TEXT,
    is_read         BOOLEAN DEFAULT FALSE,
    metadata_json   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notifications_workspace_id ON notifications(workspace_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON notifications(is_read);

-- subscriptions
CREATE TABLE IF NOT EXISTS subscriptions (
    id                  SERIAL PRIMARY KEY,
    workspace_id        INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    plan_code           TEXT NOT NULL DEFAULT 'free',
    status              TEXT NOT NULL DEFAULT 'active',
    current_period_end  TIMESTAMPTZ,
    stripe_subscription_id TEXT,
    stripe_customer_id  TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_workspace_id ON subscriptions(workspace_id);

-- plan_entitlements
CREATE TABLE IF NOT EXISTS plan_entitlements (
    id          SERIAL PRIMARY KEY,
    plan_code   TEXT NOT NULL,
    feature_key TEXT NOT NULL,
    value       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_plan_entitlements_plan_code ON plan_entitlements(plan_code);

-- redemptions
CREATE TABLE IF NOT EXISTS redemptions (
    id          SERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    plan_code   TEXT NOT NULL,
    max_uses    INTEGER DEFAULT 1,
    use_count   INTEGER DEFAULT 0,
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- subreddits_analyses
CREATE TABLE IF NOT EXISTS subreddits_analyses (
    id                  SERIAL PRIMARY KEY,
    subreddit_id        INTEGER NOT NULL REFERENCES monitored_subreddits(id) ON DELETE CASCADE,
    top_post_types      JSONB DEFAULT '[]',
    audience_signals    JSONB DEFAULT '[]',
    posting_risk        JSONB DEFAULT '[]',
    recommendation      TEXT,
    analyzed_at         TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_subreddits_analyses_subreddit_id ON subreddits_analyses(subreddit_id);

-- score_feedback
CREATE TABLE IF NOT EXISTS score_feedback (
    id              SERIAL PRIMARY KEY,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    company_id      INTEGER REFERENCES company_profiles(id) ON DELETE CASCADE,
    action          TEXT NOT NULL,
    reason          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_score_feedback_opportunity_id ON score_feedback(opportunity_id);

-- usage_metrics
CREATE TABLE IF NOT EXISTS usage_metrics (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    metric_key      TEXT NOT NULL,
    metric_value    INTEGER DEFAULT 0,
    recorded_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_usage_metrics_workspace_id ON usage_metrics(workspace_id);

-- invitations
CREATE TABLE IF NOT EXISTS invitations (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    role            TEXT DEFAULT 'member',
    token           TEXT NOT NULL UNIQUE,
    expires_at      TIMESTAMPTZ,
    accepted_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_invitations_workspace_id ON invitations(workspace_id);
CREATE INDEX IF NOT EXISTS idx_invitations_token ON invitations(token);

-- ============================================================================
-- 3. PostgREST cache invalidation
-- ============================================================================
NOTIFY pgrst, 'reload schema';
