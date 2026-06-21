"""Abstract base class for platform adapters."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.infrastructure.platforms.models import UnifiedComment, UnifiedPost

logger = logging.getLogger(__name__)


class PlatformAdapter(ABC):
    """Interface that every platform adapter must implement.

    The adapter pattern lets us swap out data sources per-platform
    without changing the scoring, relevance, or pipeline code.
    """

    platform_name: str = "unknown"

    @abstractmethod
    async def search_posts(
        self,
        keywords: list[str],
        *,
        limit: int = 50,
        sort: str = "relevance",
        time_filter: str = "week",
    ) -> list[UnifiedPost]:
        """Search for posts matching keywords.

        Args:
            keywords: Search terms to look for.
            limit: Maximum number of posts to return.
            sort: Sort order (relevance, hot, new, top).
            time_filter: Time window (hour, day, week, month, year, all).
        """

    @abstractmethod
    async def get_post_comments(
        self,
        post_id: str,
        *,
        limit: int = 20,
    ) -> list[UnifiedComment]:
        """Get comments/replies on a specific post."""

    @abstractmethod
    async def get_trending(
        self,
        *,
        topic: str | None = None,
        limit: int = 25,
    ) -> list[UnifiedPost]:
        """Get trending/hot posts, optionally filtered by topic."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify the adapter can reach its data source."""

    async def search_and_enrich(
        self,
        keywords: list[str],
        *,
        limit: int = 50,
        fetch_comments: bool = False,
        comments_per_post: int = 10,
    ) -> list[UnifiedPost]:
        """Search posts and optionally fetch top comments for each.

        This is a convenience method that combines search + comment fetching.
        Subclasses can override for more efficient batch operations.
        """
        posts = await self.search_posts(keywords, limit=limit)

        if fetch_comments:
            for post in posts:
                try:
                    comments = await self.get_post_comments(post.external_id, limit=comments_per_post)
                    post.raw_data["comments"] = [c.model_dump() for c in comments]
                    post.comments_count = max(post.comments_count, len(comments))
                except Exception as e:
                    logger.warning("Failed to fetch comments for %s/%s: %s", self.platform_name, post.external_id, e)

        return posts
