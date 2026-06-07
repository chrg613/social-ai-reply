from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsEventCreateRequest(BaseModel):
    company_id: int
    opportunity_id: int | None = Field(default=None)
    event_type: str = Field(min_length=1, max_length=255)
    metadata_json: str | None = Field(default=None, max_length=4000)


class AnalyticsEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    opportunity_id: int | None
    event_type: str
    metadata_json: str | None
    created_at: datetime


class AnalyticsSummaryResponse(BaseModel):
    total_events: int
    events_by_type: dict[str, int]
    opportunities_found: int
    opportunities_approved: int
    opportunities_rejected: int
    drafts_copied: int
