"""Schemas for user API keys (BYOK)."""

from datetime import datetime

from pydantic import BaseModel, Field


class UserKeyCreateRequest(BaseModel):
    key_type: str = Field(pattern="^(openrouter|rapidapi)$")
    api_key: str = Field(min_length=1, max_length=500)


class UserKeyResponse(BaseModel):
    key_type: str
    is_set: bool = True
    created_at: datetime
    updated_at: datetime
