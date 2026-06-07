"""Brand Brain crawler — extracts intelligence from company websites."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_DEFAULT_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_PATHS = ("/", "/pricing", "/features", "/about", "/blog", "/docs", "/sitemap.xml")


@dataclass
class CrawledPage:
    """Data extracted from a single crawled page."""

    url: str
    title: str = ""
    meta_description: str = ""
    h1_list: list[str] = field(default_factory=list)
    h2_list: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    structured_data: list[dict] = field(default_factory=list)
    status_code: int | None = None
    error: str | None = None


class BrandBrainCrawler:
    """Crawls a website to build an intelligence corpus."""

    def __init__(self, rate_limit_seconds: float = 1.0) -> None:
        self.rate_limit = rate_limit_seconds
        self._last_request_time: float | None = None
        self._robots_cache: dict[str, dict[str, bool]] = {}

    def _sleep_if_needed(self) -> None:
        """Enforce rate limit between requests."""
        if self._last_request_time is not None:
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self.rate_limit:
                time.sleep(self.rate_limit - elapsed)
        self._last_request_time = time.monotonic()

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Ensure the URL has a scheme."""
        url = url.strip()
        if not url:
            raise ValueError("Empty URL")
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        return url

    def _fetch_html(self, url: str) -> str:
        """Fetch HTML with retries and SSL fallback."""
        last_err: Exception | None = None
        candidate_urls = [url]
        if url.startswith("https://"):
            candidate_urls.append(f"http://{url.removeprefix('https://')}")

        for candidate_url in candidate_urls:
            for verify_ssl in (True, False):
                try:
                    with httpx.Client(
                        timeout=25.0,
                        follow_redirects=True,
                        verify=verify_ssl,
                    ) as client:
                        resp = client.get(candidate_url, headers=_DEFAULT_HEADERS)
                        resp.raise_for_status()
                        return resp.text
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "HTTP %s for %s (ssl_verify=%s)",
                        exc.response.status_code,
                        candidate_url,
                        verify_ssl,
                    )
                    last_err = exc
                    break
                except httpx.HTTPError as exc:
                    logger.warning(
                        "Fetch failed for %s (ssl_verify=%s): %s",
                        candidate_url,
                        verify_ssl,
                        exc,
                    )
                    last_err = exc
                    if verify_ssl:
                        continue
                    break

        raise RuntimeError(f"Could not fetch {url}: {last_err}") from last_err

    def _check_robots_txt(self, domain: str) -> dict[str, bool]:
        """Parse robots.txt and return disallowed paths for the crawler UA.

        Returns a dict mapping path -> allowed (True/False).
        """
        if domain in self._robots_cache:
            return self._robots_cache[domain]

        parsed = urlparse(domain)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        disallowed: set[str] = set()

        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(robots_url, headers=_DEFAULT_HEADERS)
                if resp.status_code == 200:
                    current_agent_match = True  # * applies to all
                    for line in resp.text.splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if line.lower().startswith("user-agent"):
                            ua = line.split(":", 1)[1].strip().lower()
                            current_agent_match = ua == "*" or "crawl" in ua or "bot" in ua
                        elif current_agent_match and line.lower().startswith("disallow"):
                            path = line.split(":", 1)[1].strip()
                            if path:
                                disallowed.add(path)
        except Exception:
            logger.debug("Could not fetch robots.txt for %s", domain)

        # Build a simple lookup: exact path match or prefix match
        allowed_map: dict[str, bool] = {}
        for path in DEFAULT_PATHS:
            allowed = True
            for d in disallowed:
                if path.startswith(d) or d == path:
                    allowed = False
                    break
            allowed_map[path] = allowed

        self._robots_cache[domain] = allowed_map
        return allowed_map

    def _is_allowed(self, base_url: str, path: str) -> bool:
        """Check if a path is allowed by robots.txt."""
        parsed = urlparse(base_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        allowed_map = self._check_robots_txt(domain)
        return allowed_map.get(path, True)

    def _extract_structured_data(self, soup: BeautifulSoup) -> list[dict]:
        """Extract schema.org structured data from the page."""
        structured: list[dict] = []
        for script in soup.find_all("script", type="application/ld+json"):
            import json

            try:
                if script.string:
                    structured.append(json.loads(script.string))
            except json.JSONDecodeError:
                continue
        return structured

    def crawl_page(self, url: str) -> CrawledPage:
        """Crawl a single page and return extracted data."""
        self._sleep_if_needed()
        page = CrawledPage(url=url)
        try:
            html = self._fetch_html(url)
            page.status_code = 200
            soup = BeautifulSoup(html, "html.parser")

            # Title
            if soup.title and soup.title.string:
                page.title = soup.title.string.strip()

            # Meta description
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                page.meta_description = meta_desc.get("content").strip()

            # Headings
            page.h1_list = [h.get_text(" ", strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]
            page.h2_list = [h.get_text(" ", strip=True) for h in soup.find_all("h2") if h.get_text(strip=True)]

            # Paragraphs (first 5 non-empty)
            page.paragraphs = [
                p.get_text(" ", strip=True)
                for p in soup.find_all("p")
                if p.get_text(strip=True)
            ][:5]

            # Links
            page.links = [
                a["href"]
                for a in soup.find_all("a", href=True)
                if a["href"].startswith("http")
            ][:20]

            # Structured data
            page.structured_data = self._extract_structured_data(soup)

        except httpx.HTTPStatusError as exc:
            page.status_code = exc.response.status_code
            page.error = f"HTTP {exc.response.status_code}"
            logger.warning("HTTP %s for %s", exc.response.status_code, url)
        except httpx.HTTPError as exc:
            page.error = str(exc)
            logger.warning("Fetch error for %s: %s", url, exc)
        except Exception as exc:
            page.error = str(exc)
            logger.warning("Error parsing %s: %s", url, exc)

        return page

    def crawl_site(self, base_url: str) -> dict[str, CrawledPage]:
        """Crawl a website across standard paths.

        Args:
            base_url: The website root URL.

        Returns:
            Dict mapping URL path -> CrawledPage data.
        """
        base_url = self._normalize_url(base_url)
        results: dict[str, CrawledPage] = {}

        for path in DEFAULT_PATHS:
            if not self._is_allowed(base_url, path):
                logger.info("Skipping %s%s (robots.txt disallowed)", base_url, path)
                continue

            full_url = urljoin(base_url, path)
            page = self.crawl_page(full_url)
            results[path] = page

            if page.error and page.status_code == 404:
                logger.debug("Page not found: %s", full_url)

        return results

    def build_corpus(self, pages: dict[str, CrawledPage]) -> str:
        """Merge all extracted text into a single corpus."""
        parts: list[str] = []
        for page in pages.values():
            if page.error:
                continue
            parts.append(page.title)
            parts.append(page.meta_description)
            parts.extend(page.h1_list)
            parts.extend(page.h2_list)
            parts.extend(page.paragraphs)
        return " ".join(p for p in parts if p).strip()
