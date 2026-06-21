"""Core module for SignalFlow application.

Provides configuration, exception classes, and constants.
"""

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AppError,
    AuthenticationError,
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)

__all__ = [
    # Configuration
    "Settings",
    "get_settings",
    # Exceptions
    "AppError",
    "NotFoundError",
    "ForbiddenError",
    "ConflictError",
    "AuthenticationError",
    "BusinessRuleError",
    "RateLimitError",
    "ValidationError",
]
