"""Schemas for Reddit OAuth and posting endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RedditConnectRequest(BaseModel):
    """Request to begin Reddit OAuth. Currently has no required fields, but accepted for forward compatibility."""

    redirect_url: str | None = Field(default=None, max_length=2048)


class RedditConnectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    auth_url: str
    state: str
    message: str = "Redirect user to this URL to authorize Reddit access."


class RedditCallbackRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=8, max_length=128)
    username: str | None = Field(default=None, max_length=255)


class RedditAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    karma: int = 0
    is_active: bool = True
    connected_at: datetime | None = Field(default=None, alias="created_at")
    message: str | None = None


class RedditAccountListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[RedditAccountResponse]


class RedditPostRequest(BaseModel):
    reddit_account_id: int
    project_id: int
    type: Literal["comment", "post"] = "comment"
    subreddit: str = Field(min_length=2, max_length=255)
    content: str = Field(min_length=1, max_length=40000)
    title: str | None = Field(default=None, max_length=300)
    parent_post_id: str | None = Field(default=None, max_length=64)
    campaign_id: int | None = None
    override_safety: bool = False


class RedditPostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    subreddit: str
    permalink: str
    status: str
    published_at: datetime | None = None


class PublishedPostItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    subreddit: str
    title: str | None = None
    content: str | None = None
    status: str | None = None
    upvotes: int = 0
    permalink: str
    published_at: datetime | None = None


class PublishedPostListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[PublishedPostItem]


class PublishedPostStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    upvotes: int
    last_checked_at: datetime | None = None
