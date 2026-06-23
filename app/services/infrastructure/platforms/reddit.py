"""Reddit platform adapter — official OAuth API with RapidAPI fallback.

Primary: Uses Reddit's official OAuth API (oauth.reddit.com) which provides
100 requests/minute for free with app credentials.

Fallback: RapidAPI reddit34 when OAuth credentials are not available
(50 requests/month — nearly useless for production).

Reddit OAuth setup:
  1. Go to https://www.reddit.com/prefs/apps
  2. Create a "script" type application
  3. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.infrastructure.platforms.base import PlatformAdapter
from app.services.infrastructure.platforms.models import UnifiedComment, UnifiedPost

logger = logging.getLogger(__name__)

# ── Reddit OAuth client ──────────────────────────────────────────

_oauth_token: dict[str, Any] = {"token": None, "expires_at": 0.0}


class RedditOAuthClient:
    """Lightweight Reddit OAuth2 client using 'script' app flow.

    Authenticates via /api/v1/access_token with client credentials,
    then uses oauth.reddit.com for all API requests.
    """

    TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
    BASE_URL = "https://oauth.reddit.com"

    def __init__(self, client_id: str, client_secret: str, user_agent: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent

    async def _ensure_token(self) -> str:
        """Get or refresh the OAuth2 bearer token."""
        now = time.time()
        if _oauth_token["token"] and _oauth_token["expires_at"] > now + 60:
            return _oauth_token["token"]

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                self.TOKEN_URL,
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self.user_agent},
            )
            resp.raise_for_status()
            data = resp.json()
            _oauth_token["token"] = data["access_token"]
            _oauth_token["expires_at"] = now + data.get("expires_in", 3600)
            logger.info("Reddit OAuth token acquired (expires in %ds)", data.get("expires_in", 3600))
            return _oauth_token["token"]

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make an authenticated GET request to oauth.reddit.com."""
        token = await self._ensure_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": self.user_agent,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.BASE_URL}{path}",
                headers=headers,
                params=params or {},
            )
            if resp.status_code == 429:
                # Reddit rate limit — wait and retry once
                wait = float(resp.headers.get("Retry-After", "2"))
                logger.warning("Reddit OAuth rate limited, waiting %.1fs", wait)
                await asyncio.sleep(wait)
                resp = await client.get(
                    f"{self.BASE_URL}{path}",
                    headers=headers,
                    params=params or {},
                )
            resp.raise_for_status()
            return resp.json()


# ── Reddit Adapter ───────────────────────────────────────────────


class RedditAdapter(PlatformAdapter):
    """Reddit adapter using official OAuth API (primary) or RapidAPI (fallback).

    When REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are set, uses the official
    Reddit OAuth API at oauth.reddit.com (100 req/min, free).

    Falls back to RapidAPI reddit34 when OAuth is not configured.
    """

    platform_name = "reddit"

    def __init__(self, api_host: str | None = None):
        self._subreddits: list[str] = []
        self._oauth_client: RedditOAuthClient | None = None
        self._rapidapi_client = None

        # Try official OAuth first
        from app.core.config import get_settings
        settings = get_settings()
        if settings.reddit_client_id and settings.reddit_client_secret:
            ua = settings.reddit_user_agent or "web:signalflow:v1.0 (by /u/SignalFlowBot)"
            self._oauth_client = RedditOAuthClient(
                settings.reddit_client_id,
                settings.reddit_client_secret,
                ua,
            )
            self._available = True
            logger.info("Reddit adapter: using official OAuth API")
        else:
            # Fallback to RapidAPI
            try:
                from app.services.infrastructure.platforms.rapidapi_client import RapidAPIClient
                api_host = api_host or "reddit34.p.rapidapi.com"
                self._rapidapi_client = RapidAPIClient(api_host)
                self._available = True
                logger.info("Reddit adapter: using RapidAPI fallback (limited quota)")
            except (ValueError, Exception):
                logger.warning("Reddit adapter: no OAuth or RapidAPI credentials — disabled")
                self._available = False

    def set_subreddits(self, subreddits: list[str]) -> None:
        """Set the list of subreddits to browse during search_and_enrich."""
        self._subreddits = list(subreddits)

    # ── Post parsing ─────────────────────────────────────────────

    def _parse_post(self, raw: dict[str, Any]) -> UnifiedPost:
        """Convert a Reddit API response item to UnifiedPost."""
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
        """Convert a Reddit comment to UnifiedComment."""
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

    # ── Core methods ─────────────────────────────────────────────

    async def get_subreddit_posts(
        self,
        subreddit: str,
        *,
        sort: str = "new",
        limit: int = 25,
    ) -> list[UnifiedPost]:
        """Get posts from a subreddit."""
        if not self._available:
            return []

        if self._oauth_client:
            return await self._get_subreddit_posts_oauth(subreddit, sort=sort, limit=limit)
        return await self._get_subreddit_posts_rapidapi(subreddit, sort=sort, limit=limit)

    async def _get_subreddit_posts_oauth(
        self, subreddit: str, *, sort: str = "new", limit: int = 25,
    ) -> list[UnifiedPost]:
        """Fetch subreddit posts via official OAuth API."""
        try:
            data = await self._oauth_client.get(
                f"/r/{subreddit}/{sort}",
                params={"limit": min(limit, 100), "raw_json": 1},
            )
        except Exception as e:
            logger.warning("OAuth: failed to get r/%s: %s", subreddit, e)
            return []

        posts_raw = data.get("data", {}).get("children", [])
        posts = []
        for item in posts_raw[:limit]:
            try:
                post_data = item.get("data", item) if isinstance(item, dict) else item
                if isinstance(post_data, dict):
                    posts.append(self._parse_post(post_data))
            except Exception as e:
                logger.debug("Failed to parse Reddit post: %s", e)

        logger.info("[reddit/oauth] r/%s (%s) → %d posts", subreddit, sort, len(posts))
        return posts

    async def _get_subreddit_posts_rapidapi(
        self, subreddit: str, *, sort: str = "hot", limit: int = 25,
    ) -> list[UnifiedPost]:
        """Fetch subreddit posts via RapidAPI (fallback)."""
        try:
            data = await self._rapidapi_client.get(
                "/getPostsBySubreddit",
                params={"subreddit": subreddit, "sort": sort},
            )
        except Exception as e:
            logger.warning("RapidAPI: failed to get r/%s: %s", subreddit, e)
            return []

        posts_raw = self._extract_posts_from_response(data)
        posts = []
        for item in posts_raw[:limit]:
            try:
                if isinstance(item, dict):
                    posts.append(self._parse_post(item))
            except Exception as e:
                logger.debug("Failed to parse Reddit post: %s", e)

        logger.info("[reddit/rapidapi] r/%s (%s) → %d posts", subreddit, sort, len(posts))
        return posts

    def _extract_posts_from_response(self, data: Any) -> list[dict[str, Any]]:
        """Extract post dicts from the reddit34 API response."""
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

    async def get_post_comments(
        self,
        post_id: str,
        *,
        limit: int = 20,
    ) -> list[UnifiedComment]:
        """Get comments for a Reddit post."""
        if not self._available:
            return []

        if self._oauth_client:
            return await self._get_comments_oauth(post_id, limit=limit)
        return await self._get_comments_rapidapi(post_id, limit=limit)

    async def _get_comments_oauth(self, post_id: str, *, limit: int = 20) -> list[UnifiedComment]:
        """Fetch comments via official OAuth API."""
        # Extract the post path from URL or ID
        if post_id.startswith("http"):
            # Extract path: https://www.reddit.com/r/sub/comments/id/title/
            from urllib.parse import urlparse
            path = urlparse(post_id).path.rstrip("/")
        else:
            path = f"/comments/{post_id}"

        try:
            data = await self._oauth_client.get(
                path,
                params={"limit": limit, "sort": "confidence", "raw_json": 1},
            )
        except Exception as e:
            logger.warning("OAuth: failed to get comments for %s: %s", post_id[:60], e)
            return []

        # Response is [post_listing, comments_listing]
        comments = []
        if isinstance(data, list) and len(data) >= 2:
            comment_listing = data[1].get("data", {}).get("children", [])
            for item in comment_listing[:limit]:
                try:
                    if isinstance(item, dict) and item.get("kind") == "t1":
                        comment_data = item.get("data", item)
                        comments.append(self._parse_comment(comment_data, post_id))
                except Exception as e:
                    logger.debug("Failed to parse comment: %s", e)

        logger.info("[reddit/oauth] %d comments for %s", len(comments), post_id[:60])
        return comments

    async def _get_comments_rapidapi(self, post_id: str, *, limit: int = 20) -> list[UnifiedComment]:
        """Fetch comments via RapidAPI (fallback)."""
        post_url = post_id
        if not post_url.startswith("http"):
            post_url = f"https://www.reddit.com/comments/{post_id}/"

        try:
            data = await self._rapidapi_client.get(
                "/getPostCommentsV2",
                params={"post_url": post_url, "sort": "new"},
            )
        except Exception as e:
            logger.warning("RapidAPI: failed to get comments for %s: %s", post_id, e)
            return []

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

        logger.info("[reddit/rapidapi] %d comments for %s", len(comments), post_id[:60])
        return comments

    # ── search_posts (required by base class) ────────────────────

    async def search_posts(
        self,
        keywords: list[str],
        *,
        limit: int = 50,
        sort: str = "relevance",
        time_filter: str = "week",
    ) -> list[UnifiedPost]:
        """Search Reddit for posts matching keywords."""
        if not self._available:
            return []

        if self._oauth_client:
            query = " OR ".join(keywords[:5])
            try:
                data = await self._oauth_client.get(
                    "/search",
                    params={
                        "q": query,
                        "sort": sort,
                        "t": time_filter,
                        "limit": min(limit, 100),
                        "type": "link",
                        "raw_json": 1,
                    },
                )
                posts_raw = data.get("data", {}).get("children", [])
                posts = []
                for item in posts_raw[:limit]:
                    try:
                        post_data = item.get("data", item) if isinstance(item, dict) else item
                        if isinstance(post_data, dict):
                            posts.append(self._parse_post(post_data))
                    except Exception:
                        continue
                logger.info("[reddit/oauth] Search '%s' → %d posts", query[:50], len(posts))
                return posts
            except Exception as e:
                logger.warning("OAuth: search failed: %s", e)
                return []

        # RapidAPI fallback: no keyword search, use popular posts
        if self._rapidapi_client:
            try:
                data = await self._rapidapi_client.get(
                    "/getPopularPosts",
                    params={"sort": "new"},
                )
                posts_raw = self._extract_posts_from_response(data)
                posts = []
                for item in posts_raw[:limit]:
                    try:
                        if isinstance(item, dict):
                            posts.append(self._parse_post(item))
                    except Exception:
                        continue
                return posts
            except Exception as e:
                logger.warning("RapidAPI search failed: %s", e)

        return []

    # ── search_and_enrich (browse all monitored subreddits) ──────

    async def search_and_enrich(
        self,
        keywords: list[str],
        *,
        limit: int = 50,
        fetch_comments: bool = False,
        comments_per_post: int = 10,
    ) -> list[UnifiedPost]:
        """Browse all monitored subreddits + fetch comments.

        When ``_subreddits`` is set, browses each subreddit and fetches
        comments for the top posts by engagement.
        """
        if not self._available:
            return []

        if not self._subreddits:
            return await super().search_and_enrich(
                keywords, limit=limit, fetch_comments=fetch_comments,
                comments_per_post=comments_per_post,
            )

        all_posts: list[UnifiedPost] = []
        posts_per_sub = max(limit // max(len(self._subreddits), 1), 10)

        for i, subreddit in enumerate(self._subreddits):
            # Space out requests to be a good API citizen
            if i > 0:
                await asyncio.sleep(0.5 if self._oauth_client else 1.5)
            try:
                sub_posts = await self.get_subreddit_posts(
                    subreddit, sort="new", limit=posts_per_sub,
                )
                logger.info("[reddit] r/%s → %d posts", subreddit, len(sub_posts))
                all_posts.extend(sub_posts)
            except Exception as exc:
                logger.warning("[reddit] Failed to browse r/%s: %s", subreddit, exc)

        # Fetch comments for the top posts (by engagement)
        comment_budget = min(len(all_posts), 15)
        sorted_posts = sorted(all_posts, key=lambda p: p.upvotes + p.comments_count, reverse=True)
        for post in sorted_posts[:comment_budget]:
            if not post.url:
                continue
            try:
                comments = await self.get_post_comments(post.url, limit=comments_per_post)
                post.raw_data["comments"] = [c.model_dump() for c in comments]
                post.comments_count = max(post.comments_count, len(comments))
            except Exception as exc:
                logger.debug("[reddit] Comment fetch failed for %s: %s", post.external_id, exc)

        logger.info("[reddit] Total: %d posts from %d subreddits", len(all_posts), len(self._subreddits))
        return all_posts

    # ── Trending & health check ──────────────────────────────────

    async def get_trending(
        self,
        *,
        topic: str | None = None,
        limit: int = 25,
    ) -> list[UnifiedPost]:
        """Get trending Reddit posts."""
        if not self._available:
            return []

        if topic:
            return await self.get_subreddit_posts(topic, sort="hot", limit=limit)

        if self._oauth_client:
            try:
                data = await self._oauth_client.get(
                    "/hot",
                    params={"limit": min(limit, 50), "raw_json": 1},
                )
                posts_raw = data.get("data", {}).get("children", [])
                posts = []
                for item in posts_raw[:limit]:
                    try:
                        post_data = item.get("data", item) if isinstance(item, dict) else item
                        if isinstance(post_data, dict):
                            posts.append(self._parse_post(post_data))
                    except Exception:
                        continue
                return posts
            except Exception:
                return []

        return []

    async def health_check(self) -> bool:
        """Check if the Reddit API is reachable."""
        if not self._available:
            return False
        try:
            if self._oauth_client:
                data = await self._oauth_client.get("/api/v1/me")
                return isinstance(data, dict)
            if self._rapidapi_client:
                data = await self._rapidapi_client.get("/getPopularPosts", params={"sort": "new"})
                return isinstance(data, dict) and data.get("success", False)
        except Exception:
            return False
        return False
