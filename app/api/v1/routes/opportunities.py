"""Opportunity listing and status management endpoints."""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from app.api.v1.deps import ensure_workspace_membership, get_active_project, get_current_user, get_current_workspace
from app.db.supabase_client import get_supabase
from app.db.tables.discovery import (
    create_score_feedback,
    get_opportunity_by_id,
    list_opportunities_for_project,
    update_opportunity,
)
from app.db.tables.feedback import create_feedback
from app.db.tables.projects import get_project_by_id
from app.schemas.v1.discovery import OpportunityResponse, OpportunityStatusRequest

logger = logging.getLogger(__name__)

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "new": {"saved", "drafting", "ignored", "rejected"},
    "saved": {"drafting", "ignored", "rejected"},
    "drafting": {"posted", "saved", "ignored"},
    "posted": set(),
    "ignored": {"new"},
    # "rejected" was filtered by the scoring pipeline — the user can
    # always manually promote it back to "new" for review.
    "rejected": {"new", "ignored"},
}

router = APIRouter(prefix="/v1", tags=["opportunities"])


@router.get("/opportunities", response_model=list[OpportunityResponse])
def list_opportunities(
    status_filter: str = Query(default="new", alias="status"),
    project_id: int | None = Query(default=None, ge=1),
    platform: str | None = Query(default=None),
    agent_name: str | None = Query(default=None),
    intent: str | None = Query(default=None),
    min_score: int | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[OpportunityResponse]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    proj = get_active_project(supabase, workspace["id"], project_id)
    if not proj:
        return []

    status_param = None if status_filter == "all" else status_filter
    rows = list_opportunities_for_project(
        supabase,
        proj["id"],
        status=status_param,
        platform=platform,
        agent_name=agent_name,
        intent=intent,
        min_score=min_score,
        limit=limit,
        offset=offset,
    )
    return [OpportunityResponse.model_validate(row) for row in rows]


@router.put("/opportunities/{opportunity_id}/status", response_model=OpportunityResponse)
def update_opportunity_status(
    opportunity_id: int,
    payload: OpportunityStatusRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> OpportunityResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    opportunity = get_opportunity_by_id(supabase, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found.")

    # Verify workspace access via project - check the opportunity's actual project
    proj = get_project_by_id(supabase, opportunity["project_id"])
    if not proj or proj["workspace_id"] != workspace["id"]:
        raise HTTPException(status_code=404, detail="Opportunity not found.")

    current = opportunity.get("status", "new")
    target = payload.status

    if target not in _VALID_TRANSITIONS.get(current, set()):
        raise HTTPException(status_code=422, detail=f"Cannot transition from '{current}' to '{target}'.")

    update_data = {"status": target}
    if target == "posted":
        update_data["posted_at"] = datetime.now(UTC).isoformat()

    updated = update_opportunity(supabase, opportunity_id, update_data)

    try:
        feedback_action = target
        if target == "drafting":
            feedback_action = "saved"
        elif target == "posted":
            feedback_action = "replied"
        create_score_feedback(supabase, {
            "opportunity_id": opportunity_id,
            "workspace_id": workspace["id"],
            "action": feedback_action,
            "original_score": opportunity.get("score", 0),
        })
    except Exception as exc:
        logger.warning("Failed to record score feedback (non-fatal): %s", exc)

    return OpportunityResponse.model_validate(updated)


@router.post("/opportunities/{opportunity_id}/approve", response_model=OpportunityResponse)
def approve_opportunity(
    opportunity_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> OpportunityResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    opportunity = get_opportunity_by_id(supabase, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found.")
    proj = get_project_by_id(supabase, opportunity["project_id"])
    if not proj or proj["workspace_id"] != workspace["id"]:
        raise HTTPException(status_code=404, detail="Opportunity not found.")
    updated = update_opportunity(supabase, opportunity_id, {"status": "approved"})
    return OpportunityResponse.model_validate(updated)


@router.post("/opportunities/{opportunity_id}/reject", response_model=OpportunityResponse)
def reject_opportunity(
    opportunity_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> OpportunityResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    opportunity = get_opportunity_by_id(supabase, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found.")
    proj = get_project_by_id(supabase, opportunity["project_id"])
    if not proj or proj["workspace_id"] != workspace["id"]:
        raise HTTPException(status_code=404, detail="Opportunity not found.")
    updated = update_opportunity(supabase, opportunity_id, {"status": "rejected"})
    return OpportunityResponse.model_validate(updated)


@router.post("/opportunities/{opportunity_id}/copy", response_model=OpportunityResponse)
def copy_opportunity(
    opportunity_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> OpportunityResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    opportunity = get_opportunity_by_id(supabase, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found.")
    proj = get_project_by_id(supabase, opportunity["project_id"])
    if not proj or proj["workspace_id"] != workspace["id"]:
        raise HTTPException(status_code=404, detail="Opportunity not found.")
    updated = update_opportunity(supabase, opportunity_id, {"status": "copied"})
    return OpportunityResponse.model_validate(updated)


@router.post("/opportunities/{opportunity_id}/mark-irrelevant")
def mark_irrelevant(
    opportunity_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    opportunity = get_opportunity_by_id(supabase, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found.")
    proj = get_project_by_id(supabase, opportunity["project_id"])
    if not proj or proj["workspace_id"] != workspace["id"]:
        raise HTTPException(status_code=404, detail="Opportunity not found.")
    update_opportunity(supabase, opportunity_id, {"status": "ignored"})
    create_feedback(
        supabase,
        {
            "opportunity_id": opportunity_id,
            "project_id": proj["id"],
            "label": "irrelevant",
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    return {"ok": True}
