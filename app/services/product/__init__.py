"""Product services for SignalFlow application.

Core business logic services for the SignalFlow product.
"""

from app.core.logging import setup_logging
from app.services.product.copilot import ProductCopilot
from app.services.product.discovery import (
    assess_subreddit_candidate,
    discover_and_store_subreddits,
    get_project_search_keywords,
)
from app.services.product.email_service import EmailService
from app.services.product.entitlements import (
    PLAN_CATALOG,
    enforce_limit,
    feature_set,
    get_limit,
    get_or_create_subscription,
    seed_plan_entitlements,
)
from app.services.product.pipeline import run_auto_pipeline_background
from app.services.product.reddit import RedditClient
from app.services.product.reddit_discovery import RedditDiscoveryService
from app.services.product.scanner import run_scan
from app.services.product.scoring import score_post
from app.services.product.supabase_auth import (
    SupabaseAuthError,
    SupabaseUser,
    admin_delete_user,
    admin_get_user,
    extract_user_from_response,
    sign_out,
    sign_up,
    verify_supabase_jwt,
)
from app.services.product.visibility import CitationExtractor, MentionDetector
from app.utils.encryption import decrypt_text, encrypt_text
from app.utils.security import slugify, validate_webhook_url

__all__ = [
    # Copilot
    "ProductCopilot",
    # Discovery
    "discover_and_store_subreddits",
    "assess_subreddit_candidate",
    "get_project_search_keywords",
    # Email
    "EmailService",
    # Encryption
    "encrypt_text",
    "decrypt_text",
    # Entitlements
    "get_limit",
    "enforce_limit",
    "get_or_create_subscription",
    "PLAN_CATALOG",
    "feature_set",
    "seed_plan_entitlements",
    # Logging
    "setup_logging",
    # Pipeline
    "run_auto_pipeline_background",
    # Reddit
    "RedditClient",
    "RedditDiscoveryService",
    # Scanner
    "run_scan",
    # Scoring
    "score_post",
    # Security
    "slugify",
    "validate_webhook_url",
    # Supabase Auth
    "SupabaseUser",
    "verify_supabase_jwt",
    "sign_up",
    "sign_out",
    "admin_get_user",
    "admin_delete_user",
    "extract_user_from_response",
    "SupabaseAuthError",
    # Visibility
    "MentionDetector",
    "CitationExtractor",
]
