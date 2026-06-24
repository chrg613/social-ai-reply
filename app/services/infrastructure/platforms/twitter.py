"""Twitter/X platform adapter — powered by RapidAPI (twitter154.p.rapidapi.com).

Uses "The Old Bird" Twitter API (v0.1.0) from the RapidAPI marketplace.

Verified endpoints:
  - POST /search/search              — keyword search (body JSON)
  - POST /search/search/continuation — paginated search continuation
  - GET/POST /user/details           — user profile lookup
  - GET/POST /user/tweets            — user timeline

Search strategy:
  1. Build query from keywords with ``-is:retweet lang:en`` filters
  2. POST to /search/search with ``section="top"`` for quality results
  3. Parse tweet objects into UnifiedPost
"""
from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.infrastructure.platforms.base import PlatformAdapter
from app.services.infrastructure.platforms.models import UnifiedComment, UnifiedPost
from app.services.infrastructure.platforms.rapidapi_client import RapidAPIClient, RapidAPIError

logger = logging.getLogger(__name__)

DEFAULT_TWITTER_API_HOST = "twitter154.p.rapidapi.com"

# Twitter's ``creation_date`` format: "Thu Jun 19 12:34:56 +0000 2025"
_TWITTER_DATE_FMT = "%a %b %d %H:%M:%S %z %Y"


class TwitterAdapter(PlatformAdapter):
    """Twitter/X adapter using RapidAPI (twitter154 — The Old Bird).

    The twitter154 API uses POST bodies for search, but
    :class:`RapidAPIClient` only exposes a ``get()`` helper.  For POST
    endpoints we fall back to raw ``httpx`` calls while reusing the same
    RapidAPI headers for authentication.
    """

    platform_name = "twitter"

    def __init__(self, api_host: str | None = None) -> None:
        self.api_host = api_host or DEFAULT_TWITTER_API_HOST
        try:
            self.client = RapidAPIClient(self.api_host)
            self._available = True
        except ValueError:
            logger.warning("RapidAPI key not configured — Twitter adapter disabled")
            self._available = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_headers(self) -> dict[str, str]:
        """Build RapidAPI auth headers for raw httpx requests."""
        settings = get_settings()
        return {
            "x-rapidapi-key": settings.rapidapi_key,
            "x-rapidapi-host": self.api_host,
            "Content-Type": "application/json",
        }

    async def _post(
        self,
        endpoint: str,
        *,
        body: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any] | list[Any]:
        """Make a POST request to a twitter154 endpoint.

        Mirrors the retry behaviour of :class:`RapidAPIClient.get` but
        sends a JSON body instead of query parameters.

        Raises:
            RapidAPIError: On non-200 responses after retries.
        """
        import asyncio

        url = f"https://{self.api_host}{endpoint}"
        headers = self._get_headers()
        max_retries = RapidAPIClient.MAX_RETRIES
        retry_delay = RapidAPIClient.RETRY_DELAY

        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as http:
                    response = await http.post(url, headers=headers, json=body)

                if response.status_code == 200:
                    return response.json()  # type: ignore[return-value]

                if response.status_code == 429:
                    wait = retry_delay * (2**attempt)
                    logger.warning(
                        "Rate limited by %s, waiting %.1fs (attempt %d)",
                        self.api_host,
                        wait,
                        attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue

                if response.status_code >= 500:
                    wait = retry_delay * (2**attempt)
                    logger.warning(
                        "Server error %d from %s, retrying in %.1fs",
                        response.status_code,
                        self.api_host,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                # Client error — don't retry
                raise RapidAPIError(response.status_code, response.text[:500], self.api_host)

            except httpx.HTTPError as e:
                last_error = e
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)
                    continue
                raise RapidAPIError(0, str(e), self.api_host) from e

        raise RapidAPIError(0, f"Max retries exceeded: {last_error}", self.api_host)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_timestamp(raw: dict[str, Any]) -> datetime | None:
        """Parse a tweet's creation timestamp.

        Tries ``creation_date`` string first (e.g.
        ``"Thu Jun 19 12:34:56 +0000 2025"``), then falls back to the
        ``timestamp`` unix epoch field.
        """
        creation_date = raw.get("creation_date")
        if creation_date and isinstance(creation_date, str):
            with contextlib.suppress(ValueError):
                return datetime.strptime(creation_date, _TWITTER_DATE_FMT).replace(tzinfo=UTC)

        ts = raw.get("timestamp")
        if ts is not None:
            with contextlib.suppress(ValueError, OSError, TypeError):
                return datetime.fromtimestamp(int(ts), tz=UTC)

        return None

    @staticmethod
    def _extract_media(raw: dict[str, Any]) -> list[str]:
        """Collect media URLs from a tweet result."""
        urls: list[str] = []
        if raw.get("media_url"):
            urls.append(str(raw["media_url"]))
        if raw.get("video_url"):
            urls.append(str(raw["video_url"]))
        return urls

    def _parse_tweet(self, raw: dict[str, Any]) -> UnifiedPost:
        """Convert a twitter154 search result into a :class:`UnifiedPost`."""
        user: dict[str, Any] = raw.get("user") or {}
        username = user.get("username") or ""
        tweet_id = str(raw.get("tweet_id") or "")

        # Build permalink
        url = f"https://x.com/{username}/status/{tweet_id}" if username and tweet_id else ""

        # Extract hashtags from tweet text
        text = raw.get("text") or ""
        hashtags: list[str] = []
        for word in text.split():
            if word.startswith("#") and len(word) > 1:
                hashtags.append(word.lstrip("#").lower())

        return UnifiedPost(
            platform="twitter",
            external_id=tweet_id,
            author=user.get("name") or username,
            author_id=username,
            title=None,  # Tweets don't have titles
            body=text,
            url=url,
            subreddit=None,
            hashtags=hashtags,
            upvotes=int(raw.get("favorite_count") or 0),
            comments_count=int(raw.get("reply_count") or 0),
            shares=int(raw.get("retweet_count") or 0),
            views=int(raw.get("views") or 0),
            created_at=self._parse_timestamp(raw),
            media_urls=self._extract_media(raw),
            raw_data=raw,
        )

    @staticmethod
    def _build_query(keywords: list[str]) -> str:
        """Build a Twitter search query from keywords.

        Joins keywords with OR to match tweets containing ANY keyword,
        then appends ``-is:retweet lang:en`` to filter retweets and
        restrict to English tweets.
        """
        # Quote multi-word keywords so they're treated as phrases
        parts = []
        for kw in keywords:
            kw = kw.strip()
            if not kw:
                continue
            if " " in kw:
                parts.append(f'"{kw}"')
            else:
                parts.append(kw)
        base = " OR ".join(parts)
        return f"({base}) -is:retweet lang:en"

    # ------------------------------------------------------------------
    # PlatformAdapter interface
    # ------------------------------------------------------------------

    async def search_posts(
        self,
        keywords: list[str],
        *,
        limit: int = 50,
        sort: str = "relevance",
        time_filter: str = "week",
    ) -> list[UnifiedPost]:
        """Search Twitter for tweets matching *keywords*.

        Batches keywords into groups of 5 (to keep queries under Twitter's
        length limits), searches each batch, and deduplicates results.

        Uses ``POST /search/search`` with ``section="top"`` for
        high-quality, engagement-sorted results.
        """
        if not self._available:
            return []

        # Batch keywords into groups of 5 to avoid overly long queries
        batch_size = 5
        kw_batches = [keywords[i:i + batch_size] for i in range(0, len(keywords), batch_size)]
        # Cap at 4 batches (20 keywords) to stay within rate limits
        kw_batches = kw_batches[:4]

        all_posts: list[UnifiedPost] = []
        seen_ids: set[str] = set()
        per_page = min(limit, 20)

        for batch in kw_batches:
            query = self._build_query(batch)

            try:
                data = await self._post(
                    "/search/search",
                    body={
                        "query": query,
                        "section": "top",
                        "limit": per_page,
                    },
                )
            except RapidAPIError as e:
                logger.warning("Twitter search failed for '%s': %s", query[:60], e)
                continue

            results: list[dict[str, Any]] = []
            if isinstance(data, dict):
                results = data.get("results", [])
            elif isinstance(data, list):
                results = data

            for item in results[:per_page]:
                if not isinstance(item, dict):
                    continue
                # Skip retweets that slipped through the query filter
                if item.get("retweet"):
                    continue
                tweet_id = str(item.get("tweet_id", ""))
                if tweet_id in seen_ids:
                    continue
                seen_ids.add(tweet_id)
                with contextlib.suppress(Exception):
                    post = self._parse_tweet(item)
                    post.compute_engagement_score()
                    all_posts.append(post)

            if len(all_posts) >= limit:
                break

        logger.info("[twitter] Search across %d batches returned %d tweets", len(kw_batches), len(all_posts))
        return all_posts[:limit]

    async def get_post_comments(
        self,
        post_id: str,
        *,
        limit: int = 20,
    ) -> list[UnifiedComment]:
        """Get replies to a tweet.

        The twitter154 API does not expose a direct tweet-reply endpoint,
        so this returns an empty list.  Callers should not rely on
        comment fetching for Twitter posts.
        """
        logger.debug("[twitter] get_post_comments not supported — returning empty list for %s", post_id)
        return []

    async def get_trending(
        self,
        *,
        topic: str | None = None,
        limit: int = 25,
    ) -> list[UnifiedPost]:
        """Get trending/popular tweets.

        Performs a search with the given *topic* (or a generic trending
        query) sorted by ``section="top"`` to surface high-engagement
        content.
        """
        if not self._available:
            return []

        keywords = [topic] if topic else ["trending"]
        return await self.search_posts(keywords, limit=limit, sort="relevance")

    async def health_check(self) -> bool:
        """Verify the Twitter adapter can reach the API."""
        if not self._available:
            return False

        try:
            data = await self._post(
                "/search/search",
                body={
                    "query": "test",
                    "section": "top",
                    "limit": 1,
                },
            )
            return isinstance(data, dict) and "results" in data
        except Exception:
            return False
