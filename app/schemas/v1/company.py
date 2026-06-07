from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _jsonb_to_str(value: Any) -> str | None:
    """Convert JSONB array to comma-separated string, or return as-is if already a string."""
    if value is None:
        return None
    if isinstance(value, list):
        if not value:
            return None
        return ", ".join(str(v) for v in value)
    if isinstance(value, str):
        return value
    return str(value)


class CompanyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    website_url: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=255)
    target_audience: str | None = Field(default=None, max_length=4000)
    geography: str | None = Field(default=None, max_length=255)
    language: str = Field(default="en", pattern="^[a-z]{2}$")
    features: str | None = Field(default=None, max_length=4000)
    benefits: str | None = Field(default=None, max_length=4000)
    pain_points: str | None = Field(default=None, max_length=4000)
    competitors: str | None = Field(default=None, max_length=4000)
    brand_voice: str | None = Field(default=None, max_length=4000)
    forbidden_claims: str | None = Field(default=None, max_length=4000)
    preferred_cta: str | None = Field(default=None, max_length=4000)


class CompanyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    website_url: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=255)
    target_audience: str | None = Field(default=None, max_length=4000)
    geography: str | None = Field(default=None, max_length=255)
    language: str | None = Field(default=None, pattern="^[a-z]{2}$")
    features: str | None = Field(default=None, max_length=4000)
    benefits: str | None = Field(default=None, max_length=4000)
    pain_points: str | None = Field(default=None, max_length=4000)
    competitors: str | None = Field(default=None, max_length=4000)
    brand_voice: str | None = Field(default=None, max_length=4000)
    forbidden_claims: str | None = Field(default=None, max_length=4000)
    preferred_cta: str | None = Field(default=None, max_length=4000)
    extracted_summary: str | None = Field(default=None, max_length=4000)
    extracted_keywords: str | None = Field(default=None, max_length=4000)
    extracted_pain_points: str | None = Field(default=None, max_length=4000)
    extracted_competitors: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = Field(default=None)


class CompanyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    name: str
    website_url: str | None
    description: str | None
    category: str | None
    target_audience: str | None
    geography: str | None
    language: str
    features: str | None
    benefits: str | None
    pain_points: str | None
    competitors: str | None
    brand_voice: str | None
    forbidden_claims: str | None
    preferred_cta: str | None
    extracted_summary: str | None
    extracted_keywords: str | None
    extracted_pain_points: str | None
    extracted_competitors: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("features", "benefits", "pain_points", "competitors", "extracted_keywords", "extracted_pain_points", "extracted_competitors", mode="before")
    @classmethod
    def _normalize_jsonb(cls, value: Any) -> str | None:
        return _jsonb_to_str(value)
