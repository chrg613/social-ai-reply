"""LLM provider registry and factory functions.

Supported providers:
- gemini (primary / default)
- openai (optional, supports custom base_url)
- perplexity (optional)
- claude (optional)
- ollama (auto-detected when OLLAMA_BASE_URL is configured)
- template (always available, no API key required)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.services.infrastructure.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type] = {}


def register(name: str, cls: type) -> None:
    """Register a provider class by name."""
    _REGISTRY[name] = cls


def _build_provider(name: str, settings) -> LLMProvider | None:
    cls = _REGISTRY.get(name)
    if not cls:
        raise ValueError(f"Unknown LLM provider: {name!r}. Available: {list(_REGISTRY.keys())}")

    instance = cls.from_settings(settings)
    if instance is None or not instance.is_configured:
        return None

    return instance


def get_provider(name: str | None = None) -> LLMProvider:
    """Get a provider by name, or the default from LLM_PROVIDER env var."""
    settings = get_settings()
    provider_name = name or settings.llm_provider

    instance = _build_provider(provider_name, settings)
    if instance is not None:
        return instance

    if name is None:
        for fallback_name in _REGISTRY:
            if fallback_name == provider_name:
                continue
            fallback = _build_provider(fallback_name, settings)
            if fallback is not None:
                logger.warning(
                    "Default LLM provider %r is unavailable; falling back to configured provider %r.",
                    provider_name,
                    fallback_name,
                )
                return fallback

    raise ValueError(f"Provider {provider_name!r} is not configured (missing API key?)")


def get_configured_providers() -> dict[str, LLMProvider]:
    """Return all providers that have valid credentials configured.

    Used by VisibilityRunner to call multiple models.
    """
    settings = get_settings()
    result: dict[str, LLMProvider] = {}

    for name, _cls in _REGISTRY.items():
        try:
            instance = _build_provider(name, settings)
            if instance is not None:
                result[name] = instance
        except Exception:
            logger.debug("Provider %r failed to initialize, skipping", name)

    return result
