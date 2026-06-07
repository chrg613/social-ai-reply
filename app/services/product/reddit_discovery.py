"""Credential-free Reddit discovery service.

This service keeps the scan pipeline working without Reddit OAuth by combining:
1. External web search for Reddit thread URLs.
2. Public subreddit JSON feeds (`new.json` / `top.json` / `hot.json`).

It normalizes everything into `RedditPost` objects so scoring, opportunity
creation, and drafting continue to use the existing contracts.
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
from app.services.product.reddit import (
    RedditPost,
    RedditSubredditMatch,
    _rerank_by_keyword_relevance,
    _search_keyword_variants,
)
from app.services.product.relevance import has_meaningful_phrase_overlap, tokenize

log = logging.getLogger("redditflow.reddit_discovery")

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
_MIN_INTERVAL_BY_HOST = {
    "api.bing.microsoft.com": 0.25,
    "html.duckduckgo.com": 0.75,
    "serpapi.com": 0.25,
    "www.reddit.com": 0.5,
}


@dataclass(slots=True)
class SearchResult:
    url: str
    title: str = ""
    snippet: str = ""


class RedditDiscoveryService:
    """Discover Reddit posts and subreddit metadata without Reddit OAuth."""

    # Class-level flag: once DDG fails once, skip it for all future instances
    _ddg_disabled: bool = False

    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._search_provider = (settings.reddit_search_provider or "auto").strip().lower()
        self._serpapi_api_key = (settings.serpapi_api_key or "").strip()
        self._bing_search_api_key = (settings.bing_search_api_key or "").strip()
        self._duckduckgo_search_url = settings.duckduckgo_search_url
        self._bing_search_url = settings.bing_search_url
        self._reddit_base_url = settings.reddit_base_url.rstrip("/")
        self._last_request_time_by_host: dict[str, float] = {}
        self._client = httpx.Client(
            headers={
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": settings.reddit_user_agent,
            },
            timeout=12.0,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RedditDiscoveryService:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def search_posts(
        self,
        keywords: list[str],
        subreddits: list[str] | None = None,
        *,
        limit: int = 20,
    ) -> list[RedditPost]:
        """Search Reddit posts using external search plus subreddit feeds.

        When *subreddits* are provided, the *limit* is applied per subreddit.
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

        # Mode A: external search discovers thread URLs and then hydrates the
        # thread details through public Reddit JSON.
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
            successful_modes += 1
            self._merge_posts(posts_by_id, external_posts, allowed_subreddits)

        # Mode B: direct subreddit feed scraping from public JSON endpoints.
        if allowed_subreddits:
            for subreddit in sorted(allowed_subreddits):
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

        if successful_modes == 0 and mode_errors:
            sample = "; ".join(mode_errors[:3])
            raise BusinessRuleError(
                f"All Reddit discovery methods failed. Sample errors: {sample[:400]}"
            )

        overall_limit = limit * max(len(allowed_subreddits), 1)
        return _rerank_by_keyword_relevance(list(posts_by_id.values()), ordered_keywords)[:overall_limit]

    def search_subreddits(self, keyword: str, limit: int = 10) -> list[RedditSubredditMatch]:
        """Infer subreddit candidates from external search results."""
        queries = self._build_external_queries([keyword], subreddits=None, limit=3)
        candidates: dict[str, dict[str, Any]] = {}

        for query in queries:
            try:
                hits = self._search_web(query, limit=max(limit * 3, 12))
            except Exception as exc:  # noqa: BLE001 - keep discovery alive
                log.warning("Subreddit web search failed for %r: %s", query, exc)
                continue

            for hit in hits:
                post_url = _normalize_reddit_post_url(hit.url)
                if not post_url:
                    continue
                subreddit = _subreddit_from_post_url(post_url)
                if not subreddit:
                    continue
                key = subreddit.lower()
                entry = candidates.setdefault(
                    key,
                    {
                        "name": subreddit,
                        "score": 0,
                        "title": "",
                        "description": "",
                    },
                )
                entry["score"] += 2
                if hit.title and not entry["title"]:
                    entry["title"] = hit.title
                if hit.snippet and not entry["description"]:
                    entry["description"] = hit.snippet

        ranked_names = [
            entry["name"]
            for entry in sorted(candidates.values(), key=lambda item: (item["score"], item["name"]), reverse=True)
        ][: max(limit * 2, limit)]

        matches: list[RedditSubredditMatch] = []
        for subreddit in ranked_names:
            about = self.subreddit_about(subreddit)
            if about:
                matches.append(
                    RedditSubredditMatch(
                        name=about.get("display_name", subreddit),
                        title=about.get("title", ""),
                        description=about.get("public_description", "") or about.get("description", ""),
                        subscribers=int(about.get("subscribers") or 0),
                    )
                )
            else:
                fallback = candidates.get(subreddit.lower(), {})
                matches.append(
                    RedditSubredditMatch(
                        name=subreddit,
                        title=fallback.get("title", ""),
                        description=fallback.get("description", ""),
                        subscribers=0,
                    )
                )

        deduped: list[RedditSubredditMatch] = []
        seen: set[str] = set()
        for match in matches:
            key = match.name.lower()
            if not match.name or key in seen:
                continue
            deduped.append(match)
            seen.add(key)
            if len(deduped) >= limit:
                break
        return deduped

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
        """Fetch subreddit posts via the Atom/RSS feed (bypasses 403 on JSON)."""
        rss_url = f"{self._reddit_base_url}/r/{subreddit}/{sort}.rss"
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if sort == "top":
            params["t"] = "month"

        try:
            resp = self._request("GET", rss_url, params=params)
        except Exception as exc:
            log.warning("RSS feed failed for r/%s: %s", subreddit, exc)
            return []

        import warnings

        from bs4 import XMLParsedAsHTMLWarning  # noqa: F811

        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(resp.text, "html.parser")

        posts: list[RedditPost] = []
        for entry in soup.find_all("entry"):
            link_el = entry.find("link")
            if not link_el:
                continue
            url = link_el.get("href", "")
            if not url or "/comments/" not in url:
                continue
            post = self._fetch_post_from_rss(url)
            if post and post.subreddit.lower() == subreddit.lower():
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
        posts: dict[str, RedditPost] = {}
        for sort in ("new", "top"):
            for post in self._paginate_subreddit_feed(subreddit, sort=sort, limit=max(limit * 2, 20)):
                if not self._matches_keywords(post, keywords):
                    continue
                posts[post.post_id] = post
        return _rerank_by_keyword_relevance(list(posts.values()), keywords)[:limit]

    def _paginate_subreddit_feed(self, subreddit: str, *, sort: str, limit: int) -> list[RedditPost]:
        posts: list[RedditPost] = []
        after: str | None = None
        remaining = limit

        while remaining > 0:
            params: dict[str, Any] = {
                "after": after,
                "limit": min(remaining, 100),
                "raw_json": 1,
            }
            if sort == "top":
                params["t"] = "month"
            try:
                data = self._reddit_json(
                    f"/r/{subreddit}/{sort}.json",
                    params=params,
                    cache_ttl=_POST_CACHE_TTL,
                )
            except Exception:
                # JSON feed blocked — fall back to RSS for remaining posts
                rss_posts = self._list_subreddit_posts_rss(subreddit, sort=sort, limit=remaining)
                posts.extend(rss_posts)
                break

            children = data.get("data", {}).get("children", [])
            if not children:
                break

            for child in children:
                post = self._parse_post_payload(child.get("data", {}), subreddit)
                if post:
                    posts.append(post)
                    remaining -= 1
                    if remaining <= 0:
                        break

            after = data.get("data", {}).get("after")
            if not after:
                break

        return posts

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
                # Disable DDG for all future calls in this process
                RedditDiscoveryService._ddg_disabled = True
                log.info("DuckDuckGo disabled for remaining searches in this process")

        # DuckDuckGo is often broken (JS SPA / connection reset). Always try
        # Reddit's RSS search as a fallback when external search fails.
        if not results:
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
        # If DDG has failed before, skip it entirely
        if self._ddg_disabled:
            return "reddit"
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

        for result in soup.select(".result"):
            link = result.select_one("a.result__a")
            if link is None:
                continue
            href = _resolve_search_result_url(link.get("href", ""))
            if not href:
                continue
            snippet_node = result.select_one(".result__snippet")
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
            return results

        # DuckDuckGo occasionally changes the result markup. Fall back to a
        # looser anchor scan instead of treating it as a hard failure.
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

        for attempt in range(3):
            self._throttle(host)
            try:
                response = self._client.request(method, url, params=params, headers=headers)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt == 2:
                    raise
                wait = min(2 ** attempt, 4)
                log.warning("Connection error on %s (attempt %d/3): %s", url, attempt + 1, exc)
                time.sleep(wait)
                continue

            self._last_request_time_by_host[host] = time.monotonic()
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                wait = min(2 ** attempt, 4)
                log.warning(
                    "Transient HTTP %d on %s (attempt %d/3); retrying in %ss",
                    response.status_code,
                    url,
                    attempt + 1,
                    wait,
                )
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response

        if response is None:
            raise RuntimeError(f"Request did not execute for {url}")
        response.raise_for_status()
        return response

    def _throttle(self, host: str) -> None:
        min_interval = _MIN_INTERVAL_BY_HOST.get(host, 0.5)
        last_request_time = self._last_request_time_by_host.get(host, 0.0)
        elapsed = time.monotonic() - last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

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


def _json_url_for_post(url: str) -> str | None:
    normalized = _normalize_reddit_post_url(url)
    if not normalized:
        return None
    return f"{normalized.rstrip('/')}.json"
