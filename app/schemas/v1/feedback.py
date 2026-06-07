from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FeedbackCreateRequest(BaseModel):
    opportunity_id: int
    action: str = Field(pattern="^(approved|rejected|copied|posted|marked_irrelevant|regenerated)$")
    reason: str | None = Field(default=None, max_length=4000)


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    opportunity_id: int
    company_id: int
    action: str
    reason: str | None
    created_at: datetime
