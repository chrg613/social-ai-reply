"""Pydantic v2 schemas for the Competitor Intelligence feature."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CompetitorMentionResponse(BaseModel):
    """A single competitor mention detected from social media."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    opportunity_id: int | None = None
    competitor_name: str
    sentiment: str
    sentiment_score: float
    complaint_category: str | None = None
    complaint_detail: str | None = None
    source_platform: str
    source_url: str | None = None
    post_title: str | None = None
    post_body: str | None = None
    detected_at: datetime | None = None
    created_at: datetime


class CompetitorStatsResponse(BaseModel):
    """Aggregated stats for a single competitor."""

    competitor_name: str
    total_mentions: int
    negative_count: int
    neutral_count: int
    positive_count: int
    top_complaints: list[str]
    avg_sentiment_score: float


class CompetitorScanRequest(BaseModel):
    """Request to trigger a competitor scan."""

    platforms: list[str] = Field(default=["reddit", "twitter"])
