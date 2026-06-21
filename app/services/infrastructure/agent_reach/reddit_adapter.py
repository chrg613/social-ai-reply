"""rdt-cli adapter — translates rdt-cli JSON output into RedditPost objects.

Bridges Agent-Reach's rdt-cli output format to SignalFlow's existing
RedditPost dataclass so the scoring, opportunity, and drafting pipelines
continue to work unchanged.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.services.product.reddit import RedditPost

logger = logging.getLogger(__name__)

def parse_rdt_posts(children: list[dict[str, Any]]) -> list[RedditPost]:
    """Parse rdt search result children into RedditPost objects.

    Args:
        children: List of post dicts from rdt search --json output
            (each is the ``data`` field of a ``t3`` child).

    Returns:
        List of RedditPost instances. Malformed entries are skipped.
    """
    posts: list[RedditPost] = []
    for child in children:
        post = _parse_rdt_post(child)
        if post:
            posts.append(post)
    return posts


def parse_rdt_read(data: dict[str, Any]) -> RedditPost | None:
    """Parse rdt read --json output into a RedditPost.

    The rdt read output includes the post and its comments. This
    function extracts the post data only (comments can be added later).
    """
    # rdt read returns a structure like:
    # {"ok": true, "data": [[{post data}], [comments...]]}
    # or just the post dict directly
    post_data = data
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, list) and inner:
            first = inner[0]
            if isinstance(first, list) and first:
                post_data = first[0]
            elif isinstance(first, dict):
                post_data = first
    return _parse_rdt_post(post_data)


def _parse_rdt_post(payload: dict[str, Any]) -> RedditPost | None:
    """Convert a single rdt post dict to RedditPost."""
    if not isinstance(payload, dict):
        return None

    post_id = payload.get("id", "")
    title = payload.get("title", "")
    if not post_id or not title:
        return None

    subreddit = payload.get("subreddit", "")
    author = payload.get("author", "[deleted]")
    body = payload.get("selftext", "") or ""
    permalink = payload.get("permalink", "")

    # Ensure permalink is a full URL
    if permalink and not permalink.startswith("http"):
        permalink = f"https://www.reddit.com{permalink}"

    # Parse created_utc (can be float timestamp or ISO string)
    created_at = _parse_created_utc(payload.get("created_utc") or payload.get("created", 0))

    num_comments = int(payload.get("num_comments") or 0)
    score = int(payload.get("score") or 0)

    return RedditPost(
        post_id=post_id,
        subreddit=subreddit,
        title=title,
        author=author,
        permalink=permalink,
        body=body,
        created_at=created_at,
        num_comments=num_comments,
        score=score,
    )


def _parse_created_utc(value: Any) -> datetime:
    """Parse created_utc from rdt output into a datetime."""
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (ValueError, TypeError):
            pass
    return datetime.now(UTC)
