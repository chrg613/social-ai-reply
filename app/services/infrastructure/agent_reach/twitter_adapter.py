"""twitter-cli adapter — translates twitter-cli JSON output into SocialPost objects.

Bridges Agent-Reach's twitter-cli output format to SignalFlow's
SocialPost dataclass for the multi-platform discovery pipeline.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.services.product.social_post import SocialPost

logger = logging.getLogger(__name__)


def parse_twitter_results(tweets: list[dict[str, Any]]) -> list[SocialPost]:
    """Parse twitter search result list into SocialPost objects.

    Args:
        tweets: List of tweet dicts from twitter search --json output.

    Returns:
        List of SocialPost instances. Malformed entries are skipped.
    """
    posts: list[SocialPost] = []
    for tweet in tweets:
        post = _parse_tweet(tweet)
        if post:
            posts.append(post)
    return posts


def _parse_tweet(payload: dict[str, Any]) -> SocialPost | None:
    """Convert a single tweet dict to SocialPost."""
    if not isinstance(payload, dict):
        return None

    tweet_id = str(payload.get("id", ""))
    text = payload.get("text", "")
    if not tweet_id or not text:
        return None

    author_info = payload.get("author", {})
    if isinstance(author_info, dict):
        author_name = author_info.get("screenName", "") or author_info.get("name", "unknown")
    else:
        author_name = "unknown"

    metrics = payload.get("metrics", {})
    if isinstance(metrics, dict):
        likes = int(metrics.get("likes", 0) or 0)
        retweets = int(metrics.get("retweets", 0) or 0)
        replies = int(metrics.get("replies", 0) or 0)
        views = int(metrics.get("views", 0) or 0)
    else:
        likes = retweets = replies = views = 0

    created_at = _parse_twitter_date(payload.get("createdAtISO") or payload.get("createdAt", ""))

    tweet_url = f"https://x.com/{author_name}/status/{tweet_id}"

    return SocialPost(
        post_id=tweet_id,
        platform="twitter",
        title="",  # tweets don't have separate titles
        body=text,
        author=author_name,
        url=tweet_url,
        created_at=created_at,
        score=likes,
        num_comments=replies,
        community="twitter",
        extra_metrics={
            "retweets": retweets,
            "views": views,
        },
    )


def _parse_twitter_date(value: str) -> datetime:
    """Parse Twitter date string into datetime.

    Twitter outputs dates as ISO 8601 (e.g. '2026-04-30T11:48:43+00:00')
    or in the legacy format (e.g. 'Thu Apr 30 11:48:43 +0000 2026').
    """
    if not value:
        return datetime.now(UTC)

    # Try ISO format first
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        pass

    # Try legacy Twitter format
    try:
        return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        pass

    return datetime.now(UTC)
