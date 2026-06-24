"""Website analysis for brand context extraction."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.services.product.copilot.inference import infer_audience, infer_business_domain, infer_cta
from app.services.product.copilot.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class WebsiteAnalysis:
    """Result of website analysis."""

    brand_name: str
    summary: str
    product_summary: str
    target_audience: str
    call_to_action: str
    voice_notes: str
    business_domain: str = ""


class WebsiteAnalyzer:
    """Analyzes website content to extract brand context."""

    _BROWSER_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self) -> None:
        self.llm = LLMClient()

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Ensure the URL has a scheme (default https)."""
        url = url.strip()
        if not url:
            raise ValueError("Empty website URL.")
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        return url

    def _fetch_html(self, url: str) -> str:
        """Fetch website HTML with retries, SSL fallback, and a real browser UA.

        Args:
            url: Website URL to fetch.

        Returns:
            HTML content as string.

        Raises:
            RuntimeError: If all fetch attempts fail.
        """
        headers = {
            "User-Agent": self._BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        last_err: Exception | None = None
        allow_http_fallback = getattr(self, "_allow_http_fallback", True)
        candidate_urls = [url]
        if allow_http_fallback and url.startswith("https://"):
            candidate_urls.append(f"http://{url.removeprefix('https://')}")

        for candidate_url in candidate_urls:
            if candidate_url != url and candidate_url.startswith("http://"):
                logger.warning("Retrying %s over plain HTTP after HTTPS fetch attempts failed", url)
            for verify_ssl in (True, False):
                try:
                    with httpx.Client(
                        timeout=25.0,
                        follow_redirects=True,
                        verify=verify_ssl,
                    ) as client:
                        resp = client.get(candidate_url, headers=headers)
                        resp.raise_for_status()
                        return resp.text
                except httpx.HTTPStatusError as exc:
                    logger.warning("HTTP %s for %s (ssl_verify=%s)", exc.response.status_code, candidate_url, verify_ssl)
                    last_err = exc
                    break
                except httpx.HTTPError as exc:
                    # Covers ConnectError, TimeoutException, and other httpx-level
                    # transport failures. Keep the retry-on-SSL loop intact.
                    logger.warning("Fetch failed for %s (ssl_verify=%s): %s", candidate_url, verify_ssl, exc)
                    last_err = exc
                    if verify_ssl:
                        logger.info("Retrying %s with SSL verification disabled...", candidate_url)
                        continue
                    break

        raise RuntimeError(f"Could not fetch {url}: {last_err}") from last_err

    def analyze_website(self, website_url: str) -> WebsiteAnalysis:
        """Analyze a website and extract brand context.

        Args:
            website_url: URL of the website to analyze.

        Returns:
            WebsiteAnalysis dataclass with extracted brand information.

        Raises:
            ValueError: If the URL is empty.
            RuntimeError: If the website cannot be fetched.
        """
        raw_url = website_url.strip()
        explicit_https = raw_url.lower().startswith("https://")
        website_url = self._normalize_url(raw_url)
        self._allow_http_fallback = not explicit_https
        try:
            html = self._fetch_html(website_url)
        finally:
            self._allow_http_fallback = True

        soup = BeautifulSoup(html, "html.parser")
        title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
        description_tag = soup.find("meta", attrs={"name": "description"})
        description = (description_tag.get("content") or "").strip() if description_tag else ""
        headings = " ".join(tag.get_text(" ", strip=True) for tag in soup.find_all(["h1", "h2"])[:6])
        paragraphs = " ".join(tag.get_text(" ", strip=True) for tag in soup.find_all("p")[:10])
        text = " ".join(part for part in [title, description, headings, paragraphs] if part).strip()
        cleaned = re.sub(r"\s+", " ", text)
        fallback_name = urlparse(website_url).netloc.replace("www.", "").split(".")[0].replace("-", " ").title()
        heuristic_text = " ".join(part for part in [description, headings, paragraphs, title] if part).strip() or cleaned or fallback_name

        ai_result = _structured_brand_analysis(self.llm, cleaned or fallback_name, fallback_name)
        if not ai_result:
            logger.warning("LLM returned no usable website analysis for %s; using heuristic fallback.", website_url)
            return _fallback_brand_analysis(heuristic_text, fallback_name)
        return ai_result


def _structured_brand_analysis(llm: LLMClient, text: str, fallback_name: str) -> WebsiteAnalysis | None:
    """Use LLM to extract structured brand analysis.

    Args:
        llm: LLMClient instance for making AI requests.
        text: Website text content to analyze.
        fallback_name: Default brand name if extraction fails.

    Returns:
        WebsiteAnalysis dataclass with extracted information, or None if analysis fails.
    """
    try:
        system_prompt = (
            "You extract go-to-market context for a Reddit engagement platform. "
            "Return JSON with brand_name, summary, product_summary, target_audience, call_to_action, voice_notes, "
            "and business_domain.\n\n"
            "business_domain MUST be a short label identifying the company's core industry or vertical "
            "(e.g. 'real estate', 'healthcare', 'fintech', 'edtech', 'ecommerce', 'saas', 'travel', "
            "'food and restaurant', 'marketing', 'developer tools', 'legal', 'logistics', 'automotive', etc.).\n\n"
            "product_summary should focus on the CORE business problem the company solves in its domain, "
            "NOT generic technology features like AI, VR, or automation. For example, if a real estate platform "
            "uses VR tours, the product_summary should emphasize real estate search and property discovery, "
            "not VR technology. Include any location/geography focus in the summary if the business is location-specific.\n\n"
            "target_audience should list the DOMAIN-SPECIFIC audience (e.g. 'home buyers, property investors, "
            "real estate agents' for a real estate platform), NOT generic tech users."
        )
        payload = llm.call(system_prompt, text[:12000], temperature=0.2)
        if not payload:
            return None
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        if not isinstance(payload, dict):
            return None
        inferred_domain = payload.get("business_domain") or infer_business_domain(
            payload.get("summary") or text[:500],
            payload.get("product_summary") or "",
        )
        return WebsiteAnalysis(
            brand_name=payload.get("brand_name") or fallback_name,
            summary=payload.get("summary") or text[:280],
            product_summary=payload.get("product_summary") or text[:280],
            target_audience=payload.get("target_audience") or infer_audience(text),
            call_to_action=payload.get("call_to_action") or infer_cta(text),
            voice_notes=payload.get("voice_notes") or "Helpful, grounded, and specific.",
            business_domain=inferred_domain,
        )
    except Exception:
        logger.exception("_structured_brand_analysis legacy fallback also failed")
        return None


async def _structured_brand_analysis_async(llm: LLMClient, text: str, fallback_name: str) -> WebsiteAnalysis | None:
    """Async version of :func:`_structured_brand_analysis`.

    Uses the Pydantic AI agent's async path directly, avoiding the
    :func:`_run_async` deadlock risk when called from an async context.
    """
    try:
        from app.services.infrastructure.llm.service import analyze_brand_async

        result = await analyze_brand_async(text, fallback_name=fallback_name, cache_ttl=300.0)
        if result is not None:
            inferred_domain = result.business_domain or infer_business_domain(
                result.summary or text[:500],
                result.product_summary or "",
            )
            return WebsiteAnalysis(
                brand_name=result.brand_name or fallback_name,
                summary=result.summary or text[:280],
                product_summary=result.product_summary or text[:280],
                target_audience=result.target_audience or infer_audience(text),
                call_to_action=result.call_to_action or infer_cta(text),
                voice_notes=result.voice_notes or "Helpful, grounded, and specific.",
                business_domain=inferred_domain,
            )
    except Exception as agent_error:
        logger.warning("Pydantic AI brand analysis agent failed, falling back to legacy: %s", agent_error)

    try:
        system_prompt = (
            "You extract go-to-market context for a Reddit engagement platform. "
            "Return JSON with brand_name, summary, product_summary, target_audience, call_to_action, voice_notes, "
            "and business_domain.\n\n"
            "business_domain MUST be a short label identifying the company's core industry or vertical "
            "(e.g. 'real estate', 'healthcare', 'fintech', 'edtech', 'ecommerce', 'saas', 'travel', "
            "'food and restaurant', 'marketing', 'developer tools', 'legal', 'logistics', 'automotive', etc.).\n\n"
            "product_summary should focus on the CORE business problem the company solves in its domain, "
            "NOT generic technology features like AI, VR, or automation. For example, if a real estate platform "
            "uses VR tours, the product_summary should emphasize real estate search and property discovery, "
            "not VR technology.\n\n"
            "target_audience should list the DOMAIN-SPECIFIC audience (e.g. 'home buyers, property investors, "
            "real estate agents' for a real estate platform), NOT generic tech users."
        )
        payload = llm.call(system_prompt, text[:12000], temperature=0.2)
        if not payload:
            return None
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        if not isinstance(payload, dict):
            return None
        inferred_domain = payload.get("business_domain") or infer_business_domain(
            payload.get("summary") or text[:500],
            payload.get("product_summary") or "",
        )
        return WebsiteAnalysis(
            brand_name=payload.get("brand_name") or fallback_name,
            summary=payload.get("summary") or text[:280],
            product_summary=payload.get("product_summary") or text[:280],
            target_audience=payload.get("target_audience") or infer_audience(text),
            call_to_action=payload.get("call_to_action") or infer_cta(text),
            voice_notes=payload.get("voice_notes") or "Helpful, grounded, and specific.",
            business_domain=inferred_domain,
        )
    except Exception:
        logger.exception("_structured_brand_analysis_async legacy fallback also failed")
        return None


def _fallback_brand_analysis(text: str, fallback_name: str) -> WebsiteAnalysis:
    """Build a deterministic analysis when the LLM response is unavailable."""
    normalized_text = re.sub(r"\s+", " ", text).strip() or fallback_name
    summary = normalized_text[:280]
    product_summary = normalized_text[:280]
    return WebsiteAnalysis(
        brand_name=fallback_name,
        summary=summary,
        product_summary=product_summary,
        target_audience=infer_audience(normalized_text),
        call_to_action=infer_cta(normalized_text),
        voice_notes="Helpful, grounded, and specific.",
        business_domain=infer_business_domain(summary, product_summary),
    )


def analyze_website(website_url: str) -> WebsiteAnalysis:
    """Convenience function to analyze a website.

    Args:
        website_url: URL of the website to analyze.

    Returns:
        WebsiteAnalysis dataclass with extracted brand information.
    """
    analyzer = WebsiteAnalyzer()
    return analyzer.analyze_website(website_url)


async def analyze_website_async(website_url: str) -> WebsiteAnalysis:
    """Async convenience function to analyze a website.

    Use this from async contexts (e.g. ``async def`` FastAPI handlers) to avoid
    the deadlock risk of the sync :func:`analyze_website`, which internally
    calls :func:`_run_async`.

    Args:
        website_url: URL of the website to analyze.

    Returns:
        WebsiteAnalysis dataclass with extracted brand information.
    """
    analyzer = WebsiteAnalyzer()
    raw_url = website_url.strip()
    explicit_https = raw_url.lower().startswith("https://")
    normalized_url = WebsiteAnalyzer._normalize_url(raw_url)
    analyzer._allow_http_fallback = not explicit_https
    try:
        html = analyzer._fetch_html(normalized_url)
    finally:
        analyzer._allow_http_fallback = True

    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    description_tag = soup.find("meta", attrs={"name": "description"})
    description = (description_tag.get("content") or "").strip() if description_tag else ""
    headings = " ".join(tag.get_text(" ", strip=True) for tag in soup.find_all(["h1", "h2"])[:6])
    paragraphs = " ".join(tag.get_text(" ", strip=True) for tag in soup.find_all("p")[:10])
    text = " ".join(part for part in [title, description, headings, paragraphs] if part).strip()
    cleaned = re.sub(r"\s+", " ", text)
    fallback_name = urlparse(normalized_url).netloc.replace("www.", "").split(".")[0].replace("-", " ").title()
    heuristic_text = " ".join(part for part in [description, headings, paragraphs, title] if part).strip() or cleaned or fallback_name

    ai_result = await _structured_brand_analysis_async(analyzer.llm, cleaned or fallback_name, fallback_name)
    if not ai_result:
        logger.warning("LLM returned no usable website analysis for %s; using heuristic fallback.", normalized_url)
        return _fallback_brand_analysis(heuristic_text, fallback_name)
    return ai_result
