from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.v1.billing import SubscriptionResponse
from app.schemas.v1.discovery import OpportunityResponse


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class ProjectUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    status: str = Field(default="active", pattern="^(active|archived)$")


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    name: str
    slug: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def map_status(cls, data: dict) -> dict:
        if isinstance(data, dict) and "is_active" in data and "status" not in data:
            data["status"] = "active" if data["is_active"] else "archived"
        return data


class SetupStatus(BaseModel):
    brand_configured: bool = False
    personas_count: int = 0
    subreddits_count: int = 0


class DashboardResponse(BaseModel):
    projects: list[ProjectResponse]
    top_opportunities: list[OpportunityResponse]
    subscription: SubscriptionResponse
    setup_status: SetupStatus = SetupStatus()
    drafts_count: int = 0
    published_count: int = 0
