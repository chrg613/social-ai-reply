"""Analytics events table operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client

ANALYTICS_EVENTS_TABLE = "analytics_events"


def get_analytics_event_by_id(db: Client, event_id: int) -> dict[str, Any] | None:
    """Get an analytics event by ID."""
    result = db.table(ANALYTICS_EVENTS_TABLE).select("*").eq("id", event_id).execute()
    return result.data[0] if result.data else None


def list_analytics_events_for_company(
    db: Client,
    company_id: int,
    event_type: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List analytics events for a company with optional filters."""
    query = db.table(ANALYTICS_EVENTS_TABLE).select("*").eq("company_id", company_id)
    if event_type:
        query = query.eq("event_type", event_type)
    if start_date:
        query = query.gte("created_at", start_date.isoformat())
    if end_date:
        query = query.lte("created_at", end_date.isoformat())
    result = query.order("created_at", desc=True).limit(limit).execute()
    return list(result.data)


def create_analytics_event(db: Client, data: dict[str, Any]) -> dict[str, Any]:
    """Create a new analytics event."""
    result = db.table(ANALYTICS_EVENTS_TABLE).insert(data).execute()
    return result.data[0]


def get_analytics_summary(db: Client, company_id: int, days: int = 30) -> dict[str, Any]:
    """Return aggregated analytics counts by event_type for a company over the last N days."""
    start = datetime.now(UTC) - timedelta(days=days)
    result = (
        db.table(ANALYTICS_EVENTS_TABLE)
        .select("event_type")
        .eq("company_id", company_id)
        .gte("created_at", start.isoformat())
        .execute()
    )
    counts: dict[str, int] = {}
    for row in result.data:
        event_type = row.get("event_type", "unknown")
        counts[event_type] = counts.get(event_type, 0) + 1
    return {"company_id": company_id, "days": days, "counts": counts}
