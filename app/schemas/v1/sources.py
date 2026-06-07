from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceCreateRequest(BaseModel):
    platform: str = Field(pattern="^(reddit|hacker_news|seo|geo|x|linkedin|article|ugc|manual)$")
    source_name: str = Field(min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=2000)
    status: str = Field(default="active", pattern="^(active|paused|archived|error)$")
    priority: int = Field(default=5, ge=1, le=10)
    config_json: str | None = Field(default=None, max_length=4000)


class SourceUpdateRequest(BaseModel):
    platform: str | None = Field(
        default=None, pattern="^(reddit|hacker_news|seo|geo|x|linkedin|article|ugc|manual)$"
    )
    source_name: str | None = Field(default=None, min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern="^(active|paused|archived|error)$")
    priority: int | None = Field(default=None, ge=1, le=10)
    config_json: str | None = Field(default=None, max_length=4000)


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    platform: str
    source_name: str
    source_url: str | None
    status: str
    priority: int
    config_json: str | None
    created_at: datetime
    updated_at: datetime
