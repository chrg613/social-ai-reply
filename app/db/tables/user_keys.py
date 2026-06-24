"""User API keys table operations (BYOK)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client

USER_API_KEYS_TABLE = "user_api_keys"


def get_user_key(db: Client, workspace_id: int, key_type: str) -> dict[str, Any] | None:
    """Get a single user API key by workspace and type."""
    result = (
        db.table(USER_API_KEYS_TABLE)
        .select("*")
        .eq("workspace_id", workspace_id)
        .eq("key_type", key_type)
        .execute()
    )
    return result.data[0] if result.data else None


def upsert_user_key(db: Client, workspace_id: int, key_type: str, encrypted_key: str) -> dict[str, Any]:
    """Insert or update a user API key (upsert on workspace_id + key_type)."""
    result = (
        db.table(USER_API_KEYS_TABLE)
        .upsert(
            {
                "workspace_id": workspace_id,
                "key_type": key_type,
                "encrypted_key": encrypted_key,
                "updated_at": "now()",
            },
            on_conflict="workspace_id,key_type",
        )
        .execute()
    )
    return result.data[0]


def delete_user_key(db: Client, workspace_id: int, key_type: str) -> None:
    """Delete a user API key by workspace and type."""
    db.table(USER_API_KEYS_TABLE).delete().eq("workspace_id", workspace_id).eq("key_type", key_type).execute()


def list_user_keys(db: Client, workspace_id: int) -> list[dict[str, Any]]:
    """List user API key metadata (key_type, created_at, updated_at) — never returns the encrypted key."""
    result = (
        db.table(USER_API_KEYS_TABLE)
        .select("key_type, created_at, updated_at")
        .eq("workspace_id", workspace_id)
        .order("created_at", desc=True)
        .execute()
    )
    return list(result.data)
