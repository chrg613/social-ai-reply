"""Services module for SignalFlow application.

Provides business logic services organized by domain.
"""

from app.services.product.entitlements import (
    PLAN_CATALOG,
    enforce_limit,
    feature_set,
    get_limit,
    get_or_create_subscription,
)
from app.services.product.pipeline import run_auto_pipeline_background
from app.services.product.scoring import score_post

__all__ = [
    # Entitlements
    "get_limit",
    "enforce_limit",
    "get_or_create_subscription",
    "PLAN_CATALOG",
    "feature_set",
    # Pipeline
    "run_auto_pipeline_background",
    # Scoring
    "score_post",
]
