"""Application-wide constants.

These constants define application metadata, defaults, and configuration
values that are used throughout the application.
"""

# Application metadata
APP_NAME = "SignalFlow"
APP_VERSION = "3.0.0"
APP_DESCRIPTION = "Multi-Platform Social Intelligence & AI Marketing Engine"

# API configuration
API_PREFIX = "/v1"
API_TITLE = "SignalFlow API"
API_VERSION = "3.0.0"

# Default environment
DEFAULT_ENVIRONMENT = "development"

# Default URLs
DEFAULT_FRONTEND_URL = "http://localhost:3000"
DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"

# Database defaults
# Schema is managed by Supabase — no local database URL needed

# LLM provider defaults
# Gemini is the primary/default provider for SignalFlow. OpenAI, Perplexity,
# and Claude are supported alternatives but are NOT required — with only a
# GEMINI_API_KEY set, the whole stack works end-to-end. The registry at
# app/services/infrastructure/llm/providers/_registry.py skips any provider
# whose API key is missing, so unused providers are silently inert.
DEFAULT_LLM_PROVIDER = "gemini"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
DEFAULT_GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
DEFAULT_PERPLEXITY_MODEL = "sonar"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"

# Reddit API defaults
REDDIT_BASE_URL = "https://www.reddit.com"
DEFAULT_REDDIT_USER_AGENT = "web:signalflow:v1.2 (by /u/signalflow_bot)"

# Email defaults
DEFAULT_SMTP_PORT = 587
DEFAULT_SMTP_USE_TLS = True

# Plan codes
PLAN_FREE = "free"
PLAN_PRO = "pro"
PLAN_ENTERPRISE = "enterprise"

# Plan feature keys
FEATURE_MAX_PROJECTS = "max_projects"
FEATURE_MAX_DRAFTS = "max_drafts"
FEATURE_MAX_PERSONAS = "max_personas"
FEATURE_MAX_KEYWORDS = "max_keywords"
FEATURE_MAX_SCANS = "max_scans"
FEATURE_AUTO_PIPELINE = "auto_pipeline"
FEATURE_ANALYTICS = "analytics"
FEATURE_WEBHOOKS = "webhooks"
FEATURE_API_ACCESS = "api_access"
FEATURE_PRIORITY_SUPPORT = "priority_support"

# Status defaults
DEFAULT_WORKSPACE_STATUS = "active"
DEFAULT_PROJECT_STATUS = "active"
DEFAULT_MEMBERSHIP_ROLE = "member"
DEFAULT_OPPORTUNITY_STATUS = "new"
DEFAULT_SCAN_STATUS = "pending"
DEFAULT_PROMPT_RUN_STATUS = "pending"

# Sorting defaults
DEFAULT_SORT_ORDER = "desc"
DEFAULT_SORT_BY = "created_at"

# Feature flags
ENABLE_ANALYTICS = True
ENABLE_WEBHOOKS = True
ENABLE_AUTO_PIPELINE = True
ENABLE_BILLING = True

# Logging defaults
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FORMAT = "json"

# Health check defaults
HEALTH_CHECK_PATH = "/health"
READINESS_CHECK_PATH = "/ready"
