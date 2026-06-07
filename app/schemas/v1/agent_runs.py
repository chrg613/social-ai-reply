from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentRunCreateRequest(BaseModel):
    company_id: int
    agent_name: str = Field(min_length=1, max_length=255)


class AgentRunUpdateRequest(BaseModel):
    status: str | None = Field(default=None, max_length=50)
    finished_at: datetime | None = Field(default=None)
    items_fetched: int | None = Field(default=None, ge=0)
    items_kept: int | None = Field(default=None, ge=0)
    items_rejected: int | None = Field(default=None, ge=0)
    error_message: str | None = Field(default=None, max_length=4000)
    logs_json: str | None = Field(default=None, max_length=4000)


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    agent_name: str
    started_at: datetime | None
    finished_at: datetime | None
    status: str | None
    items_fetched: int | None
    items_kept: int | None
    items_rejected: int | None
    error_message: str | None
    logs_json: str | None
    created_at: datetime

    @field_validator("logs_json", mode="before")
    @classmethod
    def _normalize_logs_json(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            return "\n".join(str(v) for v in value) if value else None
        if isinstance(value, dict):
            import json
            return json.dumps(value)
        return str(value) if value else None
