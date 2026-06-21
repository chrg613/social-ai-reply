import base64
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants.app import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_GEMINI_API_URL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PERPLEXITY_MODEL,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WEB_ENV_PATH = _REPO_ROOT / "web" / ".env.local"
_PLACEHOLDER_VALUES = {
    "",
    "https://your-project.supabase.co",
    "your-publishable-key",
    "your-secret-key",
    "your-jwt-secret",
}


def _is_valid_fernet_key(value: str) -> bool:
    """True when the string is a 32-byte urlsafe-base64 Fernet key (mirrors app.utils.encryption)."""
    try:
        raw = base64.urlsafe_b64decode(value.encode("utf-8"))
    except (ValueError, TypeError):
        return False
    return len(raw) == 32


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _strip_optional_quotes(value.strip())
    return values


def _normalize_placeholder(value: str) -> str:
    normalized = value.strip()
    return "" if normalized in _PLACEHOLDER_VALUES else normalized


class Settings(BaseSettings):
    app_name: str = "SignalFlow"
    environment: str = "development"
    # When True, plan limits from plan_entitlements (with PLAN_CATALOG fallback)
    # are enforced via HTTP 402. Off by default: the product is currently free.
    enforce_plan_limits: bool = False
    database_url: str = "sqlite:///./poacher.db"
    auto_create_tables: bool = True

    frontend_url: str = "http://localhost:3000"
    cors_origins_raw: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Supabase Auth
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    supabase_jwt_secret: str = ""

    encryption_key: str | None = None

    # LLM Provider selection — Gemini is the default for SignalFlow.
    # See app/core/constants/app.py::DEFAULT_LLM_PROVIDER. Only the active
    # provider's credentials are required; the registry silently skips any
    # provider whose API key is missing.
    llm_provider: str = DEFAULT_LLM_PROVIDER

    # Gemini (primary — default provider, normally the only one configured)
    gemini_api_key: str | None = None
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_api_url: str = DEFAULT_GEMINI_API_URL

    # OpenAI (optional alternative — leave unset unless llm_provider="openai")
    openai_api_key: str | None = None
    openai_model: str = DEFAULT_OPENAI_MODEL
    openai_base_url: str | None = None

    # Perplexity (optional alternative)
    perplexity_api_key: str | None = None
    perplexity_model: str = DEFAULT_PERPLEXITY_MODEL

    # Anthropic / Claude (optional alternative)
    anthropic_api_key: str | None = None
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL

    # Ollama (optional local LLM)
    ollama_base_url: str | None = None
    local_llm_model: str = "llama3.1"

    embedding_model: str = Field(default="tfidf", description="Embedding model: tfidf or sentence-transformers")
    # Rollback switch for the 2026-06 scoring unification: when True the
    # scanner uses the legacy scoring.score_post path instead of RelevanceEngine.
    # Default is False — the v2 engine is more permissive and produces more
    # opportunities from RSS feeds (which have score=0, num_comments=0).
    use_legacy_scoring: bool = False

    relevance_threshold: int = Field(default=70, ge=0, le=100)
    semantic_threshold: float = Field(default=0.45, ge=0.0, le=1.0)

    reddit_base_url: str = "https://old.reddit.com"
    reddit_user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    reddit_search_provider: str = "auto"
    # Min seconds between requests to reddit.com hosts. Reddit's public RSS
    # endpoints tolerate ~1 req/2s; 3s gives a safety margin against 429s.
    reddit_scrape_min_interval: float = 3.0
    serpapi_api_key: str | None = None
    bing_search_api_key: str | None = None
    bing_search_url: str = "https://api.bing.microsoft.com/v7.0/search"
    duckduckgo_search_url: str = "https://html.duckduckgo.com/html/"

    # Reddit OAuth (for connecting user Reddit accounts). When any of these are
    # empty, the /v1/reddit/connect endpoint returns a structured 503 instead
    # of handing out a placeholder authorize URL.
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_redirect_uri: str | None = None

    # RapidAPI (multi-platform social media scraping)
    rapidapi_key: str | None = None

    # Apify Integration (deprecated)
    apify_api_token: str | None = None

    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_publishable_key: str | None = None

    smtp_from_email: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True

    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def hydrate_local_supabase_settings(self) -> "Settings":
        self.supabase_url = _normalize_placeholder(self.supabase_url)
        self.supabase_publishable_key = _normalize_placeholder(self.supabase_publishable_key)
        self.supabase_secret_key = _normalize_placeholder(self.supabase_secret_key)
        self.supabase_jwt_secret = _normalize_placeholder(self.supabase_jwt_secret)

        if self.environment == "development":
            web_env = _read_env_file(_WEB_ENV_PATH)
            if not self.supabase_url:
                self.supabase_url = web_env.get("NEXT_PUBLIC_SUPABASE_URL", "").strip()
            if not self.supabase_publishable_key:
                self.supabase_publishable_key = web_env.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "").strip()

        return self

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.environment == "production":
            if not self.supabase_url:
                raise ValueError("SUPABASE_URL is required in production.")
            if not self.supabase_secret_key:
                raise ValueError("SUPABASE_SECRET_KEY is required in production.")
            if not self.supabase_publishable_key:
                raise ValueError("SUPABASE_PUBLISHABLE_KEY is required in production.")
            if not self.supabase_jwt_secret:
                raise ValueError("SUPABASE_JWT_SECRET is required in production.")
            if not self.encryption_key:
                raise ValueError("ENCRYPTION_KEY is required in production.")
            if not _is_valid_fernet_key(self.encryption_key.strip()):
                raise ValueError(
                    "ENCRYPTION_KEY must be a real Fernet key in production (passphrase-derived "
                    "keys are dev-only). Generate one with: "
                    'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
                )
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins_raw.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
