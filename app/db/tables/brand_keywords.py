"""Brand keywords table operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client

BRAND_KEYWORDS_TABLE = "brand_keywords"


def get_brand_keyword_by_id(db: Client, kw_id: int) -> dict[str, Any] | None:
    """Get a brand keyword by ID."""
    result = db.table(BRAND_KEYWORDS_TABLE).select("*").eq("id", kw_id).execute()
    return result.data[0] if result.data else None


def list_brand_keywords_for_company(db: Client, company_id: int, enabled_only: bool = False) -> list[dict[str, Any]]:
    """List brand keywords for a company."""
    query = db.table(BRAND_KEYWORDS_TABLE).select("*").eq("company_id", company_id)
    if enabled_only:
        query = query.eq("is_enabled", True)
    result = query.order("created_at", desc=True).execute()
    return list(result.data)


def create_brand_keyword(db: Client, data: dict[str, Any]) -> dict[str, Any]:
    """Create a new brand keyword."""
    result = db.table(BRAND_KEYWORDS_TABLE).insert(data).execute()
    return result.data[0]


def update_brand_keyword(db: Client, kw_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a brand keyword."""
    result = db.table(BRAND_KEYWORDS_TABLE).update(data).eq("id", kw_id).execute()
    return result.data[0] if result.data else None


def delete_brand_keyword(db: Client, kw_id: int) -> None:
    """Delete a brand keyword."""
    db.table(BRAND_KEYWORDS_TABLE).delete().eq("id", kw_id).execute()


def increment_matched(db: Client, kw_id: int) -> dict[str, Any] | None:
    """Increment the times_matched counter for a brand keyword."""
    record = get_brand_keyword_by_id(db, kw_id)
    if not record:
        return None
    result = (
        db.table(BRAND_KEYWORDS_TABLE)
        .update({"times_matched": record["times_matched"] + 1})
        .eq("id", kw_id)
        .execute()
    )
    return result.data[0] if result.data else None


def increment_approved(db: Client, kw_id: int) -> dict[str, Any] | None:
    """Increment the times_approved counter for a brand keyword."""
    record = get_brand_keyword_by_id(db, kw_id)
    if not record:
        return None
    result = (
        db.table(BRAND_KEYWORDS_TABLE)
        .update({"times_approved": record["times_approved"] + 1})
        .eq("id", kw_id)
        .execute()
    )
    return result.data[0] if result.data else None


def increment_rejected(db: Client, kw_id: int) -> dict[str, Any] | None:
    """Increment the times_rejected counter for a brand keyword."""
    record = get_brand_keyword_by_id(db, kw_id)
    if not record:
        return None
    result = (
        db.table(BRAND_KEYWORDS_TABLE)
        .update({"times_rejected": record["times_rejected"] + 1})
        .eq("id", kw_id)
        .execute()
    )
    return result.data[0] if result.data else None


def disable_brand_keyword(db: Client, kw_id: int) -> dict[str, Any] | None:
    """Disable a brand keyword."""
    result = db.table(BRAND_KEYWORDS_TABLE).update({"is_enabled": False}).eq("id", kw_id).execute()
    return result.data[0] if result.data else None


def enable_brand_keyword(db: Client, kw_id: int) -> dict[str, Any] | None:
    """Enable a brand keyword."""
    result = db.table(BRAND_KEYWORDS_TABLE).update({"is_enabled": True}).eq("id", kw_id).execute()
    return result.data[0] if result.data else None
