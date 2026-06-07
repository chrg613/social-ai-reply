from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BrandKeywordCreateRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=255)
    type: str = Field(
        pattern="^(core|pain_point|competitor|alternative|audience|location|problem|feature|buying_intent|question)$"
    )
    weight: int = Field(default=1, ge=1, le=10)
    source: str | None = Field(default=None, max_length=255)


class BrandKeywordUpdateRequest(BaseModel):
    keyword: str | None = Field(default=None, min_length=1, max_length=255)
    type: str | None = Field(
        default=None,
        pattern="^(core|pain_point|competitor|alternative|audience|location|problem|feature|buying_intent|question)$",
    )
    weight: int | None = Field(default=None, ge=1, le=10)
    source: str | None = Field(default=None, max_length=255)
    is_enabled: bool | None = Field(default=None)


class BrandKeywordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    keyword: str
    type: str
    weight: int
    source: str | None
    times_matched: int
    times_approved: int
    times_rejected: int
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
