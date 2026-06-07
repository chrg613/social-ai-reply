"""Feedback management endpoints."""
import logging

from fastapi import APIRouter, Depends, Query, status
from supabase import Client

from app.api.v1.deps import (
    ensure_workspace_membership,
    get_current_user,
    get_current_workspace,
)
from app.db.supabase_client import get_supabase
from app.db.tables.feedback import (
    create_feedback,
    get_feedback_stats_for_company,
    list_feedback_for_company,
)
from app.schemas.v1.feedback import FeedbackCreateRequest, FeedbackResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["feedback"])


@router.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def submit_feedback(
    payload: FeedbackCreateRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> FeedbackResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    data = payload.model_dump()
    feedback = create_feedback(supabase, data)
    return FeedbackResponse.model_validate(feedback)


@router.get("/feedback", response_model=list[FeedbackResponse])
def list_feedback(
    company_id: int | None = Query(default=None, ge=1),
    opportunity_id: int | None = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[FeedbackResponse]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    rows = list_feedback_for_company(
        supabase,
        company_id=company_id,
        opportunity_id=opportunity_id,
    )
    return [FeedbackResponse.model_validate(row) for row in rows]


@router.get("/feedback/stats")
def get_feedback_stats(
    company_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    stats = get_feedback_stats_for_company(supabase, company_id)
    return stats
