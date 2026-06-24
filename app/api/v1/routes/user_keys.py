"""User API key CRUD endpoints (BYOK)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.api.v1.deps import ensure_workspace_membership, get_current_user, get_current_workspace
from app.db.supabase_client import get_supabase
from app.db.tables.user_keys import delete_user_key, list_user_keys, upsert_user_key
from app.schemas.v1.user_keys import UserKeyCreateRequest, UserKeyResponse
from app.utils.encryption import encrypt_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["user-keys"])


@router.get("/user-keys", response_model=list[UserKeyResponse])
def list_keys(
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[UserKeyResponse]:
    """List stored key types (masked — never returns the raw key)."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    rows = list_user_keys(supabase, workspace["id"])
    return [
        UserKeyResponse(
            key_type=row["key_type"],
            is_set=True,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


@router.post("/user-keys", response_model=UserKeyResponse, status_code=status.HTTP_201_CREATED)
def save_key(
    payload: UserKeyCreateRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> UserKeyResponse:
    """Encrypt and store (or update) a user API key."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    encrypted = encrypt_text(payload.api_key)
    row = upsert_user_key(supabase, workspace["id"], payload.key_type, encrypted)
    return UserKeyResponse(
        key_type=row["key_type"],
        is_set=True,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.delete("/user-keys/{key_type}")
def remove_key(
    key_type: str,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, bool]:
    """Delete a user API key."""
    if key_type not in ("openrouter", "rapidapi"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid key type.")
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    delete_user_key(supabase, workspace["id"], key_type)
    return {"ok": True}
