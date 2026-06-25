"""OpenAI LLM provider — supports custom base URLs for OpenAI-compatible endpoints."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import httpx

from app.services.infrastructure.llm._json_helpers import parse_json_payload
from app.services.infrastructure.llm.providers._registry import register
from app.services.infrastructure.llm.providers._retry import retry_http

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """OpenAI provider using the official SDK.

    Supports custom base_url for OpenAI-compatible endpoints
    (e.g., Azure OpenAI, Ollama, LM Studio, Together AI).
    """

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> OpenAIProvider | None:
        if not settings.openai_api_key:
            return None
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            max_retries=3,
        )
        return cls(client, settings.openai_model)

    @property
    def name(self) -> str:
        return "openai"

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
    ) -> dict[str, Any] | list[Any] | None:
        try:
            resp = retry_http(
                lambda: self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    max_tokens=1500,
                ),
                provider_name="OpenAI",
            )
            text = resp.choices[0].message.content if resp.choices else None
            return parse_json_payload(text) if text else None
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.error("OpenAI chat_json failed: %s: %s", type(exc).__name__, exc)
            return None

    def chat_text(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str | None:
        try:
            resp = retry_http(
                lambda: self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
                provider_name="OpenAI",
            )
            return resp.choices[0].message.content if resp.choices else None
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.error("OpenAI chat_text failed: %s: %s", type(exc).__name__, exc)
            return None


register("openai", OpenAIProvider)
