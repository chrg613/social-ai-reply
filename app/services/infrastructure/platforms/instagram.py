"""Instagram platform adapter — powered by RapidAPI (instagram-looter2).

Uses the instagram-looter2.p.rapidapi.com API from the RapidAPI marketplace.
The API supports keyword search via GET /search?query=... which returns
matching hashtags and user profiles.

Rate limit: 150 requests/month on the free plan.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.services.infrastructure.platforms.base import PlatformAdapter
from app.services.infrastructure.platforms.models import UnifiedComment, UnifiedPost
from app.services.infrastructure.platforms.rapidapi_client import RapidAPIClient, RapidAPIError

logger = logging.getLogger(__name__)

# New RapidAPI host for Instagram scraping with keyword search support.
DEFAULT_INSTAGRAM_API_HOST = "instagram-looter2.p.rapidapi.com"


class InstagramAdapter(PlatformAdapter):
    """Instagram adapter using RapidAPI Instagram Looter 2.

    Endpoints used (GET with query params):
      - GET /search?query=...  — global search (returns users + hashtags)
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
    # Internal HTTP helper — GET requests for instagram-looter2
    # ------------------------------------------------------------------

    async def _get(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        """Make a GET request to the Instagram Looter 2 API.

        Args:
            endpoint: API path (e.g., ``/search``).
            params: Query parameters.

        Returns:
            Parsed JSON response.

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
                    response = await http.get(url, headers=headers, params=params or {})

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

    def _parse_user_as_post(self, user_wrapper: dict[str, Any]) -> UnifiedPost | None:
        """Convert a search-result user entry into a UnifiedPost.

        The /search endpoint returns users as {position, user: {...}}.
        We treat each relevant user profile as an opportunity/post.
        """
        user = user_wrapper.get("user", user_wrapper)
        if not isinstance(user, dict):
            return None

        username = user.get("username", "")
        if not username:
            return None

        full_name = user.get("full_name", "")
        bio = user.get("biography", "")
        pk = str(user.get("pk", ""))
        is_verified = user.get("is_verified", False)
        follower_count = int(user.get("follower_count", 0))
        social_context = user.get("search_social_context", "")

        # Build a descriptive body from available fields
        parts = []
        if full_name:
            parts.append(full_name)
        if bio:
            parts.append(bio)
        if social_context:
            parts.append(f"Context: {social_context}")
        if is_verified:
            parts.append("✓ Verified account")

        body = "\n".join(parts) if parts else f"Instagram user @{username}"

        profile_url = f"https://www.instagram.com/{username}/"

        # Profile picture
        media_urls: list[str] = []
        pic_url = user.get("profile_pic_url", "")
        if pic_url:
            media_urls.append(pic_url)

        # Extract hashtags from bio
        hashtags: list[str] = []
        if bio:
            import re
            hashtags = re.findall(r"#(\w+)", bio)

        try:
            post = UnifiedPost(
                platform="instagram",
                external_id=f"ig_user_{pk}" if pk else f"ig_user_{username}",
                author=username,
                author_id=pk,
                title=f"@{username}" + (f" — {full_name}" if full_name else ""),
                body=body,
                url=profile_url,
                hashtags=hashtags,
                upvotes=follower_count,
                comments_count=0,
                shares=0,
                views=0,
                created_at=None,
                media_urls=media_urls,
                raw_data=user,
            )
            post.compute_engagement_score()
            return post
        except Exception as e:
            logger.debug("Failed to create UnifiedPost from Instagram user @%s: %s", username, e)
            return None

    def _parse_hashtag_as_post(self, hashtag_wrapper: dict[str, Any]) -> UnifiedPost | None:
        """Convert a search-result hashtag entry into a UnifiedPost.

        The /search endpoint returns hashtags as {position, hashtag: {name, media_count, id}}.
        We treat popular hashtags as signals/opportunities.
        """
        hashtag = hashtag_wrapper.get("hashtag", hashtag_wrapper)
        if not isinstance(hashtag, dict):
            return None

        name = hashtag.get("name", "")
        if not name:
            return None

        media_count = int(hashtag.get("media_count", 0))
        hashtag_id = str(hashtag.get("id", ""))
        tag_url = f"https://www.instagram.com/explore/tags/{name}/"

        try:
            post = UnifiedPost(
                platform="instagram",
                external_id=f"ig_hashtag_{hashtag_id}" if hashtag_id else f"ig_hashtag_{name}",
                author="instagram",
                author_id="",
                title=f"#{name} — {media_count:,} posts",
                body=f"Instagram hashtag #{name} with {media_count:,} total posts. "
                     f"This is a high-activity topic on Instagram that may be relevant for engagement.",
                url=tag_url,
                hashtags=[name],
                upvotes=media_count,
                comments_count=0,
                shares=0,
                views=0,
                created_at=None,
                media_urls=[],
                raw_data=hashtag,
            )
            post.compute_engagement_score()
            return post
        except Exception as e:
            logger.debug("Failed to create UnifiedPost from Instagram hashtag #%s: %s", name, e)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search_posts(
        self,
        keywords: list[str],
        *,
        limit: int = 50,
        sort: str = "relevance",
        time_filter: str = "week",
    ) -> list[UnifiedPost]:
        """Search Instagram using the Global Search endpoint.

        Uses GET /search?query=... which returns matching users and hashtags.
        Each relevant user profile and trending hashtag is converted into a
        UnifiedPost for the opportunity pipeline.

        Args:
            keywords: Search terms to query.
            limit: Maximum total posts to return.
            sort: Ignored (API doesn't support sort).
            time_filter: Ignored (API doesn't support time filters).

        Returns:
            Combined list of user profiles and hashtags as UnifiedPosts.
        """
        if not self._available:
            logger.warning("Instagram adapter not available (no RAPIDAPI_KEY)")
            return []

        all_posts: list[UnifiedPost] = []
        seen_ids: set[str] = set()

        for keyword in keywords:
            query = keyword.strip()
            if not query:
                continue

            try:
                data = await self._get("/search", params={"query": query})
            except RapidAPIError as e:
                logger.error("Instagram search failed for '%s': %s", query, e)
                continue

            if not isinstance(data, dict):
                continue

            # Parse users — these are the most actionable results
            users = data.get("users", [])
            for user_wrapper in users[:10]:
                if not isinstance(user_wrapper, dict):
                    continue
                post = self._parse_user_as_post(user_wrapper)
                if post and post.external_id not in seen_ids:
                    seen_ids.add(post.external_id)
                    all_posts.append(post)

            # Parse hashtags — useful as content signals
            hashtags = data.get("hashtags", [])
            for hashtag_wrapper in hashtags[:5]:
                if not isinstance(hashtag_wrapper, dict):
                    continue
                post = self._parse_hashtag_as_post(hashtag_wrapper)
                if post and post.external_id not in seen_ids:
                    seen_ids.add(post.external_id)
                    all_posts.append(post)

            if len(all_posts) >= limit:
                break

        logger.info(
            "[instagram] Search across %d keywords returned %d results (users + hashtags)",
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

        The instagram-looter2 API does not expose a comments endpoint,
        so this returns an empty list.
        """
        logger.debug("[instagram] get_post_comments not supported by current API (post %s)", post_id)
        return []

    async def get_trending(
        self,
        *,
        topic: str | None = None,
        limit: int = 25,
    ) -> list[UnifiedPost]:
        """Get trending Instagram content by searching for a topic."""
        if not self._available:
            return []

        query = topic or "trending"
        return await self.search_posts([query], limit=limit)

    async def health_check(self) -> bool:
        """Verify the Instagram API is reachable."""
        if not self._available:
            return False
        try:
            data = await self._get("/search", params={"query": "test"})
            return isinstance(data, dict) and data.get("status") == "ok"
        except Exception:
            return False
