"""Competitor intelligence routes."""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query

if TYPE_CHECKING:
    from supabase import Client

from app.api.v1.deps import get_current_user, get_current_workspace
from app.db.supabase_client import get_supabase
from app.db.tables.competitors import (
    get_competitor_stats,
    list_competitor_mentions,
)
from app.schemas.v1.competitors import (
    CompetitorMentionResponse,
    CompetitorStatsResponse,
)
from app.services.product.competitor_intel import get_project_competitors

router = APIRouter(prefix="/v1/competitors", tags=["competitors"])


def _resolve_project_id(
    supabase: Client,
    workspace: dict,
    project_id: int | None,
) -> int | None:
    """Return project_id from query param or first project in workspace."""
    if project_id:
        return project_id
    projects = supabase.table("projects").select("id").eq("workspace_id", workspace["id"]).execute()
    return projects.data[0]["id"] if projects.data else None


@router.get("/mentions")
def list_mentions(
    project_id: int | None = Query(default=None),
    competitor_name: str | None = None,
    sentiment: str | None = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[CompetitorMentionResponse]:
    """List competitor mentions for a project."""
    pid = _resolve_project_id(supabase, workspace, project_id)
    if not pid:
        return []
    mentions = list_competitor_mentions(
        supabase,
        pid,
        competitor_name=competitor_name,
        sentiment=sentiment,
        limit=limit,
        offset=offset,
    )
    return [CompetitorMentionResponse.model_validate(m) for m in mentions]


@router.get("/stats")
def get_stats(
    project_id: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[CompetitorStatsResponse]:
    """Return aggregated competitor stats for a project."""
    pid = _resolve_project_id(supabase, workspace, project_id)
    if not pid:
        return []
    stats = get_competitor_stats(supabase, pid)
    return [CompetitorStatsResponse.model_validate(s) for s in stats]


@router.get("/list")
def list_competitors(
    project_id: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[str]:
    """Return the competitor names from the company profile."""
    pid = _resolve_project_id(supabase, workspace, project_id)
    if not pid:
        return []
    return get_project_competitors(supabase, pid)
