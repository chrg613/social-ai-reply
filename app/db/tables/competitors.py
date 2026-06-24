"""Database helpers for the competitor_mentions table."""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client


def create_competitor_mention(db: Client, data: dict[str, Any]) -> dict[str, Any]:
    """Insert a single competitor mention and return the created record."""
    result = db.table("competitor_mentions").insert(data).execute()
    return result.data[0]


def list_competitor_mentions(
    db: Client,
    project_id: int,
    *,
    competitor_name: str | None = None,
    sentiment: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List competitor mentions for a project with optional filters."""
    query = db.table("competitor_mentions").select("*").eq("project_id", project_id)
    if competitor_name:
        query = query.eq("competitor_name", competitor_name)
    if sentiment:
        query = query.eq("sentiment", sentiment)
    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
    result = query.execute()
    return list(result.data)


def get_competitor_mention_by_opportunity(db: Client, opportunity_id: int) -> dict[str, Any] | None:
    """Get a competitor mention linked to a specific opportunity."""
    result = db.table("competitor_mentions").select("*").eq("opportunity_id", opportunity_id).execute()
    return result.data[0] if result.data else None


def get_competitor_stats(db: Client, project_id: int) -> list[dict[str, Any]]:
    """Return aggregated stats per competitor.

    Supabase doesn't support GROUP BY, so we fetch all mentions and aggregate in Python.
    """
    result = db.table("competitor_mentions").select("*").eq("project_id", project_id).execute()
    mentions = result.data

    if not mentions:
        return []

    # Group by competitor_name
    grouped: dict[str, list[dict[str, Any]]] = {}
    for m in mentions:
        name = m.get("competitor_name", "")
        grouped.setdefault(name, []).append(m)

    stats: list[dict[str, Any]] = []
    for name, items in grouped.items():
        sentiment_counts = Counter(item.get("sentiment", "neutral") for item in items)
        complaint_counts = Counter(
            item["complaint_category"] for item in items if item.get("complaint_category")
        )
        top_complaints = [cat for cat, _ in complaint_counts.most_common(5)]
        scores = [item.get("sentiment_score", 0.0) for item in items]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        stats.append({
            "competitor_name": name,
            "total_mentions": len(items),
            "negative_count": sentiment_counts.get("negative", 0),
            "neutral_count": sentiment_counts.get("neutral", 0),
            "positive_count": sentiment_counts.get("positive", 0),
            "top_complaints": top_complaints,
            "avg_sentiment_score": round(avg_score, 3),
        })

    # Sort by total mentions descending
    stats.sort(key=lambda s: s["total_mentions"], reverse=True)
    return stats


def count_competitor_mentions(db: Client, project_id: int) -> int:
    """Return the total number of competitor mentions for a project."""
    result = db.table("competitor_mentions").select("id", count="exact").eq("project_id", project_id).execute()
    return result.count if result.count else 0
