"""Central Opportunity Feed API endpoints."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from supabase import Client

from app.api.v1.deps import (
    ensure_workspace_membership,
    get_current_user,
    get_current_workspace,
)
from app.db.supabase_client import get_supabase
from app.db.tables.company import get_company_by_id
from app.schemas.v1.discovery import OpportunityResponse
from app.services.agents.central_feed import CentralFeedService, FeedFilters, FeedSort

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["feed"])
feed_service = CentralFeedService()


class FeedResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    opportunities: list[OpportunityResponse]
    total: int
    filters_applied: dict[str, Any]
    debug_info: dict[str, Any] | None = None


class OpportunityDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    opportunity: dict[str, Any] | None
    drafts: list[dict[str, Any]]
    feedback_history: list[dict[str, Any]]
    scoring_breakdown: dict[str, Any]


def _ensure_company_in_workspace(supabase: Client, company_id: int, workspace_id: int) -> None:
    """Validate that a company belongs to the current workspace."""
    company = get_company_by_id(supabase, company_id)
    if not company or company.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=404, detail="Company not found.")


@router.get("/feed", response_model=FeedResultResponse)
def get_feed(
    company_id: int = Query(..., ge=1),
    platform: str | None = Query(default=None),
    status: str | None = Query(default=None),
    min_score: int | None = Query(default=None, ge=0, le=100),
    intent: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    agent_name: str | None = Query(default=None),
    sort: str = Query(default="relevance"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    debug: bool = Query(default=False),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> FeedResultResponse:
    """Return the central opportunity feed for a company."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    _ensure_company_in_workspace(supabase, company_id, workspace["id"])

    try:
        feed_sort = FeedSort(sort)
    except ValueError:
        feed_sort = FeedSort.RELEVANCE

    filters = FeedFilters(
        platform=platform,
        status=status,
        min_score=min_score,
        intent=intent,
        keyword=keyword,
        agent_name=agent_name,
    )

    result = feed_service.get_feed(
        db=supabase,
        company_id=company_id,
        filters=filters,
        sort=feed_sort,
        limit=limit,
        offset=offset,
        debug=debug,
    )

    return FeedResultResponse(
        opportunities=result.opportunities,
        total=result.total,
        filters_applied={
            k: v.isoformat() if isinstance(v, datetime) else v
            for k, v in vars(result.filters_applied).items()
        },
        debug_info=result.debug_info,
    )


@router.get("/feed/{opportunity_id}", response_model=OpportunityDetailResponse)
def get_opportunity_detail(
    opportunity_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> OpportunityDetailResponse:
    """Return detailed information for a single opportunity."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    detail = feed_service.get_opportunity_detail(supabase, opportunity_id)
    if not detail.get("opportunity"):
        raise HTTPException(status_code=404, detail="Opportunity not found.")

    # Validate workspace access via the opportunity's project
    from app.db.tables.projects import get_project_by_id

    project_id = detail["opportunity"].get("project_id")
    if project_id:
        proj = get_project_by_id(supabase, project_id)
        if not proj or proj.get("workspace_id") != workspace["id"]:
            raise HTTPException(status_code=404, detail="Opportunity not found.")

    return OpportunityDetailResponse(
        opportunity=detail["opportunity"],
        drafts=detail["drafts"],
        feedback_history=detail["feedback_history"],
        scoring_breakdown=detail["scoring_breakdown"],
    )


@router.get("/feed/debug", response_model=dict[str, Any])
def get_feed_debug(
    company_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    """Return debug statistics for a company's feed."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    _ensure_company_in_workspace(supabase, company_id, workspace["id"])

    return feed_service.get_debug_info(supabase, company_id)
