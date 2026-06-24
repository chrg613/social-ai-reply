from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class BrandProfileRequest(BaseModel):
    brand_name: str = Field(min_length=2, max_length=255)
    website_url: HttpUrl | None = None
    summary: str | None = Field(default=None, max_length=4000)
    voice_notes: str | None = Field(default=None, max_length=4000)
    product_summary: str | None = Field(default=None, max_length=4000)
    target_audience: str | None = Field(default=None, max_length=4000)
    call_to_action: str | None = Field(default=None, max_length=4000)
    business_domain: str | None = Field(default=None, max_length=255)
    reddit_username: str | None = Field(default=None, max_length=255)
    linkedin_url: HttpUrl | None = None


class BrandAnalysisRequest(BaseModel):
    website_url: HttpUrl


class BrandProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    brand_name: str
    website_url: str | None = None
    summary: str | None = None
    voice_notes: str | None = None
    product_summary: str | None = None
    target_audience: str | None = None
    call_to_action: str | None = None
    business_domain: str | None = None
    reddit_username: str | None = None
    linkedin_url: str | None
    last_analyzed_at: datetime | None = None
