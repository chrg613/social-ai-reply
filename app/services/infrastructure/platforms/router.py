"""Platform router — dispatches requests to the correct adapter.

Each platform has its own search strategy:
  - Reddit:    Browse subreddits via RapidAPI (reddit34)
  - Twitter/X: Direct keyword search via RapidAPI (twitter154)
  - Instagram: Global search (users + hashtags) via RapidAPI (instagram-looter2)
  - LinkedIn:  Keyword search via RapidAPI (fresh-linkedin-scraper-api)
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.infrastructure.platforms.base import PlatformAdapter
    from app.services.infrastructure.platforms.models import UnifiedPost

logger = logging.getLogger(__name__)

# Lazy-loaded registry of adapters
_adapters: dict[str, PlatformAdapter] = {}

# Supported platforms and their search characteristics
PLATFORM_INFO = {
    "reddit": {"host": "reddit34.p.rapidapi.com", "search": "subreddit browsing", "limit": "1000/hr"},
    "twitter": {"host": "twitter154.p.rapidapi.com", "search": "keyword search", "limit": "1000/hr"},
    "x": {"host": "twitter154.p.rapidapi.com", "search": "keyword search (alias for twitter)", "limit": "1000/hr"},
    "instagram": {"host": "instagram-looter2.p.rapidapi.com", "search": "global search (users + hashtags)", "limit": "150/month"},
    "linkedin": {"host": "fresh-linkedin-scraper-api.p.rapidapi.com", "search": "keyword search", "limit": "1000/hr"},
}


def _get_adapter(platform: str, *, workspace_id: int | None = None, db: Any = None) -> PlatformAdapter:
    """Get or create a platform adapter by name.

    When ``workspace_id`` and ``db`` are provided, checks for a custom scraper
    configuration in the database first and returns a DynamicAdapter if one
    exists.  This is what connects the "Scraper Setup" UI to actual scanning.
    """
    # Normalize platform name
    normalized = platform.strip().lower()
    if normalized == "x":
        normalized = "twitter"

    # Check for a custom scraper configuration (DB-driven DynamicAdapter)
    if workspace_id is not None and db is not None:
        try:
            from app.db.tables.custom_scrapers import get_custom_scraper_by_platform
            custom = get_custom_scraper_by_platform(db, workspace_id, normalized)
            if custom:
                from app.services.infrastructure.platforms.dynamic_adapter import DynamicAdapter
                logger.info(
                    "Using custom scraper for %s (host=%s, endpoint=%s)",
                    normalized, custom.get("api_host"), custom.get("search_endpoint"),
                )
                return DynamicAdapter(custom)
        except Exception as exc:
            logger.warning("Failed to load custom scraper for %s: %s", normalized, exc)

    if normalized not in _adapters:
        if normalized == "reddit":
            from app.services.infrastructure.platforms.reddit import RedditAdapter
            _adapters[normalized] = RedditAdapter()
        elif normalized == "twitter":
            from app.services.infrastructure.platforms.twitter import TwitterAdapter
            _adapters[normalized] = TwitterAdapter()
        elif normalized == "instagram":
            from app.services.infrastructure.platforms.instagram import InstagramAdapter
            _adapters[normalized] = InstagramAdapter()
        elif normalized == "linkedin":
            from app.services.infrastructure.platforms.linkedin import LinkedInAdapter
            _adapters[normalized] = LinkedInAdapter()
        else:
            # Unknown platform — check if there's a custom scraper config
            # even without workspace context (best-effort)
            raise ValueError(
                f"Unknown platform: {platform}. "
                f"Supported: {', '.join(PLATFORM_INFO.keys())}. "
                f"Or set up a custom scraper for this platform."
            )
    return _adapters[normalized]


class PlatformRouter:
    """Routes search/fetch requests to the correct platform adapter.

    Usage:
        router = PlatformRouter(platforms=["reddit", "twitter"])
        posts = await router.search_all(keywords=["virtual tour", "real estate tech"])
    """

    def __init__(self, platforms: list[str] | None = None, *, workspace_id: int | None = None, db: Any = None):
        self.platforms = platforms or ["reddit"]
        self.workspace_id = workspace_id
        self.db = db

    async def search_all(
        self,
        keywords: list[str],
        *,
        limit_per_platform: int = 25,
        fetch_comments: bool = False,
        time_filter: str = "week",
    ) -> list[UnifiedPost]:
        """Search across all configured platforms and merge results.

        Each platform uses its own search strategy:
        - Twitter: direct keyword search (best for keyword matching)
        - Reddit: subreddit browsing + scoring pipeline
        - Instagram: profile posts (keywords treated as usernames)

        Returns posts sorted by engagement score (highest first).
        """
        all_posts: list[UnifiedPost] = []

        # Per-platform timeout.  Reddit browses 10+ subreddits and fetches
        # comments, Instagram search can also be slow — 120s gives each
        # adapter enough headroom without blocking the scan forever.
        per_platform_timeout = 120.0

        async def _search_one(platform: str) -> list[UnifiedPost]:
            adapter = _get_adapter(platform, workspace_id=self.workspace_id, db=self.db)
            return await asyncio.wait_for(
                adapter.search_and_enrich(
                    keywords,
                    limit=limit_per_platform,
                    fetch_comments=fetch_comments,
                    time_filter=time_filter,
                ),
                timeout=per_platform_timeout,
            )

        tasks = [_search_one(p) for p in self.platforms]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for platform, result in zip(self.platforms, results, strict=False):
            if isinstance(result, TimeoutError):
                logger.warning("[%s] Timed out after %.0fs — skipping", platform, per_platform_timeout)
            elif isinstance(result, Exception):
                logger.error("[%s] Search failed: %s", platform, result)
            else:
                logger.info("[%s] Found %d posts for keywords %s", platform, len(result), keywords[:3])
                all_posts.extend(result)

        # Compute engagement scores and sort
        for post in all_posts:
            post.compute_engagement_score()

        all_posts.sort(key=lambda p: p.engagement_score, reverse=True)
        return all_posts

    async def get_comments(
        self,
        platform: str,
        post_id: str,
        *,
        limit: int = 20,
    ) -> list[Any]:
        """Get comments for a specific post on a specific platform."""
        adapter = _get_adapter(platform, workspace_id=self.workspace_id, db=self.db)
        return await adapter.get_post_comments(post_id, limit=limit)

    async def health_check_all(self) -> dict[str, bool]:
        """Check health of all configured platforms."""
        results = {}
        for platform in self.platforms:
            try:
                adapter = _get_adapter(platform, workspace_id=self.workspace_id, db=self.db)
                results[platform] = await adapter.health_check()
            except Exception:
                results[platform] = False
        return results
