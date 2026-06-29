"""Legacy facade for ProductCopilot - re-exports from split modules.

This file maintains backward compatibility for existing imports.
New code should import directly from app.services.product.copilot.* submodules.
"""

from __future__ import annotations

from app.services.product.copilot.analyzer import (
    WebsiteAnalysis,
    WebsiteAnalyzer,
    analyze_website,
    analyze_website_async,
)
from app.services.product.copilot.inference import infer_audience, infer_business_domain, infer_cta
from app.services.product.copilot.keyword import GeneratedKeyword, expand_keywords, generate_keywords
from app.services.product.copilot.llm_client import LLMClient
from app.services.product.copilot.persona import suggest_personas
from app.services.product.copilot.post import generate_post, generate_post_async
from app.services.product.copilot.reply import generate_reply, generate_reply_async


class ProductCopilot:
    """Facade class for backward compatibility.

    Delegates to split module functions.
    """

    def __init__(self) -> None:
        self._analyzer: WebsiteAnalyzer | None = None

    def _get_analyzer(self) -> WebsiteAnalyzer:
        """Lazily create the analyzer — only needed for website analysis."""
        if self._analyzer is None:
            self._analyzer = WebsiteAnalyzer()
        return self._analyzer

    def analyze_website(self, website_url: str) -> WebsiteAnalysis:
        """Analyze a website and extract brand context."""
        return self._get_analyzer().analyze_website(website_url)

    def suggest_personas(self, brand: dict | None, count: int = 4) -> list[dict]:
        """Generate persona suggestions from brand target audience."""
        return suggest_personas(brand, count)

    def generate_keywords(
        self,
        brand: dict | None,
        personas: list[dict],
        count: int = 12,
    ) -> list[GeneratedKeyword]:
        """Generate keywords from brand and persona context."""
        return generate_keywords(brand, personas, count)

    def generate_reply(
        self,
        opportunity: dict,
        brand: dict | None,
        prompts: list[dict],
        platform: str | None = None,
    ) -> tuple[str, str, str]:
        """Generate a reply draft for a social media opportunity."""
        return generate_reply(opportunity, brand, prompts, platform=platform)

    def generate_post(self, brand: dict | None, prompts: list[dict]) -> tuple[str, str, str]:
        """Generate a Reddit post draft from brand context."""
        return generate_post(brand, prompts)

    async def analyze_website_async(self, website_url: str) -> WebsiteAnalysis:
        """Async version of :meth:`analyze_website`.

        Use from async contexts to avoid the :func:`_run_async` deadlock risk.
        """
        return await analyze_website_async(website_url)

    async def generate_reply_async(
        self,
        opportunity: dict,
        brand: dict | None,
        prompts: list[dict],
    ) -> tuple[str, str, str]:
        """Async version of :meth:`generate_reply`.

        Use from async contexts to avoid the :func:`_run_async` deadlock risk.
        """
        return await generate_reply_async(opportunity, brand, prompts)

    async def generate_post_async(self, brand: dict | None, prompts: list[dict]) -> tuple[str, str, str]:
        """Async version of :meth:`generate_post`.

        Use from async contexts to avoid the :func:`_run_async` deadlock risk.
        """
        return await generate_post_async(brand, prompts)

    # Keep original private methods for backward compatibility
    def _meaningful_terms(self, text: str) -> list[str]:
        """Extract meaningful terms from text (stop-word filtered)."""
        from app.services.product.copilot.analyzer import re

        stop_words = {
            "about", "after", "before", "brand", "helps", "their", "there",
            "these", "those", "with", "from", "that", "this", "your", "into",
            "have", "more", "less", "best", "over", "team",
        }
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", text.lower())
        unique = []
        seen: set[str] = set()
        for word in words:
            if word in stop_words or word in seen:
                continue
            seen.add(word)
            unique.append(word)
        return unique[:30]

    def _infer_audience(self, summary: str) -> str:
        """Infer target audience from summary text."""
        return infer_audience(summary)

    def _infer_cta(self, summary: str) -> str:
        """Infer call-to-action from summary text."""
        return infer_cta(summary)

    def _infer_business_domain(self, summary: str, description: str = "") -> str:
        """Infer business domain from summary and description text."""
        return infer_business_domain(summary, description)

    def _call_gemini(self, system_prompt: str, user_content: str, temperature: float = 0.2) -> dict | list | None:
        """Call the LLM API and return parsed JSON response."""
        return LLMClient().call(system_prompt, user_content, temperature)

    def _structured_brand_analysis(self, text: str, fallback_name: str) -> WebsiteAnalysis | None:
        """Use LLM to extract structured brand analysis."""
        from app.services.product.copilot.analyzer import _structured_brand_analysis
        return _structured_brand_analysis(LLMClient(), text, fallback_name)

    def _ai_reply(
        self,
        opportunity: dict,
        brand: dict | None,
        prompt_context: str,
    ) -> tuple[str, str, str] | None:
        """Generate reply using LLM."""
        from app.services.product.copilot.reply import _ai_reply
        return _ai_reply(LLMClient(), opportunity, brand, prompt_context)

    def _ai_post(self, brand: dict | None, prompt_context: str) -> tuple[str, str, str] | None:
        """Generate post using LLM."""
        from app.services.product.copilot.post import _ai_post
        return _ai_post(LLMClient(), brand, prompt_context)

    def _parse_json_payload(self, text: str) -> dict | list | None:
        """Parse JSON from LLM response text."""
        from app.services.product.copilot.llm_client import _parse_json_payload
        return _parse_json_payload(text)


# Re-export types and functions for direct import
__all__ = [
    "ProductCopilot",
    "WebsiteAnalysis",
    "WebsiteAnalyzer",
    "GeneratedKeyword",
    "LLMClient",
    "analyze_website",
    "suggest_personas",
    "generate_keywords",
    "expand_keywords",
    "generate_reply",
    "generate_post",
    "infer_audience",
    "infer_business_domain",
    "infer_cta",
    "GeneratedKeyword",
]
