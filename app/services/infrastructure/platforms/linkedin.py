"""LinkedIn platform adapter — Fresh LinkedIn Scraper API (RapidAPI).

API host: fresh-linkedin-scraper-api.p.rapidapi.com
Rate limit: 1000 requests/hour (same as other platform APIs).

Endpoints used:
  - GET /api/v1/search/posts    — keyword search (param: keyword)
  - GET /api/v1/user/profile    — user profile lookup
  - GET /api/v1/post/detail     — post detail
  - GET /api/v1/post/comments   — post comments
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.infrastructure.platforms.base import PlatformAdapter
from app.services.infrastructure.platforms.models import UnifiedComment, UnifiedPost

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "fresh-linkedin-scraper-api.p.rapidapi.com"
_TIMEOUT = 25.0


class LinkedInAdapter(PlatformAdapter):
    """LinkedIn adapter using fresh-linkedin-scraper-api.p.rapidapi.com.

    Rate limit: 1000 requests/hour (same as other platforms).
    """

    platform_name: str = "linkedin"

    def __init__(
        self,
        api_key: str = "",
        host: str = _DEFAULT_HOST,
    ) -> None:
        if not api_key:
            from app.core.config import get_settings
            api_key = get_settings().rapidapi_key or ""
        self.api_key = api_key
        self.api_host = host
        self._available = bool(self.api_key)
        if not self._available:
            logger.warning("LinkedInAdapter: RAPIDAPI_KEY not set — LinkedIn features disabled.")

    def _headers(self) -> dict[str, str]:
        return {
            "x-rapidapi-host": self.api_host,
            "x-rapidapi-key": self.api_key,
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request to the LinkedIn API."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"https://{self.api_host}{path}",
                params=params or {},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and not data.get("success", True):
                msg = data.get("message", "Unknown error")
                logger.warning("[linkedin] API error: %s", msg)
            return data if isinstance(data, dict) else {"data": data}

    def _parse_post(self, raw: dict[str, Any]) -> UnifiedPost:
        """Parse a LinkedIn search result into a UnifiedPost."""
        activity = raw.get("activity", {}) or {}
        author_data = raw.get("author", {}) or {}

        # Parse created_at (ISO format: "2026-06-20T14:10:39.401Z")
        created_at = datetime.now(tz=UTC)
        raw_date = raw.get("created_at", "")
        if raw_date:
            import contextlib
            with contextlib.suppress(ValueError, TypeError):
                created_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))

        post = UnifiedPost(
            platform="linkedin",
            external_id=str(raw.get("id", "")),
            title=str(raw.get("title", ""))[:200],
            body=str(raw.get("commentary") or raw.get("text") or raw.get("description") or raw.get("content") or raw.get("title", "")),
            url=str(raw.get("url", "")),
            author=author_data.get("name", "Unknown"),
            author_url=author_data.get("url", ""),
            created_at=created_at,
            upvotes=activity.get("num_likes", 0) or 0,
            comments_count=activity.get("num_comments", 0) or 0,
            shares=activity.get("num_shares", 0) or 0,
            raw_data=raw,
        )
        post.compute_engagement_score()
        return post

    async def search_posts(
        self,
        keywords: list[str],
        *,
        limit: int = 20,
        sort: str = "relevance",
        time_filter: str = "week",
    ) -> list[UnifiedPost]:
        """Search LinkedIn posts by keyword.

        Uses GET /api/v1/search/posts with `keyword` parameter.
        Note: Each call costs 1 credit against the 1000/hr limit.
        """
        if not self._available:
            return []

        all_posts: list[UnifiedPost] = []
        seen_ids: set[str] = set()

        # Search top 5 keywords individually for broader coverage
        for keyword in keywords[:5]:
            query = keyword.strip()
            if not query:
                continue
            try:
                data = await self._get(
                    "/api/v1/search/posts",
                    params={"keyword": query, "page": "1"},
                )
            except Exception as e:
                logger.warning("[linkedin] Search failed for '%s': %s", query[:40], e)
                continue

            results = data.get("data", [])
            if not isinstance(results, list):
                continue

            for item in results[:limit]:
                try:
                    post = self._parse_post(item)
                    if post.external_id not in seen_ids:
                        seen_ids.add(post.external_id)
                        all_posts.append(post)
                except Exception as e:
                    logger.debug("[linkedin] Failed to parse post: %s", e)

            if len(all_posts) >= limit:
                break

        logger.info("[linkedin] Search across %d keywords returned %d posts", min(len(keywords), 5), len(all_posts))
        return all_posts[:limit]

    async def get_post_comments(
        self,
        post_id: str,
        *,
        limit: int = 20,
    ) -> list[UnifiedComment]:
        """Get comments for a LinkedIn post.

        Uses GET /api/v1/post/comments with `post_id` parameter.
        ⚠️ Each call costs 1 credit — use sparingly.
        """
        if not self._available:
            return []

        try:
            data = await self._get(
                "/api/v1/post/comments",
                params={"post_id": post_id},
            )
        except Exception as e:
            logger.warning("[linkedin] Comments fetch failed: %s", e)
            return []

        raw_comments = data.get("data", [])
        if not isinstance(raw_comments, list):
            return []

        comments = []
        for c in raw_comments[:limit]:
            try:
                author = c.get("author", {}) or {}
                comments.append(
                    UnifiedComment(
                        platform="linkedin",
                        comment_id=str(c.get("id", "")),
                        post_id=post_id,
                        body=str(c.get("text", c.get("content", ""))),
                        author=author.get("name", "Unknown"),
                        created_at=datetime.now(tz=UTC),
                        upvotes=c.get("num_likes", 0) or 0,
                    )
                )
            except Exception:
                continue

        return comments

    async def get_trending(
        self,
        *,
        topic: str | None = None,
        limit: int = 25,
    ) -> list[UnifiedPost]:
        """Get trending LinkedIn posts (delegates to search)."""
        keyword = topic or "technology trends"
        return await self.search_posts([keyword], limit=limit)

    async def health_check(self) -> bool:
        """Check if the LinkedIn API is reachable."""
        if not self._available:
            return False
        try:
            data = await self._get(
                "/api/v1/user/profile",
                params={"username": "jack"},
            )
            return data.get("success", False) is True
        except Exception:
            return False
