"""Instagram platform adapter — powered by RapidAPI.

Uses the instagram120.p.rapidapi.com API from the RapidAPI marketplace.
All endpoints use POST with JSON bodies.

Instagram does NOT have keyword search. ``search_posts`` interprets each
keyword as a username and fetches that account's recent posts.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.infrastructure.platforms.base import PlatformAdapter
from app.services.infrastructure.platforms.models import UnifiedComment, UnifiedPost
from app.services.infrastructure.platforms.rapidapi_client import RapidAPIClient, RapidAPIError

logger = logging.getLogger(__name__)

# Default RapidAPI host for Instagram scraping.
DEFAULT_INSTAGRAM_API_HOST = "instagram120.p.rapidapi.com"


class InstagramAdapter(PlatformAdapter):
    """Instagram adapter using RapidAPI scraper.

    Endpoints used (all POST with JSON body):
      - POST /api/instagram/posts    — posts by username
      - POST /api/instagram/profile  — user profile
      - POST /api/instagram/reels    — reels by username
      - POST /api/instagram/userInfo — user info
    """

    platform_name = "instagram"

    def __init__(self, api_host: str | None = None):
        self.api_host = api_host or DEFAULT_INSTAGRAM_API_HOST
        try:
            self.client = RapidAPIClient(self.api_host)
            self._available = True
        except ValueError:
            logger.warning("RapidAPI key not configured — Instagram adapter unavailable")
            self._available = False

    # ------------------------------------------------------------------
    # Internal HTTP helper — Instagram endpoints are POST-only
    # ------------------------------------------------------------------

    async def _post(
        self,
        endpoint: str,
        *,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Make a POST request to the Instagram RapidAPI endpoint.

        Reuses the :class:`RapidAPIClient` for auth headers and throttling,
        but sends the request as ``POST`` with a JSON body because every
        instagram120 endpoint requires it.

        Args:
            endpoint: API path (e.g., ``/api/instagram/posts``).
            body: JSON payload.

        Returns:
            Parsed JSON response dict.

        Raises:
            RapidAPIError: On non-200 responses after retries.
        """
        await self.client._throttle()  # noqa: SLF001 — reuse shared rate limiter

        url = f"https://{self.api_host}{endpoint}"
        headers = {
            **self.client._get_headers(),  # noqa: SLF001
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None

        for attempt in range(self.client.MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=self.client.timeout) as http:
                    response = await http.post(url, headers=headers, json=body)

                if response.status_code == 200:
                    return response.json()  # type: ignore[no-any-return]

                if response.status_code == 429:
                    wait = self.client.RETRY_DELAY * (2**attempt)
                    logger.warning(
                        "Rate limited by %s, waiting %.1fs (attempt %d)",
                        self.api_host,
                        wait,
                        attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue

                if response.status_code >= 500:
                    wait = self.client.RETRY_DELAY * (2**attempt)
                    logger.warning(
                        "Server error %d from %s, retrying in %.1fs",
                        response.status_code,
                        self.api_host,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                # Client error (400, 403, 404) — don't retry
                error_body = response.text[:500]
                raise RapidAPIError(response.status_code, error_body, self.api_host)

            except httpx.HTTPError as e:
                last_error = e
                if attempt < self.client.MAX_RETRIES:
                    await asyncio.sleep(self.client.RETRY_DELAY)
                    continue
                raise RapidAPIError(0, str(e), self.api_host) from e

        raise RapidAPIError(0, f"Max retries exceeded: {last_error}", self.api_host)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_post(self, node: dict[str, Any]) -> UnifiedPost:
        """Convert an Instagram post node dict into a :class:`UnifiedPost`."""
        # Caption text
        caption = node.get("caption") or {}
        body = caption.get("text", "") if isinstance(caption, dict) else str(caption)

        # Shortcode for permalink
        code = node.get("code") or node.get("shortcode") or ""
        url = f"https://www.instagram.com/p/{code}/" if code else ""

        # Author
        owner = node.get("owner") or node.get("user") or {}
        author = owner.get("username", "") if isinstance(owner, dict) else ""
        author_id = str(owner.get("pk", "")) if isinstance(owner, dict) else ""

        # Timestamp
        created_at: datetime | None = None
        taken_at = node.get("taken_at")
        if taken_at is not None:
            with contextlib.suppress(ValueError, OSError, TypeError):
                created_at = datetime.fromtimestamp(int(taken_at), tz=UTC)

        # Media URLs — first candidate from image_versions2
        media_urls: list[str] = []
        image_versions = node.get("image_versions2") or {}
        candidates = image_versions.get("candidates", []) if isinstance(image_versions, dict) else []
        if candidates and isinstance(candidates[0], dict):
            first_url = candidates[0].get("url", "")
            if first_url:
                media_urls.append(first_url)

        # Also grab video URL if present
        video_versions = node.get("video_versions") or []
        if video_versions and isinstance(video_versions[0], dict):
            video_url = video_versions[0].get("url", "")
            if video_url:
                media_urls.append(video_url)

        # Hashtags from caption
        hashtags: list[str] = []
        if body:
            import re

            hashtags = re.findall(r"#(\w+)", body)

        # Engagement
        like_count = int(node.get("like_count") or 0)
        comment_count = int(node.get("comment_count") or 0)
        views = int(node.get("view_count") or node.get("play_count") or 0)

        # Media type context
        product_type = node.get("product_type", "")  # "clips" = reel
        media_type = node.get("media_type")  # 1=photo, 2=video

        external_id = str(node.get("pk") or node.get("id") or code)

        post = UnifiedPost(
            platform="instagram",
            external_id=external_id,
            author=author,
            author_id=author_id,
            title=None,  # Instagram posts don't have titles
            body=body,
            url=url,
            hashtags=hashtags,
            upvotes=like_count,
            comments_count=comment_count,
            shares=0,  # Not exposed by the API
            views=views,
            created_at=created_at,
            media_urls=media_urls,
            raw_data={
                **node,
                "_product_type": product_type,
                "_media_type": media_type,
            },
        )
        post.compute_engagement_score()
        return post

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_user_posts(
        self,
        username: str,
        *,
        limit: int = 20,
    ) -> list[UnifiedPost]:
        """Fetch recent posts for a specific Instagram username.

        This is the primary data retrieval method. ``search_posts`` delegates
        to this since Instagram has no keyword search.

        Args:
            username: Instagram username (without ``@``).
            limit: Maximum number of posts to return.

        Returns:
            List of parsed posts.
        """
        if not self._available:
            logger.warning("Instagram adapter not available (no RAPIDAPI_KEY)")
            return []

        username = username.lstrip("@").strip()
        if not username:
            return []

        try:
            data = await self._post(
                "/api/instagram/posts",
                body={"username": username},
            )
        except RapidAPIError as e:
            logger.error("Instagram posts fetch failed for @%s: %s", username, e)
            return []

        # Navigate response: {"result": {"edges": [{"node": {...}}, ...]}}
        result = data.get("result", {}) if isinstance(data, dict) else {}
        edges = result.get("edges", []) if isinstance(result, dict) else []

        posts: list[UnifiedPost] = []
        for edge in edges[:limit]:
            node = edge.get("node", edge) if isinstance(edge, dict) else {}
            if not isinstance(node, dict) or not node:
                continue
            try:
                posts.append(self._parse_post(node))
            except Exception as e:
                logger.debug("Failed to parse Instagram post: %s", e)

        logger.info("[instagram] Fetched %d posts for @%s", len(posts), username)
        return posts

    async def search_posts(
        self,
        keywords: list[str],
        *,
        limit: int = 50,
        sort: str = "relevance",
        time_filter: str = "week",
    ) -> list[UnifiedPost]:
        """Search Instagram by treating keywords as usernames.

        Instagram has no public keyword search API. Each keyword is
        interpreted as a potential username and we fetch that account's
        recent posts.

        Args:
            keywords: Usernames (or brand names) to fetch posts from.
            limit: Maximum *total* posts to return across all accounts.
            sort: Ignored (Instagram API doesn't support sort).
            time_filter: Ignored (Instagram API doesn't support time filters).

        Returns:
            Combined list of posts from all resolved usernames.
        """
        if not self._available:
            logger.warning("Instagram adapter not available (no RAPIDAPI_KEY)")
            return []

        per_user_limit = max(1, limit // max(len(keywords), 1))
        all_posts: list[UnifiedPost] = []

        for keyword in keywords:
            # Clean the keyword into a plausible username
            username = keyword.strip().lstrip("@").replace(" ", "").lower()
            if not username:
                continue

            posts = await self.get_user_posts(username, limit=per_user_limit)
            all_posts.extend(posts)

            if len(all_posts) >= limit:
                break

        logger.info(
            "[instagram] Search across %d usernames returned %d posts",
            len(keywords),
            len(all_posts),
        )
        return all_posts[:limit]

    async def get_post_comments(
        self,
        post_id: str,
        *,
        limit: int = 20,
    ) -> list[UnifiedComment]:
        """Get comments on an Instagram post.

        The instagram120 API does not expose a dedicated comments endpoint,
        so this returns an empty list. A future API upgrade may add support.
        """
        logger.debug("[instagram] get_post_comments not supported by current API (post %s)", post_id)
        return []

    async def get_trending(
        self,
        *,
        topic: str | None = None,
        limit: int = 25,
    ) -> list[UnifiedPost]:
        """Get trending Instagram posts.

        Delegates to ``search_posts`` with the topic as a username.
        If no topic is provided, fetches from the ``instagram`` account.
        """
        if not self._available:
            return []

        username = topic or "instagram"
        return await self.get_user_posts(username, limit=limit)

    async def health_check(self) -> bool:
        """Verify the Instagram API is reachable by fetching a known profile."""
        if not self._available:
            return False
        try:
            data = await self._post(
                "/api/instagram/profile",
                body={"username": "instagram"},
            )
            result = data.get("result", {}) if isinstance(data, dict) else {}
            return bool(result.get("username") or result.get("id"))
        except Exception:
            return False
