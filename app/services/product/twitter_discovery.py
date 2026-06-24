"""Twitter/X discovery service via Agent-Reach twitter-cli.

Mirrors the structure of RedditDiscoveryService but for Twitter/X.
Discovers relevant tweets using twitter-cli search, normalises them
into SocialPost objects, and integrates with the scoring pipeline.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.infrastructure.agent_reach.client import AgentReachClient
from app.services.infrastructure.agent_reach.twitter_adapter import parse_twitter_results

if TYPE_CHECKING:
    from app.services.product.social_post import SocialPost

log = logging.getLogger("signalflow.twitter_discovery")


class TwitterDiscoveryService:
    """Discover relevant tweets via twitter-cli (Agent-Reach)."""

    def __init__(self) -> None:
        self._client = AgentReachClient()

    def search_tweets(
        self,
        keywords: list[str],
        *,
        limit: int = 20,
    ) -> list[SocialPost]:
        """Search Twitter/X for posts matching the given keywords.

        Uses twitter-cli search with multiple keyword queries and
        deduplicates results by tweet ID.

        Returns:
            List of SocialPost objects from Twitter. Returns an empty
            list (never raises) if twitter-cli is unavailable.
        """
        if not self._client.twitter_available:
            log.info("twitter-cli not available — skipping Twitter discovery")
            return []

        posts_by_id: dict[str, SocialPost] = {}

        for keyword in keywords[:6]:
            try:
                results = self._client.twitter_search(
                    keyword,
                    search_type="top",
                    limit=limit,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("twitter search failed for %r: %s", keyword, exc)
                continue

            if results is None:
                continue

            parsed = parse_twitter_results(results)
            for post in parsed:
                if post.post_id and post.post_id not in posts_by_id:
                    posts_by_id[post.post_id] = post

        # Also search for latest (recent) tweets for freshness
        for keyword in keywords[:3]:
            try:
                results = self._client.twitter_search(
                    keyword,
                    search_type="latest",
                    limit=min(limit, 10),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("twitter latest search failed for %r: %s", keyword, exc)
                continue

            if results is None:
                continue

            parsed = parse_twitter_results(results)
            for post in parsed:
                if post.post_id and post.post_id not in posts_by_id:
                    posts_by_id[post.post_id] = post

        return list(posts_by_id.values())
