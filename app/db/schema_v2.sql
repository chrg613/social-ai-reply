-- ============================================
-- RedditFlow / Social AI Reply — Schema v2
-- Multi-Agent Marketing Platform
-- ============================================

-- Users (managed by Supabase Auth; account_users is local mapping)
CREATE TABLE IF NOT EXISTS account_users (
    id SERIAL PRIMARY KEY,
    supabase_uid UUID NOT NULL UNIQUE,
    email TEXT NOT NULL,
    full_name TEXT,
    avatar_url TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    tokens_invalid_before TIMESTAMPTZ,
    revoked_access_token_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Workspaces (multi-tenancy)
CREATE TABLE IF NOT EXISTS workspaces (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Memberships
CREATE TABLE IF NOT EXISTS memberships (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES account_users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(workspace_id, user_id)
);

-- Projects
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE,
    company_id INTEGER, -- FK to company_profiles when available
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Brand Profiles (legacy, 1:1 with project)
CREATE TABLE IF NOT EXISTS brand_profiles (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    brand_name TEXT,
    summary TEXT,
    product_summary TEXT,
    target_audience TEXT,
    call_to_action TEXT,
    voice_notes TEXT,
    business_domain TEXT,
    linkedin_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Personas
CREATE TABLE IF NOT EXISTS personas_v1 (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    role TEXT,
    summary TEXT,
    pain_points JSONB DEFAULT '[]',
    goals JSONB DEFAULT '[]',
    triggers JSONB DEFAULT '[]',
    tone TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Discovery Keywords
CREATE TABLE IF NOT EXISTS discovery_keywords (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    rationale TEXT,
    priority_score INTEGER DEFAULT 50,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Monitored Subreddits
CREATE TABLE IF NOT EXISTS monitored_subreddits (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    title TEXT,
    description TEXT,
    subscribers INTEGER DEFAULT 0,
    fit_score INTEGER DEFAULT 0,
    rules_summary TEXT,
    url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Scan Runs
CREATE TABLE IF NOT EXISTS scan_runs (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'running',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Opportunities (expanded for multi-agent)
CREATE TABLE IF NOT EXISTS opportunities (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    platform TEXT DEFAULT 'reddit',
    agent_name TEXT,
    reddit_post_id TEXT,
    subreddit_name TEXT,
    title TEXT,
    body TEXT,
    permalink TEXT,
    author TEXT,
    post_created_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    upvotes INTEGER DEFAULT 0,
    comments_count INTEGER DEFAULT 0,
    engagement_score REAL DEFAULT 0,
    score INTEGER DEFAULT 0,
    semantic_similarity REAL,
    status TEXT DEFAULT 'new',
    intent TEXT,
    opportunity_type TEXT,
    matched_keywords JSONB DEFAULT '[]',
    risk_flags JSONB DEFAULT '[]',
    reason_relevant TEXT,
    rejection_reason TEXT,
    draft_reply TEXT,
    draft_post TEXT,
    draft_article TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Reply Drafts
CREATE TABLE IF NOT EXISTS reply_drafts (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    rationale TEXT,
    mode TEXT DEFAULT 'soft_mention',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Post Drafts
CREATE TABLE IF NOT EXISTS post_drafts (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT,
    content TEXT,
    rationale TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Prompt Templates
CREATE TABLE IF NOT EXISTS prompt_templates (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    system_prompt TEXT,
    user_prompt_template TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Auto Pipelines
CREATE TABLE IF NOT EXISTS auto_pipelines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'pending',
    progress INTEGER DEFAULT 0,
    current_step TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    brand_summary TEXT,
    personas_generated INTEGER DEFAULT 0,
    keywords_generated INTEGER DEFAULT 0,
    subreddits_found INTEGER DEFAULT 0,
    opportunities_found INTEGER DEFAULT 0,
    drafts_generated INTEGER DEFAULT 0,
    error_message TEXT,
    website_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- NEW MULTI-AGENT TABLES
-- ============================================

-- Company Profiles
CREATE TABLE IF NOT EXISTS company_profiles (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    website_url TEXT,
    description TEXT,
    category TEXT,
    target_audience TEXT,
    geography TEXT,
    language TEXT DEFAULT 'en',
    features JSONB DEFAULT '[]',
    benefits JSONB DEFAULT '[]',
    pain_points JSONB DEFAULT '[]',
    competitors JSONB DEFAULT '[]',
    brand_voice TEXT,
    forbidden_claims JSONB DEFAULT '[]',
    preferred_cta TEXT,
    extracted_summary TEXT,
    extracted_keywords JSONB DEFAULT '[]',
    extracted_pain_points JSONB DEFAULT '[]',
    extracted_competitors JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Brand Keywords (keyword universe)
CREATE TABLE IF NOT EXISTS brand_keywords (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES company_profiles(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'core', -- core, pain_point, competitor, alternative, audience, location, problem, feature, buying_intent
    weight REAL DEFAULT 1.0,
    source TEXT,
    times_matched INTEGER DEFAULT 0,
    times_approved INTEGER DEFAULT 0,
    times_rejected INTEGER DEFAULT 0,
    is_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sources (platform abstraction)
CREATE TABLE IF NOT EXISTS sources (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES company_profiles(id) ON DELETE CASCADE,
    platform TEXT NOT NULL, -- reddit, hacker_news, seo, geo, x, linkedin, article, ugc, manual
    source_name TEXT NOT NULL,
    source_url TEXT,
    status TEXT DEFAULT 'active', -- active, paused, disabled
    priority INTEGER DEFAULT 50,
    config_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Agent Runs
CREATE TABLE IF NOT EXISTS agent_runs (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES company_profiles(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT DEFAULT 'running', -- running, completed, failed
    items_fetched INTEGER DEFAULT 0,
    items_kept INTEGER DEFAULT 0,
    items_rejected INTEGER DEFAULT 0,
    error_message TEXT,
    logs_json JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Feedback (human-in-the-loop)
CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY,
    opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE CASCADE,
    company_id INTEGER REFERENCES company_profiles(id) ON DELETE CASCADE,
    action TEXT NOT NULL, -- approved, rejected, copied, posted, marked_irrelevant, regenerated
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Analytics Events
CREATE TABLE IF NOT EXISTS analytics_events (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES company_profiles(id) ON DELETE CASCADE,
    opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    metadata_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_opportunities_project_id ON opportunities(project_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_platform ON opportunities(platform);
CREATE INDEX IF NOT EXISTS idx_opportunities_agent_name ON opportunities(agent_name);
CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_opportunities_relevance ON opportunities(score DESC);
CREATE INDEX IF NOT EXISTS idx_opportunities_created_at ON opportunities(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_brand_keywords_company_id ON brand_keywords(company_id);
CREATE INDEX IF NOT EXISTS idx_sources_company_id ON sources(company_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_company_id ON agent_runs(company_id);
CREATE INDEX IF NOT EXISTS idx_feedback_company_id ON feedback(company_id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_company_id ON analytics_events(company_id);
