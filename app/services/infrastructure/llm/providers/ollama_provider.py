"""Ollama LLM provider — uses httpx for the OpenAI-compatible endpoint."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from app.services.infrastructure.llm._json_helpers import parse_json_payload
from app.services.infrastructure.llm.providers._registry import register

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_API_KEY = "ollama"


class OllamaProvider:
    """Ollama provider using the OpenAI-compatible REST API via httpx.

    Configurable via OLLAMA_BASE_URL and LOCAL_LLM_MODEL env vars.
    """

    def __init__(self, base_url: str, model: str, api_key: str = DEFAULT_OLLAMA_API_KEY) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key

    @classmethod
    def from_settings(cls, settings: Settings) -> OllamaProvider | None:
        if not settings.ollama_base_url:
            return None
        return cls(
            base_url=settings.ollama_base_url,
            model=settings.local_llm_model,
        )

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url)

    def _post_chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        try:
            resp = httpx.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Ollama is unreachable at {self._base_url}. "
                "Ensure Ollama is running and the model is pulled."
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Ollama timed out at {self._base_url}. "
                "Ensure Ollama is running and responsive."
            ) from exc

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
    ) -> dict[str, Any] | list[Any] | None:
        try:
            data = self._post_chat(
                messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            text = data.get("choices", [{}])[0].get("message", {}).get("content")
            return parse_json_payload(text) if text else None
        except RuntimeError:
            raise
        except Exception:
            logger.exception("Ollama chat_json failed")
            return None

    def chat_text(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str | None:
        try:
            data = self._post_chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return data.get("choices", [{}])[0].get("message", {}).get("content")
        except RuntimeError:
            raise
        except Exception:
            logger.exception("Ollama chat_text failed")
            return None


register("ollama", OllamaProvider)
