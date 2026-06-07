"""Feedback table operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client

FEEDBACK_TABLE = "feedback"


def get_feedback_by_id(db: Client, feedback_id: int) -> dict[str, Any] | None:
    """Get feedback by ID."""
    result = db.table(FEEDBACK_TABLE).select("*").eq("id", feedback_id).execute()
    return result.data[0] if result.data else None


def list_feedback_for_company(
    db: Client,
    company_id: int,
    opportunity_id: int | None = None,
) -> list[dict[str, Any]]:
    """List feedback for a company with optional opportunity filter."""
    query = db.table(FEEDBACK_TABLE).select("*").eq("company_id", company_id)
    if opportunity_id:
        query = query.eq("opportunity_id", opportunity_id)
    result = query.order("created_at", desc=True).execute()
    return list(result.data)


def create_feedback(db: Client, data: dict[str, Any]) -> dict[str, Any]:
    """Create new feedback."""
    result = db.table(FEEDBACK_TABLE).insert(data).execute()
    return result.data[0]


def get_feedback_stats_for_company(db: Client, company_id: int) -> dict[str, Any]:
    """Return counts of feedback by action for a company."""
    result = db.table(FEEDBACK_TABLE).select("action").eq("company_id", company_id).execute()
    stats: dict[str, int] = {}
    for row in result.data:
        action = row.get("action", "unknown")
        stats[action] = stats.get(action, 0) + 1
    return {"company_id": company_id, "counts": stats}
