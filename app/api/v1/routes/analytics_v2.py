"""Enhanced analytics v2 endpoints — multi-agent stats, trends, and performance."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query

if TYPE_CHECKING:
    from supabase import Client

from app.api.v1.deps import (
    ensure_workspace_membership,
    get_current_user,
    get_current_workspace,
)
from app.db.supabase_client import get_supabase
from app.db.tables.company import get_company_by_id
from app.db.tables.projects import list_projects_for_workspace
from app.services.product.feedback_loop import FeedbackLoop

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/analytics/v2", tags=["analytics-v2"])


def _get_project_ids_for_company(db: Client, company_id: int) -> list[int]:
    """Resolve company_id -> workspace_id -> project_ids."""
    company = get_company_by_id(db, company_id)
    if not company:
        return []
    workspace_id = company.get("workspace_id")
    if not workspace_id:
        return []
    projects = list_projects_for_workspace(db, workspace_id)
    return [p["id"] for p in projects]


@router.get("/overview")
def analytics_v2_overview(
    company_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    """Enhanced overview with multi-agent stats and keyword performance."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    project_ids = _get_project_ids_for_company(supabase, company_id)
    if not project_ids:
        raise HTTPException(status_code=404, detail="No projects found for company.")

    # Fetch opportunities for these projects
    if len(project_ids) == 1:
        opp_query = supabase.table("opportunities").select("*").eq("project_id", project_ids[0])
    else:
        opp_query = supabase.table("opportunities").select("*").in_("project_id", project_ids)
    all_opps = opp_query.execute().data

    # Agent breakdown
    opportunities_found_by_agent: dict[str, int] = {}
    approval_rate_by_agent: dict[str, dict[str, int]] = {}
    relevance_scores_by_agent: dict[str, list[float]] = {}
    platform_breakdown: dict[str, dict[str, int]] = {}

    for opp in all_opps:
        agent = opp.get("agent_name") or opp.get("platform", "unknown")
        platform = opp.get("platform", "unknown")
        status = opp.get("status", "new")
        score = opp.get("score")

        opportunities_found_by_agent[agent] = opportunities_found_by_agent.get(agent, 0) + 1

        if agent not in approval_rate_by_agent:
            approval_rate_by_agent[agent] = {"approved": 0, "rejected": 0, "total": 0}
        approval_rate_by_agent[agent]["total"] += 1
        if status in ("approved", "copied", "posted"):
            approval_rate_by_agent[agent]["approved"] += 1
        elif status in ("rejected", "ignored"):
            approval_rate_by_agent[agent]["rejected"] += 1

        if score is not None:
            relevance_scores_by_agent.setdefault(agent, []).append(float(score))

        if platform not in platform_breakdown:
            platform_breakdown[platform] = {"total": 0, "kept": 0, "rejected": 0}
        platform_breakdown[platform]["total"] += 1
        if status in ("approved", "copied", "posted"):
            platform_breakdown[platform]["kept"] += 1
        elif status in ("rejected", "ignored"):
            platform_breakdown[platform]["rejected"] += 1

    average_relevance_by_agent: dict[str, float] = {}
    for agent, scores in relevance_scores_by_agent.items():
        average_relevance_by_agent[agent] = round(sum(scores) / len(scores), 2) if scores else 0.0

    # Top performing keywords (brand_keywords)
    kw_result = (
        supabase.table("brand_keywords")
        .select("*")
        .eq("company_id", company_id)
        .eq("is_enabled", True)
        .execute()
    )
    brand_keywords = kw_result.data
    top_performing_keywords = sorted(
        brand_keywords,
        key=lambda k: int(k.get("times_approved", 0)),
        reverse=True,
    )[:10]

    # Noisy keywords
    noisy_keywords = FeedbackLoop.get_noisy_keywords(company_id, supabase)

    return {
        "company_id": company_id,
        "project_ids": project_ids,
        "opportunities_found_by_agent": opportunities_found_by_agent,
        "approval_rate_by_agent": {
            agent: {
                "approved": stats["approved"],
                "rejected": stats["rejected"],
                "total": stats["total"],
                "rate": round(stats["approved"] / stats["total"], 3) if stats["total"] else 0.0,
            }
            for agent, stats in approval_rate_by_agent.items()
        },
        "average_relevance_by_agent": average_relevance_by_agent,
        "top_performing_keywords": [
            {
                "id": k["id"],
                "keyword": k["keyword"],
                "times_approved": k.get("times_approved", 0),
                "times_rejected": k.get("times_rejected", 0),
                "weight": k.get("weight", 1.0),
            }
            for k in top_performing_keywords
        ],
        "noisy_keywords": noisy_keywords,
        "platform_breakdown": platform_breakdown,
    }


@router.get("/trends")
def analytics_v2_trends(
    company_id: int = Query(..., ge=1),
    days: int = Query(default=30, ge=1, le=90),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    """Time-series data for opportunities, approval rate, and relevance over time."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    project_ids = _get_project_ids_for_company(supabase, company_id)
    if not project_ids:
        raise HTTPException(status_code=404, detail="No projects found for company.")

    since = datetime.now(UTC) - timedelta(days=days)
    if len(project_ids) == 1:
        opp_query = (
            supabase.table("opportunities")
            .select("*")
            .eq("project_id", project_ids[0])
            .gte("created_at", since.isoformat())
        )
    else:
        opp_query = (
            supabase.table("opportunities")
            .select("*")
            .in_("project_id", project_ids)
            .gte("created_at", since.isoformat())
        )
    all_opps = opp_query.execute().data

    # Build daily buckets
    buckets: dict[str, dict[str, Any]] = {}
    for opp in all_opps:
        created = opp.get("created_at", "")
        if not created:
            continue
        day = created[:10] if isinstance(created, str) else created.isoformat()[:10]
        if day not in buckets:
            buckets[day] = {
                "opportunities": 0,
                "approved": 0,
                "rejected": 0,
                "relevance_scores": [],
            }
        buckets[day]["opportunities"] += 1
        status = opp.get("status", "new")
        if status in ("approved", "copied", "posted"):
            buckets[day]["approved"] += 1
        elif status in ("rejected", "ignored"):
            buckets[day]["rejected"] += 1
        score = opp.get("score")
        if score is not None:
            buckets[day]["relevance_scores"].append(float(score))

    items = []
    for day in sorted(buckets.keys()):
        stats = buckets[day]
        total_actions = stats["approved"] + stats["rejected"]
        items.append(
            {
                "date": day,
                "opportunities": stats["opportunities"],
                "approval_rate": round(stats["approved"] / total_actions, 3) if total_actions else 0.0,
                "rejection_rate": round(stats["rejected"] / total_actions, 3) if total_actions else 0.0,
                "average_relevance": round(sum(stats["relevance_scores"]) / len(stats["relevance_scores"]), 2)
                if stats["relevance_scores"]
                else 0.0,
            }
        )

    return {
        "company_id": company_id,
        "days": days,
        "items": items,
    }


@router.get("/keywords")
def analytics_v2_keywords(
    company_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    """Keyword performance with approval/rejection rates and weights."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    result = (
        supabase.table("brand_keywords")
        .select("*")
        .eq("company_id", company_id)
        .execute()
    )
    keywords = result.data

    items = []
    for kw in keywords:
        matched = int(kw.get("times_matched", 0))
        approved = int(kw.get("times_approved", 0))
        rejected = int(kw.get("times_rejected", 0))
        total = approved + rejected + 1
        items.append(
            {
                "id": kw["id"],
                "keyword": kw["keyword"],
                "times_matched": matched,
                "approval_rate": round(approved / total, 3),
                "rejection_rate": round(rejected / total, 3),
                "weight": kw.get("weight", 1.0),
                "is_enabled": kw.get("is_enabled", True),
            }
        )

    return {
        "company_id": company_id,
        "items": items,
    }


@router.get("/sources")
def analytics_v2_sources(
    company_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    """Source/platform performance aggregated from opportunities."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    project_ids = _get_project_ids_for_company(supabase, company_id)
    if not project_ids:
        raise HTTPException(status_code=404, detail="No projects found for company.")

    if len(project_ids) == 1:
        opp_query = supabase.table("opportunities").select("*").eq("project_id", project_ids[0])
    else:
        opp_query = supabase.table("opportunities").select("*").in_("project_id", project_ids)
    all_opps = opp_query.execute().data

    # Also fetch active sources for status
    sources_result = (
        supabase.table("sources")
        .select("*")
        .eq("company_id", company_id)
        .execute()
    )
    source_status: dict[str, str] = {}
    for s in sources_result.data:
        platform = s.get("platform", "unknown")
        source_status[platform] = s.get("status", "unknown")

    platform_stats: dict[str, dict[str, Any]] = {}
    for opp in all_opps:
        platform = opp.get("platform", "unknown")
        status = opp.get("status", "new")
        score = opp.get("score")

        if platform not in platform_stats:
            platform_stats[platform] = {
                "total_fetched": 0,
                "total_kept": 0,
                "total_rejected": 0,
                "relevance_scores": [],
            }
        platform_stats[platform]["total_fetched"] += 1
        if status in ("approved", "copied", "posted"):
            platform_stats[platform]["total_kept"] += 1
        elif status in ("rejected", "ignored"):
            platform_stats[platform]["total_rejected"] += 1
        if score is not None:
            platform_stats[platform]["relevance_scores"].append(float(score))

    items = []
    for platform, stats in platform_stats.items():
        scores = stats["relevance_scores"]
        items.append(
            {
                "platform": platform,
                "total_fetched": stats["total_fetched"],
                "total_kept": stats["total_kept"],
                "total_rejected": stats["total_rejected"],
                "avg_relevance": round(sum(scores) / len(scores), 2) if scores else 0.0,
                "status": source_status.get(platform, "unknown"),
            }
        )

    return {
        "company_id": company_id,
        "items": items,
    }
