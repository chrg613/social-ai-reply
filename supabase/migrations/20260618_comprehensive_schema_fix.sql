-- ============================================================================
-- Comprehensive Schema Fix — adds ALL missing tables and columns
-- ============================================================================
-- Date:     2026-06-18
-- Safety:   All CREATE TABLE use IF NOT EXISTS; all ALTER use IF NOT EXISTS.
--           Re-running is idempotent.
-- ============================================================================

-- ============================================================================
-- PART 1: Missing columns on existing tables
-- ============================================================================

-- scan_runs: opportunities_found, subreddits_total, subreddits_scanned
ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS opportunities_found INTEGER DEFAULT 0;
ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS subreddits_total INTEGER DEFAULT 0;
ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS subreddits_scanned INTEGER DEFAULT 0;

-- opportunities: body_excerpt, score_reasons, keyword_hits, rule_risk, scan_run_id, scoring_breakdown, buying_stage, intent_confidence
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS body_excerpt TEXT;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS score_reasons JSONB DEFAULT '[]'::jsonb;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS keyword_hits JSONB DEFAULT '[]'::jsonb;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS rule_risk JSONB DEFAULT '[]'::jsonb;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS scan_run_id INTEGER REFERENCES scan_runs(id) ON DELETE SET NULL;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS scoring_breakdown JSONB DEFAULT '{}'::jsonb;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS buying_stage TEXT;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS intent_confidence REAL;

-- prompt_templates: is_default
ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS is_default BOOLEAN DEFAULT FALSE;

-- reply_drafts: source_prompt, version, status
ALTER TABLE reply_drafts ADD COLUMN IF NOT EXISTS source_prompt TEXT;
ALTER TABLE reply_drafts ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;
ALTER TABLE reply_drafts ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'draft';

-- ============================================================================
-- PART 2: Missing tables (with table name constants from Python code)
-- ============================================================================

-- reddit_accounts
CREATE TABLE IF NOT EXISTS reddit_accounts (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE,
    username TEXT,
    reddit_user_id TEXT,
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at TIMESTAMPTZ,
    karma INTEGER DEFAULT 0,
    account_created_at TIMESTAMPTZ,
    safety_config JSONB DEFAULT '{}'::jsonb,
    last_safety_check_at TIMESTAMPTZ,
    shadowban_suspected BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_reddit_accounts_workspace_id ON reddit_accounts(workspace_id);

-- integration_secrets
CREATE TABLE IF NOT EXISTS integration_secrets (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    key_name TEXT NOT NULL,
    encrypted_value TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_integration_secrets_workspace_id ON integration_secrets(workspace_id);

-- campaigns
CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    goal TEXT,
    target_platforms JSONB DEFAULT '[]'::jsonb,
    status TEXT DEFAULT 'draft',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_campaigns_project_id ON campaigns(project_id);

-- published_posts
CREATE TABLE IF NOT EXISTS published_posts (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    platform TEXT,
    external_id TEXT,
    content TEXT,
    permalink TEXT,
    status TEXT DEFAULT 'draft',
    posted_at TIMESTAMPTZ,
    engagement_metrics JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_published_posts_campaign_id ON published_posts(campaign_id);
CREATE INDEX IF NOT EXISTS idx_published_posts_project_id ON published_posts(project_id);

-- analytics_snapshots
CREATE TABLE IF NOT EXISTS analytics_snapshots (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    total_opportunities INTEGER DEFAULT 0,
    approved_drafts INTEGER DEFAULT 0,
    rejected_drafts INTEGER DEFAULT 0,
    response_rate REAL DEFAULT 0,
    metadata_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_project_date ON analytics_snapshots(project_id, snapshot_date);

-- audit_events
CREATE TABLE IF NOT EXISTS audit_events (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES account_users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    metadata_json JSONB DEFAULT '{}'::jsonb,
    ip_address TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_events_workspace_id ON audit_events(workspace_id);

-- visibility_snapshots
CREATE TABLE IF NOT EXISTS visibility_snapshots (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    provider TEXT NOT NULL,
    brand_mention_count INTEGER DEFAULT 0,
    sentiment_score REAL DEFAULT 0,
    visibility_score REAL DEFAULT 0,
    metadata_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_visibility_snapshots_project_date ON visibility_snapshots(project_id, snapshot_date);

-- prompt_sets
CREATE TABLE IF NOT EXISTS prompt_sets (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    prompts_json JSONB DEFAULT '[]'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_prompt_sets_project_id ON prompt_sets(project_id);

-- prompt_runs
CREATE TABLE IF NOT EXISTS prompt_runs (
    id SERIAL PRIMARY KEY,
    prompt_set_id INTEGER REFERENCES prompt_sets(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'running',
    provider TEXT,
    total_prompts INTEGER DEFAULT 0,
    completed_prompts INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_prompt_runs_project_id ON prompt_runs(project_id);

-- ai_responses
CREATE TABLE IF NOT EXISTS ai_responses (
    id SERIAL PRIMARY KEY,
    prompt_run_id INTEGER REFERENCES prompt_runs(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    prompt_text TEXT,
    response_text TEXT,
    latency_ms INTEGER,
    tokens_used INTEGER DEFAULT 0,
    is_cached BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ai_responses_project_id ON ai_responses(project_id);

-- brand_mentions
CREATE TABLE IF NOT EXISTS brand_mentions (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    mention_text TEXT,
    source_url TEXT,
    sentiment TEXT,
    mentioned_at TIMESTAMPTZ,
    context_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_brand_mentions_project_id ON brand_mentions(project_id);

-- citations
CREATE TABLE IF NOT EXISTS citations (
    id SERIAL PRIMARY KEY,
    opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE CASCADE,
    draft_id INTEGER REFERENCES reply_drafts(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_text TEXT,
    source_url TEXT,
    relevance_score REAL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_citations_opportunity_id ON citations(opportunity_id);

-- source_domains
CREATE TABLE IF NOT EXISTS source_domains (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    domain TEXT NOT NULL,
    domain_type TEXT DEFAULT 'unknown',
    relevance_score REAL DEFAULT 0,
    last_checked_at TIMESTAMPTZ,
    metadata_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_source_domains_project_id ON source_domains(project_id);

-- source_gaps
CREATE TABLE IF NOT EXISTS source_gaps (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    gap_type TEXT NOT NULL,
    gap_description TEXT,
    priority INTEGER DEFAULT 50,
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_source_gaps_project_id ON source_gaps(project_id);

-- webhook_endpoints
CREATE TABLE IF NOT EXISTS webhook_endpoints (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    secret TEXT,
    events JSONB DEFAULT '[]'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    last_triggered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_webhook_endpoints_workspace_id ON webhook_endpoints(workspace_id);

-- ============================================================================
-- PART 3: PostgREST schema cache refresh
-- ============================================================================
NOTIFY pgrst, 'reload schema';
