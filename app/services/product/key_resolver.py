"""Key resolution helpers for BYOK (Bring Your Own Key).

Each resolver checks for a user-provided key first, then falls back to the
platform-wide environment variable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.config import get_settings
from app.db.tables.user_keys import get_user_key
from app.utils.encryption import decrypt_text

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)

# Default OpenRouter base URL
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def resolve_rapidapi_key(db: Client, workspace_id: int) -> str:
    """Return the RapidAPI key: user-provided key first, then env fallback.

    Raises:
        RuntimeError: If no key is available from either source.
    """
    row = get_user_key(db, workspace_id, "rapidapi")
    if row:
        try:
            return decrypt_text(row["encrypted_key"])
        except ValueError:
            logger.warning("Failed to decrypt user RapidAPI key for workspace %s, falling back to env", workspace_id)

    settings = get_settings()
    if settings.rapidapi_key:
        return settings.rapidapi_key

    raise RuntimeError(
        "No RapidAPI key available. Please add one in Settings → API Keys, or set RAPIDAPI_KEY in the environment."
    )


def resolve_openrouter_config(db: Client, workspace_id: int) -> tuple[str, str]:
    """Return (api_key, base_url) for OpenRouter.

    Checks for a user-provided key first, then falls back to environment
    variables ``OPENAI_API_KEY`` and ``OPENAI_BASE_URL`` (the standard way to
    route OpenAI-compatible traffic through OpenRouter).

    Raises:
        RuntimeError: If no key is available from either source.
    """
    row = get_user_key(db, workspace_id, "openrouter")
    if row:
        try:
            api_key = decrypt_text(row["encrypted_key"])
            return api_key, _OPENROUTER_BASE_URL
        except ValueError:
            logger.warning(
                "Failed to decrypt user OpenRouter key for workspace %s, falling back to env", workspace_id
            )

    settings = get_settings()
    if settings.openai_api_key:
        base_url = settings.openai_base_url or _OPENROUTER_BASE_URL
        return settings.openai_api_key, base_url

    raise RuntimeError(
        "No OpenRouter key available. Please add one in Settings → API Keys, "
        "or set OPENAI_API_KEY + OPENAI_BASE_URL in the environment."
    )
