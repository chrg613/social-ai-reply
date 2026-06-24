"""Voice profile table operations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)
VOICE_PROFILES_TABLE = "voice_profiles"


def get_voice_profile_by_id(db: Client, profile_id: int) -> dict[str, Any] | None:
    """Get a voice profile by ID."""
    try:
        result = db.table(VOICE_PROFILES_TABLE).select("*").eq("id", profile_id).execute()
        return result.data[0] if result.data else None
    except Exception:
        logger.debug("voice_profiles table not available — returning None")
        return None


def list_voice_profiles_for_project(db: Client, project_id: int) -> list[dict[str, Any]]:
    """List all voice profiles for a project."""
    try:
        result = (
            db.table(VOICE_PROFILES_TABLE)
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .execute()
        )
        return list(result.data)
    except Exception:
        logger.debug("voice_profiles table not available — returning []")
        return []


def create_voice_profile(db: Client, profile_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new voice profile."""
    result = db.table(VOICE_PROFILES_TABLE).insert(profile_data).execute()
    return result.data[0]


def update_voice_profile(db: Client, profile_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a voice profile."""
    result = db.table(VOICE_PROFILES_TABLE).update(update_data).eq("id", profile_id).execute()
    return result.data[0] if result.data else None


def delete_voice_profile(db: Client, profile_id: int) -> None:
    """Delete a voice profile."""
    db.table(VOICE_PROFILES_TABLE).delete().eq("id", profile_id).execute()


def get_default_voice_profile_for_project(db: Client, project_id: int) -> dict[str, Any] | None:
    """Get the default voice profile for a project, if one is set."""
    try:
        result = (
            db.table(VOICE_PROFILES_TABLE)
            .select("*")
            .eq("project_id", project_id)
            .eq("is_default", True)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        logger.debug("voice_profiles table not available — returning None")
        return None


def unset_default_voice_profiles_for_project(
    db: Client,
    project_id: int,
    exclude_id: int | None = None,
) -> None:
    """Unset is_default on all voice profiles for a project (optionally excluding one)."""
    query = db.table(VOICE_PROFILES_TABLE).update({"is_default": False}).eq("project_id", project_id)
    if exclude_id is not None:
        query = query.neq("id", exclude_id)
    query.execute()
