"""Company profile table operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client

COMPANY_TABLE = "company_profiles"


def get_company_by_id(db: Client, company_id: int) -> dict[str, Any] | None:
    """Get a company profile by ID."""
    result = db.table(COMPANY_TABLE).select("*").eq("id", company_id).execute()
    return result.data[0] if result.data else None


def get_company_by_workspace(db: Client, workspace_id: int) -> dict[str, Any] | None:
    """Get a company profile by workspace ID."""
    result = db.table(COMPANY_TABLE).select("*").eq("workspace_id", workspace_id).execute()
    return result.data[0] if result.data else None


def list_companies_for_workspace(db: Client, workspace_id: int) -> list[dict[str, Any]]:
    """List all company profiles for a workspace."""
    result = (
        db.table(COMPANY_TABLE)
        .select("*")
        .eq("workspace_id", workspace_id)
        .order("created_at", desc=True)
        .execute()
    )
    return list(result.data)


def create_company(db: Client, data: dict[str, Any]) -> dict[str, Any]:
    """Create a new company profile."""
    result = db.table(COMPANY_TABLE).insert(data).execute()
    return result.data[0]


def update_company(db: Client, company_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a company profile."""
    result = db.table(COMPANY_TABLE).update(data).eq("id", company_id).execute()
    return result.data[0] if result.data else None


def delete_company(db: Client, company_id: int) -> None:
    """Delete a company profile."""
    db.table(COMPANY_TABLE).delete().eq("id", company_id).execute()
