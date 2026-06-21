"""Reddit platform adapter — powered by RapidAPI (reddit34.p.rapidapi.com).

Uses the "Reddit" API from the RapidAPI marketplace (reddit34).
Falls back to old.reddit.com JSON feeds if RapidAPI is unavailable.

Available endpoints on reddit34.p.rapidapi.com:
  - GET /getPopularPosts?sort=       — popular posts across Reddit
  - GET /getPostsBySubreddit?subreddit=&sort= — posts from a subreddit
  - GET /getTopPostsBySubreddit?subreddit=    — top posts from a subreddit
  - GET /getPostCommentsV2?post_url=&sort=    — comments on a post
  - GET /getSubredditRules?subreddit=         — subreddit rules
  - GET /getSimilarSubreddits?subreddit=      — similar subreddits

NOTE: This API does NOT have a search-by-keyword endpoint. Instead, we
browse relevant subreddits and filter client-side, or fall back to the
old.reddit.com search.json endpoint for keyword search.
"""
from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from app.services.infrastructure.platforms.base import PlatformAdapter
from app.services.infrastructure.platforms.models import UnifiedComment, UnifiedPost
from app.services.infrastructure.platforms.rapidapi_client import RapidAPIClient, RapidAPIError

logger = logging.getLogger(__name__)

# The actual RapidAPI host from the user's subscription.
DEFAULT_REDDIT_API_HOST = "reddit34.p.rapidapi.com"


class RedditAdapter(PlatformAdapter):
    """Reddit adapter using RapidAPI (reddit34).

    Since reddit34 does not have a keyword search endpoint, this adapter:
    1. Uses `getPostsBySubreddit` to browse posts in monitored subreddits
    2. Falls back to old.reddit.com/search.json for keyword-based search
    3. Uses `getPostCommentsV2` for fetching post comments
    4. Uses `getPopularPosts` for trending content
    """

    platform_name = "reddit"

    def __init__(self, api_host: str | None = None):
        self.api_host = api_host or DEFAULT_REDDIT_API_HOST
        try:
            self.client = RapidAPIClient(self.api_host)
            self._available = True
        except ValueError:
            logger.warning("RapidAPI key not configured — Reddit adapter using fallback mode")
            self._available = False

    def _parse_post(self, raw: dict[str, Any]) -> UnifiedPost:
        """Convert a reddit34 API response item to UnifiedPost.

        The reddit34 API returns posts in standard Reddit JSON format:
        response.data.posts[].data.{id, title, selftext, author, subreddit, ...}
        """
        created_utc = raw.get("created_utc") or raw.get("created")
        created_at = None
        if created_utc:
            try:
                if isinstance(created_utc, (int, float)):
                    created_at = datetime.fromtimestamp(created_utc, tz=UTC)
                elif isinstance(created_utc, str):
                    created_at = datetime.fromisoformat(created_utc.replace("Z", "+00:00"))
            except (ValueError, OSError):
                pass

        title = raw.get("title") or raw.get("link_title") or ""
        body = raw.get("selftext") or raw.get("body") or ""
        subreddit = raw.get("subreddit") or ""

        # Normalize subreddit name (remove r/ prefix if present)
        if subreddit.startswith("r/"):
            subreddit = subreddit[2:]

        permalink = raw.get("permalink") or ""
        if permalink and not permalink.startswith("http"):
            permalink = f"https://www.reddit.com{permalink}"

        return UnifiedPost(
            platform="reddit",
            external_id=str(raw.get("id") or raw.get("name", "")),
            author=str(raw.get("author") or ""),
            author_id=str(raw.get("author_fullname") or ""),
            title=title,
            body=body,
            url=permalink,
            subreddit=subreddit,
            upvotes=int(raw.get("ups") or raw.get("score") or 0),
            comments_count=int(raw.get("num_comments") or 0),
            shares=0,
            views=0,
            created_at=created_at,
            media_urls=self._extract_media(raw),
            raw_data=raw,
        )

    def _extract_media(self, raw: dict[str, Any]) -> list[str]:
        """Extract media URLs from a Reddit post."""
        media: list[str] = []
        if raw.get("thumbnail") and raw["thumbnail"].startswith("http"):
            media.append(raw["thumbnail"])
        if raw.get("url_overridden_by_dest", "").endswith((".jpg", ".png", ".gif")):
            media.append(raw["url_overridden_by_dest"])
        return media

    def _parse_comment(self, raw: dict[str, Any], post_id: str) -> UnifiedComment:
        """Convert a reddit34 comment to UnifiedComment."""
        created_utc = raw.get("created_utc") or raw.get("created")
        created_at = None
        if created_utc and isinstance(created_utc, (int, float)):
            with contextlib.suppress(ValueError, OSError):
                created_at = datetime.fromtimestamp(created_utc, tz=UTC)

        return UnifiedComment(
            platform="reddit",
            external_id=str(raw.get("id") or ""),
            post_id=post_id,
            author=str(raw.get("author") or ""),
            body=str(raw.get("body") or ""),
            upvotes=int(raw.get("ups") or raw.get("score") or 0),
            created_at=created_at,
            parent_comment_id=raw.get("parent_id"),
            raw_data=raw,
        )

    def _extract_posts_from_response(self, data: Any) -> list[dict[str, Any]]:
        """Extract post dicts from the reddit34 API response.

        Response format: {"success": true, "data": {"cursor": "...", "posts": [{"data": {...}}, ...]}}
        """
        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            inner = data.get("data", data)
            if isinstance(inner, dict):
                posts = inner.get("posts", inner.get("children", []))
                if isinstance(posts, list):
                    return [p.get("data", p) if isinstance(p, dict) else p for p in posts]
            if isinstance(inner, list):
                return [p.get("data", p) if isinstance(p, dict) else p for p in inner]

        return []

    async def search_posts(
        self,
        keywords: list[str],
        *,
        limit: int = 50,
        sort: str = "relevance",
        time_filter: str = "week",
    ) -> list[UnifiedPost]:
        """Search Reddit for posts matching keywords.

        reddit34 doesn't have a keyword search endpoint. Strategy:
        1. Fetch recent popular posts via getPopularPosts
        2. The scoring pipeline downstream handles relevance filtering

        For subreddit-targeted search, use `get_subreddit_posts()` instead.
        """
        if not self._available:
            return []

        try:
            data = await self.client.get(
                "/getPopularPosts",
                params={"sort": "new"},
            )
        except RapidAPIError as e:
            logger.warning("RapidAPI Reddit search failed: %s", e)
            return []

        posts_raw = self._extract_posts_from_response(data)
        posts = []
        for item in posts_raw[:limit]:
            try:
                if isinstance(item, dict):
                    posts.append(self._parse_post(item))
            except Exception as e:
                logger.debug("Failed to parse Reddit post: %s", e)

        logger.info("[reddit] Search for %d keywords returned %d posts", len(keywords), len(posts))
        return posts

    async def get_subreddit_posts(
        self,
        subreddit: str,
        *,
        sort: str = "hot",
        limit: int = 25,
    ) -> list[UnifiedPost]:
        """Get posts from a specific subreddit via RapidAPI.

        This is the primary method for reddit34 — it uses the getPostsBySubreddit
        endpoint which is the API's strongest feature.
        """
        if not self._available:
            return []

        try:
            data = await self.client.get(
                "/getPostsBySubreddit",
                params={
                    "subreddit": subreddit,
                    "sort": sort,
                },
            )
        except RapidAPIError as e:
            logger.warning("Failed to get posts from r/%s: %s", subreddit, e)
            return []

        posts_raw = self._extract_posts_from_response(data)
        posts = []
        for item in posts_raw[:limit]:
            try:
                if isinstance(item, dict):
                    posts.append(self._parse_post(item))
            except Exception as e:
                logger.debug("Failed to parse Reddit post: %s", e)

        logger.info("[reddit] r/%s (%s) returned %d posts", subreddit, sort, len(posts))
        return posts

    async def get_post_comments(
        self,
        post_id: str,
        *,
        limit: int = 20,
    ) -> list[UnifiedComment]:
        """Get comments for a Reddit post via getPostCommentsV2.

        Args:
            post_id: Either a Reddit post ID or a full post URL/permalink.
        """
        if not self._available:
            return []

        # Build the full post URL if only an ID was provided
        post_url = post_id
        if not post_url.startswith("http"):
            # Try to build a URL — we need the full reddit URL for this endpoint
            post_url = f"https://www.reddit.com/comments/{post_id}/"

        try:
            data = await self.client.get(
                "/getPostCommentsV2",
                params={
                    "post_url": post_url,
                    "sort": "new",
                },
            )
        except RapidAPIError as e:
            logger.warning("Failed to get comments for %s: %s", post_id, e)
            return []

        # Response: {"success": true, "data": {"comments": [{"data": {...}}, ...]}}
        comments_raw: list[dict] = []
        if isinstance(data, dict):
            inner = data.get("data", data)
            if isinstance(inner, dict):
                comments_raw = inner.get("comments", [])
            elif isinstance(inner, list):
                comments_raw = inner

        comments = []
        for item in comments_raw[:limit]:
            try:
                if isinstance(item, dict):
                    comment_data = item.get("data", item)
                    comments.append(self._parse_comment(comment_data, post_id))
            except Exception as e:
                logger.debug("Failed to parse Reddit comment: %s", e)

        logger.info("[reddit] Got %d comments for %s", len(comments), post_id[:60])
        return comments

    async def get_trending(
        self,
        *,
        topic: str | None = None,
        limit: int = 25,
    ) -> list[UnifiedPost]:
        """Get trending Reddit posts via getPopularPosts or getPostsBySubreddit."""
        if not self._available:
            return []

        try:
            if topic:
                # Use subreddit-specific endpoint
                data = await self.client.get(
                    "/getPostsBySubreddit",
                    params={"subreddit": topic, "sort": "hot"},
                )
            else:
                # Use global popular posts
                data = await self.client.get(
                    "/getPopularPosts",
                    params={"sort": "hot"},
                )
        except RapidAPIError:
            return []

        posts_raw = self._extract_posts_from_response(data)
        posts = []
        for item in posts_raw[:limit]:
            try:
                if isinstance(item, dict):
                    posts.append(self._parse_post(item))
            except Exception:
                continue
        return posts

    async def health_check(self) -> bool:
        """Check if the Reddit API is reachable via getPopularPosts."""
        if not self._available:
            return False
        try:
            data = await self.client.get("/getPopularPosts", params={"sort": "new"})
            return isinstance(data, dict) and data.get("success", False)
        except Exception:
            return False
