"""Content table operations: reply drafts, post drafts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)

REPLY_DRAFTS_TABLE = "reply_drafts"
POST_DRAFTS_TABLE = "post_drafts"


# Reply draft operations
def get_reply_draft_by_id(db: Client, draft_id: int) -> dict[str, Any] | None:
    """Get a reply draft by ID."""
    result = db.table(REPLY_DRAFTS_TABLE).select("*").eq("id", draft_id).execute()
    return result.data[0] if result.data else None


def list_reply_drafts_for_opportunity(db: Client, opportunity_id: int) -> list[dict[str, Any]]:
    """List all reply drafts for an opportunity."""
    result = (
        db.table(REPLY_DRAFTS_TABLE)
        .select("*")
        .eq("opportunity_id", opportunity_id)
        .order("created_at", desc=True)
        .execute()
    )
    return list(result.data)


def list_reply_drafts_for_project(
    db: Client,
    project_id: int,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List reply drafts for a project with pagination."""
    result = (
        db.table(REPLY_DRAFTS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return list(result.data)


def count_reply_drafts_for_project(db: Client, project_id: int, status: str | None = None) -> int:
    """Count reply drafts for a project, optionally filtered by status."""
    query = db.table(REPLY_DRAFTS_TABLE).select("*", count="exact").eq("project_id", project_id)
    if status:
        query = query.eq("status", status)
    result = query.execute()
    return result.count or 0


def create_reply_draft(db: Client, draft_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new reply draft."""
    result = db.table(REPLY_DRAFTS_TABLE).insert(draft_data).execute()
    return result.data[0]


def update_reply_draft(db: Client, draft_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a reply draft."""
    result = db.table(REPLY_DRAFTS_TABLE).update(update_data).eq("id", draft_id).execute()
    return result.data[0] if result.data else None


def delete_reply_draft(db: Client, draft_id: int) -> None:
    """Delete a reply draft."""
    db.table(REPLY_DRAFTS_TABLE).delete().eq("id", draft_id).execute()


def list_reply_drafts_for_opportunities(db: Client, opportunity_ids: list[int]) -> list[dict[str, Any]]:
    """List all reply drafts for a set of opportunity IDs (batch query)."""
    if not opportunity_ids:
        return []
    result = (
        db.table(REPLY_DRAFTS_TABLE)
        .select("*")
        .in_("opportunity_id", opportunity_ids)
        .order("created_at", desc=True)
        .execute()
    )
    return list(result.data)


def get_draft_by_project_and_opportunity(
    db: Client,
    project_id: int,
    opportunity_id: int,
) -> dict[str, Any] | None:
    """Get a reply draft by project and opportunity ID."""
    result = (
        db.table(REPLY_DRAFTS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .eq("opportunity_id", opportunity_id)
        .execute()
    )
    return result.data[0] if result.data else None


# Post draft operations
def get_post_draft_by_id(db: Client, draft_id: int) -> dict[str, Any] | None:
    """Get a post draft by ID."""
    result = db.table(POST_DRAFTS_TABLE).select("*").eq("id", draft_id).execute()
    return result.data[0] if result.data else None


def list_post_drafts_for_project(
    db: Client,
    project_id: int,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List post drafts for a project with pagination."""
    result = (
        db.table(POST_DRAFTS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return list(result.data)


def create_post_draft(db: Client, draft_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new post draft."""
    result = db.table(POST_DRAFTS_TABLE).insert(draft_data).execute()
    return result.data[0]


def update_post_draft(db: Client, draft_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a post draft."""
    result = db.table(POST_DRAFTS_TABLE).update(update_data).eq("id", draft_id).execute()
    return result.data[0] if result.data else None


def delete_post_draft(db: Client, draft_id: int) -> None:
    """Delete a post draft."""
    db.table(POST_DRAFTS_TABLE).delete().eq("id", draft_id).execute()
