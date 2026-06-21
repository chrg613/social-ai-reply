"""Unified post/comment models for cross-platform social intelligence."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class UnifiedPost(BaseModel):
    """Platform-agnostic post representation.

    Every platform adapter normalizes its response into this model,
    so the scoring/relevance engine works identically regardless of source.
    """

    platform: str = Field(description="Source platform: reddit, twitter, instagram, tiktok, linkedin, hackernews")
    external_id: str = Field(description="Platform-specific post ID")
    author: str = Field(default="")
    author_id: str = Field(default="", description="Platform-specific author/user ID")
    title: str | None = Field(default=None, description="Post title (Reddit/HN have titles; Twitter/IG don't)")
    body: str = Field(default="", description="Post body text, tweet content, caption")
    url: str = Field(default="", description="Permalink to the post")
    subreddit: str | None = Field(default=None, description="Subreddit name (Reddit only)")
    hashtags: list[str] = Field(default_factory=list, description="Hashtags extracted from content")

    # Engagement metrics (normalized across platforms)
    upvotes: int = Field(default=0, description="Likes/upvotes/hearts")
    comments_count: int = Field(default=0, description="Number of comments/replies")
    shares: int = Field(default=0, description="Retweets/reposts/shares")
    views: int = Field(default=0, description="View count if available")
    engagement_score: float = Field(default=0.0, description="Calculated: upvotes + comments*2 + shares*3")

    # Timestamps
    created_at: datetime | None = Field(default=None)
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    # Media
    media_urls: list[str] = Field(default_factory=list, description="Attached images/videos")

    # Raw data for platform-specific fields
    raw_data: dict[str, Any] = Field(default_factory=dict, description="Original API response")

    def compute_engagement_score(self) -> float:
        """Calculate a normalized engagement score."""
        self.engagement_score = float(self.upvotes + self.comments_count * 2 + self.shares * 3)
        return self.engagement_score


class UnifiedComment(BaseModel):
    """Platform-agnostic comment representation."""

    platform: str
    external_id: str
    post_id: str = Field(description="ID of the parent post")
    author: str = Field(default="")
    body: str = Field(default="")
    upvotes: int = Field(default=0)
    created_at: datetime | None = Field(default=None)
    parent_comment_id: str | None = Field(default=None, description="For nested/threaded comments")
    raw_data: dict[str, Any] = Field(default_factory=dict)
