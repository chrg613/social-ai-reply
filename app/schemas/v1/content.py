from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReplyDraftRequest(BaseModel):
    opportunity_id: int
    voice_profile_id: int | None = Field(default=None, ge=1)
    platform: str | None = Field(
        default=None,
        pattern="^(reddit|twitter|linkedin|instagram|x)$",
        description="Override the opportunity's platform for tone selection",
    )
    variants: int = Field(
        default=1, ge=1, le=3,
        description="Number of reply variants to generate (each with slightly different style)",
    )


class ReplyDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    opportunity_id: int
    content: str
    rationale: str | None
    source_prompt: str | None
    version: int
    created_at: datetime


class ReplyDraftUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    rationale: str | None = Field(default=None, max_length=8000)


class PostDraftRequest(BaseModel):
    project_id: int


class PostDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    body: str
    rationale: str | None
    source_prompt: str | None
    version: int
    created_at: datetime


class PostDraftUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=40000)
    rationale: str | None = Field(default=None, max_length=8000)
