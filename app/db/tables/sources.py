"""Sources table operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client

SOURCES_TABLE = "sources"


def get_source_by_id(db: Client, source_id: int) -> dict[str, Any] | None:
    """Get a source by ID."""
    result = db.table(SOURCES_TABLE).select("*").eq("id", source_id).execute()
    return result.data[0] if result.data else None


def list_sources_for_company(db: Client, company_id: int, status: str | None = None) -> list[dict[str, Any]]:
    """List sources for a company with optional status filter."""
    query = db.table(SOURCES_TABLE).select("*").eq("company_id", company_id)
    if status:
        query = query.eq("status", status)
    result = query.order("priority", desc=True).execute()
    return list(result.data)


def list_sources_for_company_and_platform(db: Client, company_id: int, platform: str) -> list[dict[str, Any]]:
    """List sources for a company and platform."""
    result = (
        db.table(SOURCES_TABLE)
        .select("*")
        .eq("company_id", company_id)
        .eq("platform", platform)
        .order("priority", desc=True)
        .execute()
    )
    return list(result.data)


def create_source(db: Client, data: dict[str, Any]) -> dict[str, Any]:
    """Create a new source."""
    result = db.table(SOURCES_TABLE).insert(data).execute()
    return result.data[0]


def update_source(db: Client, source_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a source."""
    result = db.table(SOURCES_TABLE).update(data).eq("id", source_id).execute()
    return result.data[0] if result.data else None


def delete_source(db: Client, source_id: int) -> None:
    """Delete a source."""
    db.table(SOURCES_TABLE).delete().eq("id", source_id).execute()
