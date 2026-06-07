"""Template-based LLM fallback provider — works without any API key.

Ensures the platform never crashes when no paid API is configured.
Uses prompt heuristics to select the appropriate response template.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.services.infrastructure.llm.providers._registry import register

logger = logging.getLogger(__name__)


class TemplateProvider:
    """Fallback provider that returns structured template output.

    Does NOT make any HTTP calls. Uses Jinja2-style string formatting
    with brand context variables to return structured JSON matching the
    same schema as real LLM providers.
    """

    def __init__(self) -> None:
        pass

    @classmethod
    def from_settings(cls, settings: Any) -> TemplateProvider:
        """Always available — no configuration required."""
        return cls()

    @property
    def name(self) -> str:
        return "template"

    @property
    def is_configured(self) -> bool:
        return True

    def _extract_text(self, messages: list[dict[str, str]]) -> str:
        """Flatten messages into a single text block."""
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.append(f"[System]\n{content}")
            else:
                parts.append(content)
        return "\n\n".join(parts)

    def _detect_use_case(self, text: str) -> str:
        """Heuristic to determine which template to use.

        More specific patterns are checked first to avoid false matches.
        """
        text_lower = text.lower()
        if any(k in text_lower for k in ("reply draft", "draft a reply", "generate a reply", "reddit post")):
            return "reply_draft"
        if any(k in text_lower for k in ("post draft", "draft a post", "social media post", "generate a post")):
            return "post_draft"
        if any(k in text_lower for k in ("website analysis", "brand analysis", "analyze this website", "brand profile")):
            return "website_analysis"
        if any(k in text_lower for k in ("persona", "target audience", "audience profile")):
            return "persona_generation"
        if any(k in text_lower for k in ("article brief", "blog brief", "content brief")):
            return "article_brief"
        if any(k in text_lower for k in ("keyword", "keywords")):
            return "keyword_generation"
        return "generic"

    def _extract_brand(self, text: str) -> str | None:
        """Extract brand/company name from prompt text."""
        patterns = [
            r"Brand:\s*([^\n,.]+)",
            r"Company:\s*([^\n,.]+)",
            r"for\s+([A-Z][A-Za-z0-9\s&]+?)(?:,|\.|$|\n)",
            r"([A-Z][A-Za-z0-9\s&]+?)\s+is\s+(?:a|an)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip().rstrip(".,;")
        return None

    def _extract_topic(self, text: str) -> str:
        """Extract topic from prompt text."""
        patterns = [
            r"about\s+([^.]+)",
            r"topic:\s*([^.]+)",
            r"subject:\s*([^.]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip().rstrip(".,;")
        return "the discussed topic"

    def _render_json(self, use_case: str, text: str) -> dict[str, Any]:
        """Return structured JSON matching the expected schema for each use case."""
        brand = self._extract_brand(text) or "your product"
        topic = self._extract_topic(text)

        if use_case == "reply_draft":
            return {
                "content": (
                    f"Thanks for sharing your experience with {topic}. "
                    f"Based on what you're looking for, {brand} might be worth checking out — "
                    f"it handles exactly this use case and is designed to save you time. "
                    f"Feel free to DM me if you have any questions about how it works."
                ),
                "rationale": (
                    f"This reply is helpful and directly addresses the user's question about {topic}. "
                    f"It naturally mentions {brand} as a relevant solution without being pushy."
                ),
            }
        if use_case == "post_draft":
            return {
                "content": (
                    f"Struggling with {topic}? Here's a quick tip: start with the root cause, not the symptom. "
                    f"{brand} was built to help teams solve exactly this — here's a 2-minute overview of how it works. "
                    f"Would love to hear your thoughts in the comments."
                ),
                "rationale": (
                    f"This post provides genuine value about {topic} and introduces {brand} naturally as a solution."
                ),
            }
        if use_case == "website_analysis":
            return {
                "brand_name": brand,
                "product_description": f"{brand} is a solution focused on solving problems related to {topic}.",
                "target_audience": f"People interested in {topic}",
                "key_benefits": ["Saves time", "Improves accuracy", "Easy to use"],
                "tone": "Professional and helpful",
            }
        if use_case == "persona_generation":
            return {
                "personas": [
                    {
                        "name": "Primary Persona",
                        "description": f"People interested in {topic}",
                        "pain_points": ["Inefficient workflows", "Lack of reliable tools"],
                        "goals": [f"Find a better solution for {topic}"],
                    }
                ]
            }
        if use_case == "keyword_generation":
            return {
                "keywords": [
                    f"{topic} tool",
                    f"best {topic} solution",
                    f"{brand} alternative",
                    f"{topic} software",
                ]
            }
        if use_case == "article_brief":
            return {
                "title": f"How to Solve {topic} with {brand}",
                "outline": [
                    f"Introduction to {topic}",
                    "Common challenges",
                    f"How {brand} addresses these challenges",
                    "Step-by-step guide",
                    "Conclusion",
                ],
                "key_points": [
                    f"Identify the core problem in {topic}",
                    f"Map {brand} features to pain points",
                    "Include actionable takeaways",
                ],
            }
        return {
            "content": f"Here is a helpful response regarding {topic}. Consider how {brand} can help with your specific needs.",
            "rationale": f"This response is safe, relevant, and references {brand} naturally.",
        }

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
    ) -> dict[str, Any] | list[Any] | None:
        text = self._extract_text(messages)
        use_case = self._detect_use_case(text)
        result = self._render_json(use_case, text)
        logger.info("TemplateProvider used for use_case=%s", use_case)
        return result

    def chat_text(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str | None:
        text = self._extract_text(messages)
        use_case = self._detect_use_case(text)
        result = self._render_json(use_case, text)
        if isinstance(result, dict):
            return json.dumps(result, indent=2)
        return str(result)

    def call_json(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience wrapper that matches the facade call_json signature."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        result = self.chat_json(messages, temperature=temperature)
        if result is None:
            return {"content": "", "rationale": "Template provider returned empty result."}
        return result

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> str:
        """Convenience wrapper that returns formatted text directly."""
        result = self.chat_text(messages, temperature=temperature, max_tokens=max_tokens)
        return result or ""


register("template", TemplateProvider)
