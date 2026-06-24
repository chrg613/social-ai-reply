from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _strip_nonempty(value: str, field_name: str, min_len: int = 2) -> str:
    value = value.strip()
    if len(value) < min_len:
        raise ValueError(f"{field_name} must be at least {min_len} characters after trimming whitespace.")
    return value


class AuthRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=255)
    workspace_name: str = Field(min_length=2, max_length=255)

    @field_validator("full_name", mode="before")
    @classmethod
    def strip_full_name(cls, v: str) -> str:
        return _strip_nonempty(v, "full_name")

    @field_validator("workspace_name", mode="before")
    @classmethod
    def strip_workspace_name(cls, v: str) -> str:
        return _strip_nonempty(v, "workspace_name")


class OAuthCompleteRequest(BaseModel):
    workspace_name: str = Field(min_length=2, max_length=255)

    @field_validator("workspace_name", mode="before")
    @classmethod
    def strip_workspace_name(cls, v: str) -> str:
        return _strip_nonempty(v, "workspace_name")


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supabase_uid: str
    email: EmailStr
    full_name: str
    is_active: bool


class WorkspaceSummary(BaseModel):
    id: int
    name: str
    slug: str
    role: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    user: UserResponse
    workspace: WorkspaceSummary
