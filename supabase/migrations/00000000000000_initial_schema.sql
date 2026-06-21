-- ============================================================================
-- SignalFlow — Complete Initial Schema
-- ============================================================================
-- Creates ALL tables required by SignalFlow from scratch.
-- Safe to re-run: uses IF NOT EXISTS throughout.
-- Run this in your Supabase SQL Editor before starting the app.
-- ============================================================================

-- ============================================================================
-- SECTION 1: Core Identity & Multi-Tenancy
-- ============================================================================

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

CREATE TABLE IF NOT EXISTS workspaces (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS memberships (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES account_users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(workspace_id, user_id)
);

CREATE TABLE IF NOT EXISTS invitations (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT DEFAULT 'member',
    token TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_invitations_workspace_id ON invitations(workspace_id);
CREATE INDEX IF NOT EXISTS idx_invitations_token ON invitations(token);

CREATE TABLE IF NOT EXISTS subscriptions (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    plan_code TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'active',
    current_period_end TIMESTAMPTZ,
    stripe_subscription_id TEXT,
    stripe_customer_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_workspace_id ON subscriptions(workspace_id);

CREATE TABLE IF NOT EXISTS plan_entitlements (
    id SERIAL PRIMARY KEY,
    plan_code TEXT NOT NULL,
    feature_key TEXT NOT NULL,
    value TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_plan_entitlements_plan_code ON plan_entitlements(plan_code);

CREATE TABLE IF NOT EXISTS redemptions (
    id SERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    plan_code TEXT NOT NULL,
    max_uses INTEGER DEFAULT 1,
    use_count INTEGER DEFAULT 0,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- SECTION 2: Projects & Brand Intelligence
-- ============================================================================

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE,
    company_id INTEGER,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

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
    website_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS company_profiles (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
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

CREATE TABLE IF NOT EXISTS brand_keywords (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'core',
    weight REAL DEFAULT 1.0,
    source TEXT,
    times_matched INTEGER DEFAULT 0,
    times_approved INTEGER DEFAULT 0,
    times_rejected INTEGER DEFAULT 0,
    is_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_brand_keywords_company_id ON brand_keywords(company_id);
CREATE INDEX IF NOT EXISTS idx_brand_keywords_type ON brand_keywords(type);

CREATE TABLE IF NOT EXISTS voice_profiles (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    example_replies JSONB DEFAULT '[]',
    tone_descriptors JSONB DEFAULT '[]',
    banned_phrases JSONB DEFAULT '[]',
    style_guide TEXT,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_voice_profiles_project ON voice_profiles(project_id, is_default);

-- ============================================================================
-- SECTION 3: Discovery & Scanning
-- ============================================================================

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
    is_active BOOLEAN DEFAULT TRUE,
    source TEXT,
    preferred_subreddits JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS discovery_keywords (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    rationale TEXT,
    priority_score INTEGER DEFAULT 50,
    source TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

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
    activity_score INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    tone_rules TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subreddits_analyses (
    id SERIAL PRIMARY KEY,
    subreddit_id INTEGER NOT NULL REFERENCES monitored_subreddits(id) ON DELETE CASCADE,
    top_post_types JSONB DEFAULT '[]',
    audience_signals JSONB DEFAULT '[]',
    posting_risk JSONB DEFAULT '[]',
    recommendation TEXT,
    analyzed_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_subreddits_analyses_subreddit_id ON subreddits_analyses(subreddit_id);

CREATE TABLE IF NOT EXISTS scan_runs (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'running',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    search_window_hours INTEGER DEFAULT 72,
    posts_scanned INTEGER DEFAULT 0,
    opportunities_found INTEGER DEFAULT 0,
    subreddits_total INTEGER DEFAULT 0,
    subreddits_scanned INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS opportunities (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    platform TEXT DEFAULT 'reddit',
    agent_name TEXT,
    reddit_post_id TEXT,
    subreddit_name TEXT,
    title TEXT,
    body TEXT,
    body_excerpt TEXT,
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
    buying_stage TEXT,
    intent_confidence REAL,
    scoring_breakdown JSONB DEFAULT '{}'::jsonb,
    score_reasons JSONB DEFAULT '[]'::jsonb,
    keyword_hits JSONB DEFAULT '[]'::jsonb,
    rule_risk JSONB DEFAULT '[]'::jsonb,
    scan_run_id INTEGER REFERENCES scan_runs(id) ON DELETE SET NULL,
    source_type TEXT DEFAULT 'post',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_opportunities_project_id ON opportunities(project_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_platform ON opportunities(platform);
CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_opportunities_relevance ON opportunities(score DESC);
CREATE INDEX IF NOT EXISTS idx_opportunities_created_at ON opportunities(created_at DESC);

CREATE TABLE IF NOT EXISTS score_feedback (
    id SERIAL PRIMARY KEY,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    company_id INTEGER REFERENCES company_profiles(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_score_feedback_opportunity_id ON score_feedback(opportunity_id);

-- ============================================================================
-- SECTION 4: Content Generation
-- ============================================================================

CREATE TABLE IF NOT EXISTS prompt_templates (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    system_prompt TEXT,
    user_prompt_template TEXT,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reply_drafts (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    rationale TEXT,
    mode TEXT DEFAULT 'soft_mention',
    source_prompt TEXT,
    version INTEGER DEFAULT 1,
    status TEXT DEFAULT 'draft',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS post_drafts (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT,
    content TEXT,
    rationale TEXT,
    platform TEXT DEFAULT 'reddit',
    thread_json JSONB DEFAULT '[]'::jsonb,
    source_reply_draft_id INTEGER,
    source_opportunity_id INTEGER,
    status TEXT DEFAULT 'draft',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS citations (
    id SERIAL PRIMARY KEY,
    opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE CASCADE,
    draft_id INTEGER REFERENCES reply_drafts(id) ON DELETE CASCADE,
    ai_response_id INTEGER,
    source_type TEXT,
    source_text TEXT,
    source_url TEXT,
    url TEXT,
    domain TEXT,
    content_type TEXT,
    title TEXT,
    excerpt TEXT,
    relevance_score REAL DEFAULT 0,
    first_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_citations_opportunity_id ON citations(opportunity_id);

-- ============================================================================
-- SECTION 5: Pipelines & Automation
-- ============================================================================

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

-- ============================================================================
-- SECTION 6: Multi-Agent Platform
-- ============================================================================

CREATE TABLE IF NOT EXISTS sources (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT,
    status TEXT DEFAULT 'active',
    priority INTEGER DEFAULT 50,
    config_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sources_company_id ON sources(company_id);
CREATE INDEX IF NOT EXISTS idx_sources_platform ON sources(platform);

CREATE TABLE IF NOT EXISTS agent_runs (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT DEFAULT 'running',
    items_fetched INTEGER DEFAULT 0,
    items_kept INTEGER DEFAULT 0,
    items_rejected INTEGER DEFAULT 0,
    error_message TEXT,
    logs_json JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_company_id ON agent_runs(company_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status);

CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY,
    opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE CASCADE,
    company_id INTEGER REFERENCES company_profiles(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_feedback_company_id ON feedback(company_id);

-- ============================================================================
-- SECTION 7: AI Visibility & SEO/GEO
-- ============================================================================

CREATE TABLE IF NOT EXISTS prompt_sets (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    prompts_json JSONB DEFAULT '[]'::jsonb,
    target_models JSONB DEFAULT '[]'::jsonb,
    schedule TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_prompt_sets_project_id ON prompt_sets(project_id);

CREATE TABLE IF NOT EXISTS prompt_runs (
    id SERIAL PRIMARY KEY,
    prompt_set_id INTEGER REFERENCES prompt_sets(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'running',
    provider TEXT,
    model_name TEXT,
    total_prompts INTEGER DEFAULT 0,
    completed_prompts INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_prompt_runs_project_id ON prompt_runs(project_id);

CREATE TABLE IF NOT EXISTS ai_responses (
    id SERIAL PRIMARY KEY,
    prompt_run_id INTEGER REFERENCES prompt_runs(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model_name TEXT,
    prompt_text TEXT,
    response_text TEXT,
    latency_ms INTEGER,
    tokens_used INTEGER DEFAULT 0,
    is_cached BOOLEAN DEFAULT FALSE,
    brand_mentioned BOOLEAN DEFAULT FALSE,
    competitor_mentions JSONB DEFAULT '[]'::jsonb,
    sentiment TEXT,
    response_length INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ai_responses_project_id ON ai_responses(project_id);

CREATE TABLE IF NOT EXISTS brand_mentions (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    ai_response_id INTEGER REFERENCES ai_responses(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    entity_name TEXT,
    mention_type TEXT,
    mention_text TEXT,
    context_snippet TEXT,
    source_url TEXT,
    sentiment TEXT,
    mentioned_at TIMESTAMPTZ,
    context_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_brand_mentions_project_id ON brand_mentions(project_id);

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

CREATE TABLE IF NOT EXISTS source_domains (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    domain TEXT NOT NULL,
    domain_type TEXT DEFAULT 'unknown',
    total_citations INTEGER DEFAULT 0,
    relevance_score REAL DEFAULT 0,
    last_checked_at TIMESTAMPTZ,
    metadata_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_source_domains_project_id ON source_domains(project_id);

CREATE TABLE IF NOT EXISTS source_gaps (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    gap_type TEXT NOT NULL,
    gap_description TEXT,
    domain TEXT,
    competitor_name TEXT,
    citation_count INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 50,
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMPTZ,
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_source_gaps_project_id ON source_gaps(project_id);

-- ============================================================================
-- SECTION 8: Campaigns & Publishing
-- ============================================================================

CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    goal TEXT,
    target_platforms JSONB DEFAULT '[]'::jsonb,
    status TEXT DEFAULT 'draft',
    start_date DATE,
    end_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_campaigns_project_id ON campaigns(project_id);

CREATE TABLE IF NOT EXISTS published_posts (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    reddit_account_id INTEGER,
    platform TEXT,
    type TEXT,
    external_id TEXT,
    reddit_id TEXT,
    subreddit TEXT,
    title TEXT,
    content TEXT,
    permalink TEXT,
    parent_post_id TEXT,
    status TEXT DEFAULT 'draft',
    posted_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    engagement_metrics JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_published_posts_campaign_id ON published_posts(campaign_id);
CREATE INDEX IF NOT EXISTS idx_published_posts_project_id ON published_posts(project_id);

-- ============================================================================
-- SECTION 9: Integrations & Reddit Accounts
-- ============================================================================

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
-- SECTION 10: Analytics & System
-- ============================================================================

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

CREATE TABLE IF NOT EXISTS analytics_events (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    metadata_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_analytics_events_company_id ON analytics_events(company_id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_event_type ON analytics_events(event_type);

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

CREATE TABLE IF NOT EXISTS activity_logs (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES account_users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    metadata_json JSONB DEFAULT '{}',
    ip_address TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_activity_logs_workspace_id ON activity_logs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_activity_logs_created_at ON activity_logs(created_at DESC);

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES account_users(id) ON DELETE CASCADE,
    type TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    message TEXT,
    is_read BOOLEAN DEFAULT FALSE,
    metadata_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notifications_workspace_id ON notifications(workspace_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);

CREATE TABLE IF NOT EXISTS usage_metrics (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    metric_key TEXT NOT NULL,
    metric_value INTEGER DEFAULT 0,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_usage_metrics_workspace_id ON usage_metrics(workspace_id);

-- ============================================================================
-- SECTION 11: Link Tracking & Attribution
-- ============================================================================

CREATE TABLE IF NOT EXISTS tracked_links (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    code TEXT UNIQUE NOT NULL,
    destination_url TEXT NOT NULL,
    opportunity_id INTEGER,
    reply_draft_id INTEGER,
    utm_params JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tracked_links_project_id ON tracked_links(project_id);
CREATE INDEX IF NOT EXISTS idx_tracked_links_code ON tracked_links(code);

CREATE TABLE IF NOT EXISTS link_clicks (
    id SERIAL PRIMARY KEY,
    tracked_link_id INTEGER REFERENCES tracked_links(id) ON DELETE CASCADE,
    clicked_at TIMESTAMPTZ DEFAULT NOW(),
    referrer TEXT,
    user_agent_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_link_clicks_tracked_link_id ON link_clicks(tracked_link_id);

-- ============================================================================
-- PostgREST schema cache refresh
-- ============================================================================
NOTIFY pgrst, 'reload schema';
