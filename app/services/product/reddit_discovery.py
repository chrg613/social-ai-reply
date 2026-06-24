"""Credential-free Reddit discovery service.

This service keeps the scan pipeline working without Reddit OAuth by combining:
1. Reddit's public JSON search endpoints (subreddits/search.json, search.json).
2. External web search for Reddit thread URLs.
3. Public subreddit JSON feeds (`new.json` / `top.json` / `hot.json`).
4. RSS feed fallbacks.

It normalizes everything into `RedditPost` objects so scoring, opportunity
creation, and drafting continue to use the existing contracts.

Inspired by the last30days-skill pattern: https://github.com/mvanhorn/last30days-skill
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings
from app.core.exceptions import BusinessRuleError
from app.services.infrastructure.http_budget import HttpBudget
from app.services.product.reddit import (
    RedditComment,
    RedditPost,
    RedditSubredditMatch,
    _rerank_by_keyword_relevance,
    _search_keyword_variants,
)
from app.services.product.relevance import has_meaningful_phrase_overlap, tokenize

log = logging.getLogger("signalflow.reddit_discovery")

# Process-wide cache shared across discovery service instances so repeated
# subreddit/search hydration in a worker can reuse responses.
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_MAX_ENTRIES = 2048
_VALID_REDDIT_POST_PATH = re.compile(r"^/r/([^/]+)/comments/([^/?#]+)/?", re.IGNORECASE)
_REDDIT_HOSTS = {
    "reddit.com",
    "www.reddit.com",
    "old.reddit.com",
    "np.reddit.com",
    "new.reddit.com",
}
_SEARCH_RESULT_CACHE_TTL = 300.0
_POST_CACHE_TTL = 300.0
_SUBREDDIT_CACHE_TTL = 900.0
# Hard caps to prevent runaway scans (infinite pipeline loop).
_MAX_TOTAL_FEED_REQUESTS = 30  # max Reddit HTTP requests per search_posts() call
_SEARCH_TIMEOUT_SECONDS = 180  # 3-minute wall-clock cap for search_posts()
_MIN_INTERVAL_BY_HOST = {
    "api.bing.microsoft.com": 0.25,
    "html.duckduckgo.com": 0.75,
    "serpapi.com": 0.25,
}

# Shared across all RedditDiscoveryService instances (the scanner creates one
# per subreddit) so throttling and circuit state apply process-wide per host.
_HTTP_BUDGET = HttpBudget(
    min_interval_by_host=_MIN_INTERVAL_BY_HOST,
    failure_threshold=5,       # Open circuit after 5 consecutive failures (was 10)
    cooldown_seconds=45.0,     # Cool down for 45s (was 120s) — Reddit's limit window is ~60s
)


@dataclass(slots=True)
class SearchResult:
    url: str
    title: str = ""
    snippet: str = ""


def _parse_rss(text: str) -> BeautifulSoup:
    """Parse RSS/Atom XML with warnings suppressed."""
    import warnings

    from bs4 import XMLParsedAsHTMLWarning

    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    return BeautifulSoup(text, "html.parser")


def _parse_rss_entry(entry: Any, *, expected_subreddit: str | None = None) -> RedditPost | None:
    """Extract a RedditPost directly from an RSS <entry> element.

    This is the **batch parsing** path — no additional HTTP requests needed.
    Each RSS <entry> contains title, author, body (content), and link.

    Returns None if the entry can't be parsed into a valid post.
    """
    import contextlib
    import html as html_mod

    # Get link URL
    link_el = entry.find("link")
    if not link_el:
        return None
    url = link_el.get("href", "")
    if not url or "/comments/" not in url:
        return None

    # Parse permalink for post_id and subreddit
    normalized = _normalize_reddit_post_url(url)
    if not normalized:
        return None
    path_segments = [s for s in urlsplit(normalized).path.split("/") if s]
    if len(path_segments) < 4:
        return None
    subreddit = path_segments[1]
    post_id = path_segments[3]

    # Optional: filter by expected subreddit
    if expected_subreddit and subreddit.lower() != expected_subreddit.lower():
        return None

    # Title
    title_el = entry.find("title")
    title = title_el.text.strip() if title_el else ""
    if not title:
        return None

    # Body from content
    body = ""
    content_el = entry.find("content")
    if content_el:
        raw = html_mod.unescape(content_el.decode_contents())
        body_soup = BeautifulSoup(raw, "html.parser")
        body = body_soup.get_text(" ", strip=True)
        for prefix in ("<!-- SC_OFF -->", "<!-- SC_ON -->"):
            body = body.replace(prefix, "").strip()

    # Author
    author = ""
    author_el = entry.find("author")
    if author_el:
        name_el = author_el.find("name")
        author = name_el.text.removeprefix("/u/").strip() if name_el else ""

    # Score (best-effort from media:statistics if present)
    score = 0
    stats = entry.find("media:statistics")
    if stats:
        with contextlib.suppress(ValueError, TypeError):
            score = int(stats.get("views", 0))

    # Timestamp
    created_at = None
    updated_el = entry.find("updated")
    if updated_el and updated_el.text:
        with contextlib.suppress(ValueError, TypeError):
            dt_str = updated_el.text.strip()
            if dt_str.endswith("Z"):
                dt_str = dt_str[:-1] + "+00:00"
            created_at = datetime.fromisoformat(dt_str).replace(tzinfo=None)

    permalink = normalized if normalized.startswith("http") else f"https://www.reddit.com{normalized}"

    return RedditPost(
        post_id=post_id,
        subreddit=subreddit,
        title=title,
        author=author or "[deleted]",
        permalink=permalink,
        body=body,
        score=score,
        num_comments=0,
        created_at=created_at,
    )


class RedditDiscoveryService:
    """Discover Reddit posts and subreddit metadata without Reddit OAuth."""

    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._search_provider = (settings.reddit_search_provider or "auto").strip().lower()
        self._serpapi_api_key = (settings.serpapi_api_key or "").strip()
        self._bing_search_api_key = (settings.bing_search_api_key or "").strip()
        self._duckduckgo_search_url = settings.duckduckgo_search_url
        self._bing_search_url = settings.bing_search_url
        self._reddit_base_url = settings.reddit_base_url.rstrip("/")
        for reddit_host in _REDDIT_HOSTS:
            _HTTP_BUDGET.set_min_interval(reddit_host, settings.reddit_scrape_min_interval)
        self._client = httpx.Client(
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "User-Agent": settings.reddit_user_agent,
            },
            timeout=6.0,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RedditDiscoveryService:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # ── Reddit public search endpoints (RSS-first, batch parsing) ──────

    def _search_subreddits_reddit(self, keyword: str, limit: int = 10) -> list[RedditSubredditMatch]:
        """Discover subreddits via Reddit's public RSS search.

        Searches /search.rss and extracts unique subreddit names from post URLs.
        Free, no authentication required.
        """
        return self._discover_subreddits_via_search_rss(keyword, limit=limit)

    def _discover_subreddits_via_search_rss(self, keyword: str, limit: int = 10) -> list[RedditSubredditMatch]:
        """Extract unique subreddits from Reddit /search.rss results.

        Tries the configured base URL first, then falls back to
        old.reddit.com if the primary domain is blocked/429'd.
        """
        base_urls = [self._reddit_base_url]
        # Reddit rate-limits domains independently — try the other one as fallback.
        if "old.reddit.com" in self._reddit_base_url:
            base_urls.append("https://www.reddit.com")
        else:
            base_urls.append("https://old.reddit.com")

        resp = None
        for base_url in base_urls:
            rss_url = f"{base_url}/search.rss"
            try:
                resp = self._request(
                    "GET",
                    rss_url,
                    params={"q": keyword, "sort": "relevance", "t": "month", "limit": min(limit * 5, 50)},
                )
                break  # success — stop trying other domains
            except Exception as exc:
                log.warning("Reddit /search.rss failed on %s for subreddit discovery: %s", base_url, exc)
                continue

        if resp is None:
            return []

        soup = _parse_rss(resp.text)
        subreddit_counts: dict[str, int] = {}
        for entry in soup.find_all("entry"):
            link_el = entry.find("link")
            if not link_el:
                continue
            url = link_el.get("href", "")
            subreddit = _subreddit_from_post_url(url)
            if subreddit:
                key = subreddit.lower()
                subreddit_counts[key] = subreddit_counts.get(key, 0) + 1

        if not subreddit_counts:
            return []

        # Sort by frequency (most posts = most relevant subreddit)
        ranked = sorted(subreddit_counts.items(), key=lambda item: item[1], reverse=True)

        matches: list[RedditSubredditMatch] = []
        for sub_name, count in ranked[:limit]:
            matches.append(
                RedditSubredditMatch(
                    name=sub_name,
                    title="",
                    description=f"Found {count} relevant post(s) via Reddit search",
                    subscribers=0,
                )
            )

        log.info("RSS search discovered %d subreddits for %r", len(matches), keyword)
        return matches

    def _search_posts_reddit(
        self,
        keywords: list[str],
        *,
        subreddits: set[str] | None = None,
        limit: int = 20,
    ) -> list[RedditPost]:
        """Search Reddit posts via /search.rss — batch parse, no per-post hydration.

        Parses all posts directly from the RSS feed entries. Each entry contains
        title, author, body (content), and link — so one HTTP request returns ~25
        posts instead of requiring individual hydration requests.
        """
        posts_by_id: dict[str, RedditPost] = {}
        query = " OR ".join(f'"{kw}"' for kw in keywords[:6])
        if not query:
            return []

        rss_targets: list[str] = []
        if subreddits:
            for sub in sorted(subreddits):
                rss_targets.append(f"/r/{sub}/search.rss")
        else:
            rss_targets.append("/search.rss")

        for rss_path in rss_targets:
            rss_params: dict[str, Any] = {
                "q": query,
                "sort": "relevance",
                "t": "month",
                "limit": min(limit * 2, 50),
            }
            if "/r/" in rss_path:
                rss_params["restrict_sr"] = "on"

            try:
                resp = self._request("GET", f"{self._reddit_base_url}{rss_path}", params=rss_params)
                soup = _parse_rss(resp.text)

                for entry in soup.find_all("entry"):
                    post = _parse_rss_entry(entry)
                    if post:
                        posts_by_id[post.post_id] = post
                        if len(posts_by_id) >= limit:
                            break
            except Exception as exc:
                log.warning("Reddit search.rss failed for %s: %s", rss_path, exc)

            if len(posts_by_id) >= limit:
                break

        return _rerank_by_keyword_relevance(list(posts_by_id.values()), keywords)[:limit]

    def search_posts(
        self,
        keywords: list[str],
        subreddits: list[str] | None = None,
        *,
        limit: int = 20,
    ) -> list[RedditPost]:
        """Search Reddit posts using multiple free strategies with hard caps.

        Fallback chain:
        1. Reddit /search.rss (batch parsing, no per-post hydration)
        2. Subreddit feed scraping (/r/{sub}/new.rss, /r/{sub}/top.rss)
        3. External web search → hydrate via RSS (only if modes A+B found nothing)

        Hard caps prevent infinite loops:
        - Wall-clock timeout: 3 minutes
        - Max HTTP requests: 30
        """
        ordered_keywords = self._normalize_keywords(keywords)
        if not ordered_keywords:
            return []

        allowed_subreddits = {
            subreddit.strip().lower()
            for subreddit in (subreddits or [])
            if subreddit and subreddit.strip()
        }
        posts_by_id: dict[str, RedditPost] = {}
        mode_errors: list[str] = []
        successful_modes = 0
        deadline = time.monotonic() + _SEARCH_TIMEOUT_SECONDS

        def _budget_ok() -> bool:
            """Check if we've exceeded time or request budget."""
            if time.monotonic() > deadline:
                log.info("search_posts hit %ds timeout — returning %d posts collected so far",
                         _SEARCH_TIMEOUT_SECONDS, len(posts_by_id))
                return False
            return True

        # Mode A: Reddit search RSS (batch — 1 request returns ~25 posts).
        if _budget_ok():
            try:
                reddit_posts = self._search_posts_reddit(
                    ordered_keywords,
                    subreddits=allowed_subreddits or None,
                    limit=limit,
                )
            except Exception as exc:  # noqa: BLE001 - keep scans alive
                mode_errors.append(f"Reddit search: {type(exc).__name__}: {exc}")
                log.warning("Reddit search failed: %s", exc)
            else:
                if reddit_posts:
                    successful_modes += 1
                    self._merge_posts(posts_by_id, reddit_posts, allowed_subreddits)

        # Mode B: subreddit feed RSS (batch — 1 request per sub per sort).
        if allowed_subreddits and _budget_ok():
            for subreddit in sorted(allowed_subreddits):
                if not _budget_ok():
                    break
                try:
                    feed_posts = self._search_posts_in_subreddit_feed(
                        subreddit,
                        ordered_keywords,
                        limit=limit,
                    )
                except Exception as exc:  # noqa: BLE001 - keep scans alive
                    mode_errors.append(f"r/{subreddit}: {type(exc).__name__}: {exc}")
                    log.warning("Subreddit feed fetch failed for r/%s: %s", subreddit, exc)
                    continue
                successful_modes += 1
                self._merge_posts(posts_by_id, feed_posts, allowed_subreddits)

        # Mode C: external web search — only if modes A+B found nothing.
        if not posts_by_id and _budget_ok():
            try:
                external_posts = self._search_posts_via_external_search(
                    ordered_keywords,
                    allowed_subreddits=allowed_subreddits,
                    limit=limit,
                )
            except Exception as exc:  # noqa: BLE001 - keep scans alive
                mode_errors.append(f"external search: {type(exc).__name__}: {exc}")
                log.warning("External Reddit search failed: %s", exc)
            else:
                if external_posts:
                    successful_modes += 1
                    self._merge_posts(posts_by_id, external_posts, allowed_subreddits)

        if successful_modes == 0 and mode_errors:
            sample = "; ".join(mode_errors[:3])
            raise BusinessRuleError(
                f"All Reddit discovery methods failed. Sample errors: {sample[:400]}"
            )

        overall_limit = limit * max(len(allowed_subreddits), 1)
        return _rerank_by_keyword_relevance(list(posts_by_id.values()), ordered_keywords)[:overall_limit]

    def search_subreddits(self, keyword: str, limit: int = 10) -> list[RedditSubredditMatch]:
        """Discover subreddit candidates.

        Fallback chain — ordered by speed and reliability:
        1. Reddit /search.rss → fast (1 HTTP call), most reliable
        2. Keyword-based catalog → instant (zero HTTP), guaranteed results
        3. External web search (DDG) → slow, often rate-limited
        4. LLM suggestion → slow, often 429'd

        Reddit RSS is tried first because it's fast (single call) and returns
        the most relevant results.  The catalog is the instant zero-HTTP
        fallback.  DDG and LLM are last because they're slow and unreliable.
        """
        # ── Strategy 1: Reddit RSS search — fast, 1 HTTP call ─────────────
        reddit_matches = self._search_subreddits_reddit(keyword, limit=limit)
        if reddit_matches:
            return reddit_matches

        # ── Strategy 2: Keyword-based catalog (zero HTTP, instant) ────────
        catalog_matches = self._suggest_subreddits_from_catalog(keyword, limit=limit)
        if catalog_matches:
            log.info("Catalog suggested %d subreddits for %r (zero HTTP)", len(catalog_matches), keyword)
            return catalog_matches

        # ── Strategy 3: External web search (DDG) — slow fallback ─────────
        web_matches = self._discover_subreddits_via_web_search(keyword, limit=limit)
        if web_matches:
            log.info("Web search discovered %d subreddits for %r", len(web_matches), keyword)
            return web_matches

        # ── Strategy 4: LLM suggestion — slowest fallback ────────────────
        llm_matches = self._suggest_subreddits_via_llm(keyword, limit=limit)
        if llm_matches:
            log.info("LLM suggested %d subreddits for %r", len(llm_matches), keyword)
            return llm_matches

        log.warning("All subreddit discovery methods returned 0 for %r", keyword)
        return []

    # -- Keyword → subreddit catalog for zero-HTTP fallback --

    _SUBREDDIT_CATALOG: dict[str, list[str]] = {
        # Business & Entrepreneurship
        "startup": ["startups", "smallbusiness", "Entrepreneur", "SaaS"],
        "business": ["smallbusiness", "Entrepreneur", "business", "startups"],
        "entrepreneur": ["Entrepreneur", "startups", "smallbusiness", "EntrepreneurRideAlong"],
        "saas": ["SaaS", "startups", "Entrepreneur", "webdev"],
        "marketing": ["marketing", "digital_marketing", "socialmedia", "SEO"],
        "seo": ["SEO", "bigseo", "TechSEO", "marketing"],
        "agency": ["digital_marketing", "marketing", "freelance", "agency"],
        # Technology
        "software": ["software", "programming", "webdev", "technology"],
        "ai": ["artificial", "MachineLearning", "ChatGPT", "LocalLLaMA"],
        "tech": ["technology", "gadgets", "programming", "webdev"],
        "web": ["webdev", "web_design", "Frontend", "javascript"],
        "app": ["androiddev", "iOSProgramming", "webdev", "startups"],
        "cloud": ["aws", "googlecloud", "azure", "devops"],
        "devops": ["devops", "sysadmin", "kubernetes", "docker"],
        # Finance & Investment
        "stock": ["stocks", "investing", "wallstreetbets", "StockMarket"],
        "invest": ["investing", "stocks", "personalfinance", "financialindependence"],
        "finance": ["personalfinance", "finance", "investing", "FinancialPlanning"],
        "crypto": ["CryptoCurrency", "Bitcoin", "ethereum", "CryptoMarkets"],
        "trading": ["Daytrading", "stocks", "options", "forex"],
        # India-specific
        "india": ["india", "IndianStockMarket", "indiabusiness", "IndiaTech"],
        "indian": ["india", "IndianStockMarket", "IndianGaming", "IndiaSpeaks"],
        "nse": ["IndianStockMarket", "IndiaInvestments", "IndianStreetBets"],
        "bse": ["IndianStockMarket", "IndiaInvestments", "IndianStreetBets"],
        "steel": ["metalworking", "engineering", "manufacturing", "IndianStockMarket"],
        "manufacturing": ["manufacturing", "engineering", "IndustrialDesign", "metalworking"],
        # E-commerce & Retail
        "ecommerce": ["ecommerce", "shopify", "dropship", "FulfillmentByAmazon"],
        "shopify": ["shopify", "ecommerce", "Entrepreneur", "smallbusiness"],
        "amazon": ["FulfillmentByAmazon", "AmazonSeller", "ecommerce"],
        "retail": ["retail", "ecommerce", "smallbusiness"],
        # Real Estate
        "realestate": ["realestate", "RealEstateInvesting", "FirstTimeHomeBuyer"],
        "property": ["realestate", "RealEstateInvesting", "homeowners"],
        "home": ["HomeImprovement", "homeowners", "InteriorDesign", "realestate"],
        # Health & Wellness
        "health": ["health", "HealthIT", "healthcare", "nutrition"],
        "fitness": ["fitness", "bodybuilding", "running", "loseit"],
        "wellness": ["wellness", "meditation", "yoga", "selfimprovement"],
        # Education
        "education": ["education", "teachers", "edtech", "learnprogramming"],
        "learning": ["learnprogramming", "education", "OnlineLearning"],
        "course": ["OnlineLearning", "udemy", "learnprogramming"],
        # Design
        "design": ["design", "graphic_design", "web_design", "UI_Design"],
        "ui": ["UI_Design", "userexperience", "web_design"],
        "ux": ["userexperience", "UI_Design", "web_design"],
        # General
        "product": ["ProductManagement", "startups", "Entrepreneur"],
        "tool": ["SideProject", "webdev", "productivity", "software"],
        "project": ["SideProject", "startups", "webdev"],
        "freelance": ["freelance", "WorkOnline", "digitalnomad"],
        "remote": ["remotework", "digitalnomad", "WorkOnline"],
    }

    def _suggest_subreddits_from_catalog(self, keyword: str, limit: int = 10) -> list[RedditSubredditMatch]:
        """Suggest subreddits from a hardcoded catalog based on keyword tokens.

        This is the ultimate zero-HTTP fallback.  It uses a mapping of common
        keyword tokens to well-known subreddit communities.  The results are less
        precise than LLM or web search, but they guarantee SOMETHING is always
        returned.
        """
        tokens = set(keyword.lower().split())
        seen: set[str] = set()
        matches: list[RedditSubredditMatch] = []

        for token in tokens:
            for catalog_key, subs in self._SUBREDDIT_CATALOG.items():
                if catalog_key in token or token in catalog_key:
                    for sub in subs:
                        if sub.lower() in seen:
                            continue
                        seen.add(sub.lower())
                        matches.append(
                            RedditSubredditMatch(
                                name=sub,
                                title="",
                                description=f"Suggested from keyword catalog (matched '{catalog_key}')",
                                subscribers=0,
                            )
                        )
                        if len(matches) >= limit:
                            return matches

        return matches

    def _discover_subreddits_via_web_search(self, keyword: str, limit: int = 10) -> list[RedditSubredditMatch]:
        """Discover subreddits via external web search (DDG/Bing/SerpAPI).

        Uses ``site:reddit.com/r/`` queries to find Reddit posts via a web
        search engine, then extracts unique subreddit names from the result
        URLs.  This never touches reddit.com directly.
        """
        queries = [
            f'site:reddit.com/r/ "{keyword}"',
            f'site:reddit.com "{keyword}" subreddit',
        ]

        candidates: dict[str, dict[str, Any]] = {}
        for query in queries:
            try:
                hits = self._search_web(query, limit=max(limit * 3, 12))
            except Exception as exc:  # noqa: BLE001 - keep discovery alive
                log.warning("Subreddit web search failed for %r: %s", query, exc)
                continue

            for hit in hits:
                # Extract subreddit name from any reddit.com URL
                subreddit = _subreddit_from_post_url(hit.url) or _subreddit_from_any_reddit_url(hit.url)
                if not subreddit:
                    continue
                key = subreddit.lower()
                entry = candidates.setdefault(
                    key,
                    {"name": subreddit, "score": 0, "title": "", "description": ""},
                )
                entry["score"] += 2
                if hit.title and not entry["title"]:
                    entry["title"] = hit.title
                if hit.snippet and not entry["description"]:
                    entry["description"] = hit.snippet

        if not candidates:
            return []

        ranked = sorted(candidates.values(), key=lambda item: (item["score"], item["name"]), reverse=True)

        # Build matches WITHOUT calling subreddit_about() — that would hit Reddit.
        # Use the web search metadata instead (title/snippet from DDG).
        matches: list[RedditSubredditMatch] = []
        seen: set[str] = set()
        for entry in ranked:
            key = entry["name"].lower()
            if key in seen or not entry["name"]:
                continue
            seen.add(key)
            matches.append(
                RedditSubredditMatch(
                    name=entry["name"],
                    title=entry.get("title", ""),
                    description=entry.get("description", ""),
                    subscribers=0,  # Unknown without Reddit call — that's OK
                )
            )
            if len(matches) >= limit:
                break

        return matches

    def _suggest_subreddits_via_llm(self, keyword: str, limit: int = 10) -> list[RedditSubredditMatch]:
        """Use the LLM (Gemini) to suggest relevant subreddit names.

        This is a zero-HTTP-to-Reddit fallback.  LLMs have extensive knowledge
        of popular subreddits and their communities.
        """
        try:
            from app.services.infrastructure.llm.service import LLMService

            llm = LLMService()
        except Exception:  # noqa: BLE001
            log.warning("LLM service unavailable for subreddit suggestion")
            return []

        prompt = (
            f'Given the search keyword "{keyword}", suggest the top {limit + 5} most '
            f"relevant active Reddit subreddits where people discuss this topic.\n\n"
            f"Return ONLY a JSON array of objects, each with:\n"
            f'- "name": subreddit name without the r/ prefix\n'
            f'- "description": one-line description of the community\n\n'
            f"Include both niche and popular subreddits. Order by relevance.\n"
            f"Example format: [{{'name': 'stocks', 'description': 'Stock market discussion'}}]"
        )
        import threading

        # Use a short timeout for this non-critical fallback.  When the LLM
        # is rate-limited the provider retries for ~60s — far too long for a
        # discovery fallback.  Cap at 8s so we fail fast and reach Strategy 3.
        result_holder: list[str | None] = [None]
        error_holder: list[Exception | None] = [None]

        def _call_llm() -> None:
            try:
                result_holder[0] = llm.call_text(
                    prompt,
                    system_message="You are a Reddit expert. Respond with valid JSON only.",
                    temperature=0.3,
                    max_tokens=1024,
                )
            except Exception as exc:  # noqa: BLE001
                error_holder[0] = exc

        t = threading.Thread(target=_call_llm, daemon=True)
        t.start()
        t.join(timeout=8)

        if t.is_alive():
            log.info("LLM subreddit suggestion timed out after 8s — skipping")
            return []
        if error_holder[0]:
            log.warning("LLM subreddit suggestion failed: %s", error_holder[0])
            return []
        raw_text = result_holder[0]

        if not raw_text:
            return []

        # Parse JSON from the LLM response text
        try:
            from app.services.infrastructure.llm._json_helpers import parse_json_payload

            result = parse_json_payload(raw_text)
        except Exception:  # noqa: BLE001
            log.debug("Failed to parse LLM subreddit response as JSON")
            return []

        if not isinstance(result, list):
            log.debug("LLM returned non-list for subreddit suggestion: %s", type(result))
            return []

        matches: list[RedditSubredditMatch] = []
        seen: set[str] = set()
        for item in result:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip().removeprefix("r/").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            matches.append(
                RedditSubredditMatch(
                    name=name,
                    title="",
                    description=(item.get("description") or "")[:300],
                    subscribers=0,
                )
            )
            if len(matches) >= limit:
                break

        log.info("LLM suggested %d subreddits for %r", len(matches), keyword)
        return matches

    def list_subreddit_posts(self, subreddit: str, sort: str = "hot", limit: int = 10) -> list[RedditPost]:
        """List posts from a subreddit.

        Tries the public JSON feed first; if Reddit blocks it (403), falls
        back to the Atom/RSS feed which remains accessible.
        """
        feed_sort = sort if sort in {"hot", "new", "top"} else "hot"
        params: dict[str, Any] = {"limit": min(limit, 100), "raw_json": 1}
        if feed_sort == "top":
            params["t"] = "month"

        # Try JSON first
        try:
            data = self._reddit_json(f"/r/{subreddit}/{feed_sort}.json", params=params, cache_ttl=_POST_CACHE_TTL)
            posts: list[RedditPost] = []
            for child in data.get("data", {}).get("children", []):
                post = self._parse_post_payload(child.get("data", {}), subreddit)
                if post and post.subreddit.lower() == subreddit.lower():
                    posts.append(post)
            if posts:
                return posts[:limit]
        except Exception as exc:
            log.debug("JSON feed for r/%s failed (%s), trying RSS", subreddit, exc)

        # Fall back to RSS
        return self._list_subreddit_posts_rss(subreddit, sort=feed_sort, limit=limit)

    def _list_subreddit_posts_rss(self, subreddit: str, *, sort: str, limit: int) -> list[RedditPost]:
        """Fetch subreddit posts via RSS — batch parse, NO per-post hydration.

        Parses all posts directly from the feed XML. Each <entry> contains
        title, author, body (content), and link, so ONE HTTP request yields
        up to 25 posts instead of requiring individual requests per post.
        """
        rss_url = f"{self._reddit_base_url}/r/{subreddit}/{sort}.rss"
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if sort == "top":
            params["t"] = "month"

        try:
            resp = self._request("GET", rss_url, params=params)
        except Exception as exc:
            log.warning("RSS feed failed for r/%s: %s", subreddit, exc)
            return []

        soup = _parse_rss(resp.text)
        posts: list[RedditPost] = []
        for entry in soup.find_all("entry"):
            post = _parse_rss_entry(entry, expected_subreddit=subreddit)
            if post:
                posts.append(post)
            if len(posts) >= limit:
                break
        return posts

    def subreddit_about(self, subreddit: str) -> dict[str, Any]:
        """Fetch subreddit metadata from the public `about.json` endpoint."""
        try:
            data = self._reddit_json(
                f"/r/{subreddit}/about.json",
                params={"raw_json": 1},
                cache_ttl=_SUBREDDIT_CACHE_TTL,
            )
        except httpx.HTTPError:
            return {}
        return data.get("data", {})

    def subreddit_rules(self, subreddit: str) -> list[str]:
        """Fetch subreddit rules from the public rules endpoint."""
        try:
            data = self._reddit_json(
                f"/r/{subreddit}/about/rules.json",
                params={"raw_json": 1},
                cache_ttl=_SUBREDDIT_CACHE_TTL,
            )
        except httpx.HTTPError:
            return []
        rules: list[str] = []
        for rule in data.get("rules", []):
            short_name = rule.get("short_name")
            description = rule.get("description")
            if short_name and description:
                rules.append(f"{short_name}: {description}")
            elif short_name:
                rules.append(short_name)
        return rules

    def _search_posts_via_external_search(
        self,
        keywords: list[str],
        *,
        allowed_subreddits: set[str],
        limit: int,
    ) -> list[RedditPost]:
        queries = self._build_external_queries(keywords, subreddits=allowed_subreddits or None, limit=4)
        posts_by_id: dict[str, RedditPost] = {}
        max_detail_fetches = max(limit * max(len(allowed_subreddits), 1), limit * 2)

        for query in queries:
            hits = self._search_web(query, limit=max(limit * 2, 8))
            for hit in hits:
                post_url = _normalize_reddit_post_url(hit.url)
                if not post_url:
                    continue
                subreddit_name = _subreddit_from_post_url(post_url)
                if allowed_subreddits and (not subreddit_name or subreddit_name.lower() not in allowed_subreddits):
                    continue
                # Try JSON hydration first, fall back to RSS
                post = self._fetch_post_from_url(post_url)
                if not post:
                    post = self._fetch_post_from_rss(post_url)
                if not post:
                    continue
                posts_by_id[post.post_id] = post
                if len(posts_by_id) >= max_detail_fetches:
                    break
            if len(posts_by_id) >= max_detail_fetches:
                break

        return list(posts_by_id.values())

    def _search_posts_in_subreddit_feed(
        self,
        subreddit: str,
        keywords: list[str],
        *,
        limit: int,
    ) -> list[RedditPost]:
        """Fetch posts from subreddit feeds and pass ALL to the scorer.

        No keyword pre-filter — the RelevanceEngine handles filtering properly.
        The old _matches_keywords gate was dropping ~90% of posts before they
        could be scored, causing 0 opportunities.
        """
        posts: dict[str, RedditPost] = {}
        for sort in ("new", "top"):
            for post in self._paginate_subreddit_feed(subreddit, sort=sort, limit=max(limit * 2, 20)):
                posts[post.post_id] = post
        return _rerank_by_keyword_relevance(list(posts.values()), keywords)[:limit]

    def _paginate_subreddit_feed(self, subreddit: str, *, sort: str, limit: int) -> list[RedditPost]:
        """Fetch subreddit posts via RSS (JSON endpoints are blocked by Reddit).

        Goes straight to RSS batch parsing — no wasted 403 JSON attempts.
        """
        return self._list_subreddit_posts_rss(subreddit, sort=sort, limit=limit)

    def fetch_post_comments(
        self,
        post_url: str,
        *,
        post_id: str,
        subreddit: str,
        parent_post_title: str,
        limit: int = 15,
    ) -> list[RedditComment]:
        """Fetch comments from a single post's RSS feed.

        Reddit's per-post RSS (``{permalink}/.rss``) returns the post as
        ``entries[0]`` and comments as ``entries[1:]``. This method parses
        only the comments — one HTTP request yields ~25 comments.

        Comments are where users ask for recommendations, alternatives, and
        help — the highest-value opportunity sources.
        """
        import contextlib
        import html as html_mod

        rss_url = post_url.rstrip("/") + "/.rss"
        try:
            resp = self._request("GET", rss_url)
        except Exception as exc:
            log.debug("Comment RSS fetch failed for %s: %s", post_url, exc)
            return []

        soup = _parse_rss(resp.text)
        entries = soup.find_all("entry")
        if len(entries) < 2:
            return []  # No comments (entries[0] is the post itself)

        comments: list[RedditComment] = []
        for entry in entries[1:]:  # Skip entries[0] which is the post
            # Comment link
            link_el = entry.find("link")
            comment_url = link_el.get("href", "") if link_el else ""

            # Comment ID from URL (last path segment)
            comment_id = ""
            if comment_url:
                segments = [s for s in comment_url.rstrip("/").split("/") if s]
                if segments:
                    comment_id = segments[-1]

            if not comment_id:
                continue

            # Body
            body = ""
            content_el = entry.find("content")
            if content_el:
                raw = html_mod.unescape(content_el.decode_contents())
                body_soup = BeautifulSoup(raw, "html.parser")
                body = body_soup.get_text(" ", strip=True)

            # Skip very short comments (< 20 chars — likely just emojis/links)
            if len(body) < 20:
                continue

            # Author
            author = ""
            author_el = entry.find("author")
            if author_el:
                name_el = author_el.find("name")
                author = name_el.text.removeprefix("/u/").strip() if name_el else ""

            # Timestamp
            created_at = None
            updated_el = entry.find("updated")
            if updated_el and updated_el.text:
                with contextlib.suppress(ValueError, TypeError):
                    dt_str = updated_el.text.strip()
                    if dt_str.endswith("Z"):
                        dt_str = dt_str[:-1] + "+00:00"
                    created_at = datetime.fromisoformat(dt_str).replace(tzinfo=None)

            comments.append(RedditComment(
                comment_id=comment_id,
                post_id=post_id,
                subreddit=subreddit,
                author=author or "[deleted]",
                body=body,
                permalink=comment_url or post_url,
                score=0,  # RSS doesn't expose comment scores
                created_at=created_at,
                parent_post_title=parent_post_title,
            ))

            if len(comments) >= limit:
                break

        log.info("Fetched %d comments from %s", len(comments), post_url)
        return comments

    def _fetch_post_from_url(self, post_url: str) -> RedditPost | None:
        json_url = _json_url_for_post(post_url)
        if not json_url:
            return None
        try:
            data = self._request_json(json_url, params={"raw_json": 1, "limit": 1}, cache_ttl=_POST_CACHE_TTL)
        except httpx.HTTPError as exc:
            log.debug("Failed to hydrate post %s: %s", post_url, exc)
            return None

        if not isinstance(data, list) or not data:
            return None
        children = data[0].get("data", {}).get("children", [])
        if not children:
            return None
        payload = children[0].get("data", {})
        subreddit = payload.get("subreddit") or _subreddit_from_post_url(post_url) or ""
        return self._parse_post_payload(payload, subreddit)

    def _search_web(self, query: str, *, limit: int) -> list[SearchResult]:
        provider = self._resolve_search_provider()
        cache_key = f"search:{provider}:{query}:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        results: list[SearchResult] = []
        if provider == "serpapi":
            results = self._search_serpapi(query, limit=limit)
        elif provider == "bing":
            results = self._search_bing(query, limit=limit)
        elif provider == "reddit":
            # Skip DDG entirely — go straight to Reddit RSS search
            pass
        else:
            try:
                results = self._search_duckduckgo(query, limit=limit)
            except Exception as exc:
                log.debug("DuckDuckGo failed for %r: %s", query, exc)

        # DuckDuckGo is often broken (JS SPA / connection reset). Always try
        # Reddit's RSS search as a fallback when external search fails.
        # Only fall back to Reddit native search if the circuit is not open.
        # When Reddit is rate-limiting, trying again here wastes time and
        # delays the caller (pipeline/scanner) by the backoff sleep.
        reddit_circuit_open = any(_HTTP_BUDGET.is_open(h) for h in _REDDIT_HOSTS)
        if not results and not reddit_circuit_open:
            try:
                reddit_results = self._search_reddit_native(query, limit=limit)
                if reddit_results:
                    results = reddit_results
            except Exception as exc:
                log.debug("Reddit native search failed for %r: %s", query, exc)

        self._set_cached(cache_key, results, ttl=_SEARCH_RESULT_CACHE_TTL)
        return results

    def _resolve_search_provider(self) -> str:
        if self._search_provider in {"serpapi", "bing", "duckduckgo", "reddit"}:
            return self._search_provider
        if self._serpapi_api_key:
            return "serpapi"
        if self._bing_search_api_key:
            return "bing"
        return "duckduckgo"

    def _search_serpapi(self, query: str, *, limit: int) -> list[SearchResult]:
        if not self._serpapi_api_key:
            raise RuntimeError("SERPAPI_API_KEY is not configured.")
        data = self._request_json(
            "https://serpapi.com/search.json",
            params={
                "api_key": self._serpapi_api_key,
                "engine": "google",
                "num": min(limit, 10),
                "q": query,
            },
            cache_ttl=_SEARCH_RESULT_CACHE_TTL,
        )
        results: list[SearchResult] = []
        for item in data.get("organic_results", []):
            url = item.get("link") or ""
            if not url:
                continue
            results.append(
                SearchResult(
                    url=url,
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                )
            )
        return results

    def _search_bing(self, query: str, *, limit: int) -> list[SearchResult]:
        if not self._bing_search_api_key:
            raise RuntimeError("BING_SEARCH_API_KEY is not configured.")
        data = self._request_json(
            self._bing_search_url,
            params={"count": min(limit, 20), "q": query},
            headers={"Ocp-Apim-Subscription-Key": self._bing_search_api_key},
            cache_ttl=_SEARCH_RESULT_CACHE_TTL,
        )
        results: list[SearchResult] = []
        for item in data.get("webPages", {}).get("value", []):
            url = item.get("url") or ""
            if not url:
                continue
            results.append(
                SearchResult(
                    url=url,
                    title=item.get("name", ""),
                    snippet=item.get("snippet", ""),
                )
            )
        return results

    def _search_duckduckgo(self, query: str, *, limit: int) -> list[SearchResult]:
        html = self._request_text(
            self._duckduckgo_search_url,
            params={"q": query},
            cache_ttl=_SEARCH_RESULT_CACHE_TTL,
        )
        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResult] = []

        # Try multiple CSS selector patterns — DDG changes markup often
        selectors = [
            (".result", "a.result__a", ".result__snippet"),
            (".web-result", "h2 a[href]", ".result__snippet"),
            (".results article", "h2 a[href]", "p"),
            ("article[data-testid='result']", "a[href]", "span"),
        ]
        used_fallback = False
        for container_sel, link_sel, snippet_sel in selectors:
            containers = soup.select(container_sel)
            if not containers:
                continue
            for container in containers:
                link = container.select_one(link_sel) if link_sel else container
                if link is None:
                    continue
                href = _resolve_search_result_url(link.get("href", ""))
                if not href:
                    continue
                snippet_node = container.select_one(snippet_sel) if snippet_sel else None
                results.append(
                    SearchResult(
                        url=href,
                        title=link.get_text(" ", strip=True),
                        snippet=snippet_node.get_text(" ", strip=True) if snippet_node else "",
                    )
                )
                if len(results) >= limit:
                    break
            if results:
                break
            used_fallback = container_sel != selectors[0][0]

        if results:
            return results

        if not used_fallback:
            # Looser anchor scan as last resort
            for link in soup.select("a[href]"):
                href = _resolve_search_result_url(link.get("href", ""))
                if not href:
                    continue
                results.append(
                    SearchResult(
                        url=href,
                        title=link.get_text(" ", strip=True),
                        snippet="",
                    )
                )
                if len(results) >= limit:
                    break
        return results

    def _search_reddit_native(self, query: str, *, limit: int) -> list[SearchResult]:
        """Fall back to Reddit's public RSS search when external search fails.

        Reddit blocks the JSON search API (403), but the Atom/RSS feed at
        ``/search.rss`` still works with a descriptive User-Agent.
        """
        # Clean up query for Reddit search — strip DDG/external-search syntax
        clean_query = query
        for prefix in ("site:reddit.com ", "site:reddit.com"):
            if clean_query.lower().startswith(prefix):
                clean_query = clean_query[len(prefix):]
                break
        # Strip subreddit prefix like "/r/subreddit " added by _build_external_queries
        import re as _re

        clean_query = _re.sub(r"^/r/\w+\s+", "", clean_query)
        # Remove surrounding quotes
        clean_query = clean_query.strip('"').strip("'")
        clean_query = clean_query.strip()
        if not clean_query:
            return []

        try:
            resp = self._request(
                "GET",
                f"{self._reddit_base_url}/search.rss",
                params={
                    "q": clean_query,
                    "sort": "relevance",
                    "t": "month",
                    "limit": min(limit, 25),
                },
            )
        except Exception as exc:
            log.debug("Reddit RSS search failed for %r: %s", clean_query, exc)
            return []

        import warnings

        from bs4 import XMLParsedAsHTMLWarning  # noqa: F811

        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(resp.text, "html.parser")

        results: list[SearchResult] = []
        for entry in soup.find_all("entry"):
            title_el = entry.find("title")
            link_el = entry.find("link")
            if not link_el:
                continue
            url = link_el.get("href", "")
            if not url:
                continue
            # Skip subreddit listing pages (only want comment/post links)
            if "/comments/" not in url:
                continue
            results.append(
                SearchResult(
                    url=url,
                    title=title_el.text.strip() if title_el else "",
                    snippet="",
                )
            )
            if len(results) >= limit:
                break
        return results

    def _fetch_post_from_rss(self, post_url: str) -> RedditPost | None:
        """Hydrate a single Reddit post via its Atom/RSS feed.

        Reddit blocks the ``.json`` endpoint for unauthenticated clients,
        but ``{permalink}/.rss`` still returns the post content.
        """
        rss_url = post_url.rstrip("/") + "/.rss"
        try:
            resp = self._request("GET", rss_url)
        except Exception as exc:
            log.debug("Reddit RSS hydration failed for %s: %s", post_url, exc)
            return None

        import html
        import warnings

        from bs4 import XMLParsedAsHTMLWarning  # noqa: F811

        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(resp.text, "html.parser")
        entries = soup.find_all("entry")
        if not entries:
            return None

        # First entry is the post itself; subsequent entries are comments
        post_entry = entries[0]
        title = post_entry.find("title")
        title_text = title.text.strip() if title else ""

        # Parse permalink for post_id and subreddit
        normalized = _normalize_reddit_post_url(post_url)
        if not normalized:
            return None
        path_segments = [s for s in urlsplit(normalized).path.split("/") if s]
        if len(path_segments) < 4:
            return None
        subreddit = path_segments[1]
        post_id = path_segments[3]

        # Extract body from content (HTML-escaped in RSS)
        content_el = post_entry.find("content")
        body = ""
        if content_el:
            # RSS wraps content in HTML entities — unescape first
            raw = html.unescape(content_el.decode_contents())
            body_soup = BeautifulSoup(raw, "html.parser")
            body = body_soup.get_text(" ", strip=True)
            # Strip common prefixes from self-posts
            for prefix in ("<!-- SC_OFF -->", "<!-- SC_ON -->"):
                body = body.replace(prefix, "").strip()

        # Extract author
        author_el = post_entry.find("author")
        author_name = ""
        if author_el:
            name_el = author_el.find("name")
            author_name = name_el.text.removeprefix("/u/").strip() if name_el else ""

        # Try to get score from the XML (sometimes present as <media:statistics>)
        score = 0
        stats = post_entry.find("media:statistics")
        if stats:
            score = int(stats.get("views", 0))

        # Parse updated time as created_at
        import contextlib

        updated_el = post_entry.find("updated")
        created_at = datetime.now(UTC)
        if updated_el and updated_el.text:
            with contextlib.suppress(ValueError, TypeError):
                created_at = datetime.fromisoformat(updated_el.text.replace("Z", "+00:00"))

        return RedditPost(
            post_id=post_id,
            subreddit=subreddit,
            title=title_text,
            author=author_name or "[unknown]",
            permalink=normalized,
            body=body,
            created_at=created_at,
            num_comments=len(entries) - 1,
            score=score,
        )

    def _request_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cache_ttl: float = 0.0,
    ) -> Any:
        cache_key = f"json:{url}?{urlencode(sorted((params or {}).items()), doseq=True)}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        response = self._request("GET", url, params=params, headers=headers)
        payload = response.json()
        if cache_ttl > 0:
            self._set_cached(cache_key, payload, ttl=cache_ttl)
        return payload

    def _request_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cache_ttl: float = 0.0,
    ) -> str:
        cache_key = f"text:{url}?{urlencode(sorted((params or {}).items()), doseq=True)}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        response = self._request("GET", url, params=params, headers=headers)
        payload = response.text
        if cache_ttl > 0:
            self._set_cached(cache_key, payload, ttl=cache_ttl)
        return payload

    def _reddit_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        cache_ttl: float,
    ) -> Any:
        return self._request_json(f"{self._reddit_base_url}{path}", params=params, cache_ttl=cache_ttl)

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        host = urlsplit(url).netloc.lower()
        response: httpx.Response | None = None

        for attempt in range(2):
            _HTTP_BUDGET.acquire(host)  # raises CircuitOpenError when the host is cooling down
            try:
                response = self._client.request(method, url, params=params, headers=headers)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                _HTTP_BUDGET.record_failure(host)
                if attempt == 1:
                    raise
                wait = _HTTP_BUDGET.backoff_delay(attempt)
                log.warning("Connection error on %s (attempt %d/2): %s", url, attempt + 1, exc)
                time.sleep(wait)
                continue

            if response.status_code in {429, 500, 502, 503, 504}:
                _HTTP_BUDGET.record_failure(host)
                if attempt < 1:
                    wait = _HTTP_BUDGET.backoff_delay(attempt, retry_after=response.headers.get("Retry-After"))
                    log.warning(
                        "Transient HTTP %d on %s (attempt %d/2); retrying in %.1fs",
                        response.status_code,
                        url,
                        attempt + 1,
                        wait,
                    )
                    time.sleep(wait)
                    continue

            response.raise_for_status()
            _HTTP_BUDGET.record_success(host)
            return response

        if response is None:
            raise RuntimeError(f"Request did not execute for {url}")
        response.raise_for_status()
        return response

    def _merge_posts(
        self,
        posts_by_id: dict[str, RedditPost],
        posts: list[RedditPost],
        allowed_subreddits: set[str],
    ) -> None:
        for post in posts:
            if allowed_subreddits and post.subreddit.lower() not in allowed_subreddits:
                continue
            if not post.post_id or not post.title:
                continue
            posts_by_id[post.post_id] = post

    def _parse_post_payload(self, payload: dict[str, Any], subreddit: str) -> RedditPost | None:
        post_id = payload.get("id", "")
        title = payload.get("title", "")
        permalink = payload.get("permalink", "")
        if not post_id or not title or not permalink:
            return None

        created_ts = float(payload.get("created_utc") or 0.0)
        permalink_url = permalink if permalink.startswith("http") else f"https://www.reddit.com{permalink}"
        post_subreddit = payload.get("subreddit") or subreddit
        return RedditPost(
            post_id=post_id,
            subreddit=post_subreddit,
            title=title,
            author=payload.get("author", "[deleted]"),
            permalink=permalink_url,
            body=payload.get("selftext", "") or "",
            created_at=datetime.fromtimestamp(created_ts, tz=UTC) if created_ts else datetime.now(UTC),
            num_comments=int(payload.get("num_comments") or 0),
            score=int(payload.get("score") or 0),
        )

    def _matches_keywords(self, post: RedditPost, keywords: list[str]) -> bool:
        text = f"{post.title} {post.body}".lower()
        token_set = set(tokenize(text))
        for keyword in keywords:
            normalized = keyword.lower()
            if normalized in text:
                return True
            if len(normalized.split()) > 1 and has_meaningful_phrase_overlap(normalized, token_set):
                return True
        return False

    def _build_external_queries(
        self,
        keywords: list[str],
        *,
        subreddits: set[str] | None,
        limit: int,
    ) -> list[str]:
        queries: list[str] = []
        seen: set[str] = set()

        for keyword in keywords[:6]:
            variants = _search_keyword_variants(keyword)[:2]
            for variant in variants:
                query = self._format_external_query(variant, subreddits=subreddits)
                if query in seen:
                    continue
                queries.append(query)
                seen.add(query)
                if len(queries) >= limit:
                    return queries

        return queries

    def _format_external_query(self, keyword: str, *, subreddits: set[str] | None) -> str:
        if subreddits and len(subreddits) == 1:
            subreddit = next(iter(subreddits))
            return f'site:reddit.com/r/{subreddit}/comments "{keyword}"'
        return f'site:reddit.com/r/ "{keyword}"'

    def _normalize_keywords(self, keywords: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for keyword in keywords:
            cleaned = " ".join((keyword or "").strip().replace('"', "").split())
            if len(cleaned) < 2:
                continue
            lowered = cleaned.lower()
            if lowered in seen:
                continue
            normalized.append(cleaned)
            seen.add(lowered)
        return normalized[:12]

    def _get_cached(self, key: str) -> Any | None:
        cached = _CACHE.get(key)
        if cached is None:
            return None
        expires_at, value = cached
        if expires_at < time.monotonic():
            _CACHE.pop(key, None)
            return None
        return value

    def _set_cached(self, key: str, value: Any, *, ttl: float) -> None:
        if len(_CACHE) >= _CACHE_MAX_ENTRIES:
            now = time.monotonic()
            expired_keys = [cached_key for cached_key, (expires_at, _) in _CACHE.items() if expires_at < now]
            for cached_key in expired_keys:
                _CACHE.pop(cached_key, None)
            if len(_CACHE) >= _CACHE_MAX_ENTRIES and _CACHE:
                oldest_key = min(_CACHE.items(), key=lambda item: item[1][0])[0]
                _CACHE.pop(oldest_key, None)
        _CACHE[key] = (time.monotonic() + ttl, value)


def _resolve_search_result_url(href: str) -> str | None:
    if not href:
        return None
    if href.startswith("//"):
        href = f"https:{href}"
    if "duckduckgo.com/l/?" in href:
        uddg = parse_qs(urlsplit(href).query).get("uddg")
        if not uddg:
            return None
        return unquote(uddg[0])
    return href


def _normalize_reddit_post_url(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.netloc.lower() not in _REDDIT_HOSTS:
        return None
    match = _VALID_REDDIT_POST_PATH.match(parts.path)
    if not match:
        return None
    subreddit = match.group(1)
    post_id = match.group(2)
    path_segments = [segment for segment in parts.path.split("/") if segment]
    canonical_path = f"/r/{subreddit}/comments/{post_id}"
    if len(path_segments) >= 5:
        canonical_path += f"/{path_segments[4]}"
    return f"https://www.reddit.com{canonical_path}"


def _subreddit_from_post_url(url: str) -> str | None:
    normalized = _normalize_reddit_post_url(url)
    if not normalized:
        return None
    path_segments = [segment for segment in urlsplit(normalized).path.split("/") if segment]
    if len(path_segments) < 2 or path_segments[0].lower() != "r":
        return None
    return path_segments[1]


def _subreddit_from_any_reddit_url(url: str) -> str | None:
    """Extract subreddit name from any reddit.com URL (not just post URLs).

    Handles URLs like:
    - https://www.reddit.com/r/startups/
    - https://old.reddit.com/r/stocks/wiki/...
    - https://reddit.com/r/IndianStockMarket/comments/...
    """
    try:
        parsed = urlsplit(url)
    except Exception:  # noqa: BLE001
        return None
    host = (parsed.netloc or "").lower()
    if "reddit.com" not in host:
        return None
    segments = [s for s in parsed.path.split("/") if s]
    if len(segments) >= 2 and segments[0].lower() == "r":
        name = segments[1]
        # Filter out non-subreddit paths
        if name.lower() not in {"comments", "search", "user", "wiki", "about", "submit"}:
            return name
    return None


def _json_url_for_post(url: str) -> str | None:
    normalized = _normalize_reddit_post_url(url)
    if not normalized:
        return None
    return f"{normalized.rstrip('/')}.json"
