"""Auto-pipeline run and management endpoints."""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, status
from supabase import Client

from app.api.v1.deps import (
    ensure_workspace_membership,
    get_active_project,
    get_current_user,
    get_current_workspace,
)
from app.db.supabase_client import get_supabase
from app.db.tables.analytics import create_auto_pipeline, get_auto_pipeline_by_id, list_auto_pipelines_for_project
from app.db.tables.content import list_reply_drafts_for_project
from app.db.tables.discovery import (
    list_discovery_keywords_for_project,
    list_monitored_subreddits_for_project,
    list_opportunities_for_project,
    list_personas_for_project,
)
from app.db.tables.projects import get_project_by_id
from app.services.infrastructure.llm.service import LLMService
from app.services.product.entitlements import FEATURE_AUTO_PIPELINE, has_feature
from app.services.product.pipeline import run_auto_pipeline_background

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["auto-pipeline"])
RESULT_STATUSES = {"ready", "executed"}


def _slice_run_results(items: list[dict], limit: int) -> list[dict]:
    """Trim results to the count persisted for the specific pipeline run.

    Older project rows can contain accumulated personas/opportunities/drafts
    from multiple runs. A zero persisted count means we have no items to show
    for this run snapshot, so we intentionally return an empty list instead of
    leaking prior project data into the run results view.
    """
    return items[:limit] if limit > 0 else []


def _ensure_llm_ready() -> None:
    try:
        LLMService()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post("/auto-pipeline/run")
def start_auto_pipeline(
    background_tasks: BackgroundTasks,
    payload: dict = Body(...),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    """Start the full auto-pipeline from website URL."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    if not has_feature(supabase, workspace, FEATURE_AUTO_PIPELINE):
        raise HTTPException(403, "Auto-pipeline is not available on your current plan")

    website_url = payload.get("website_url")
    project_id = payload.get("project_id")
    time_filter = payload.get("time_filter", "week")
    if time_filter not in {"day", "week", "month", "year", "all"}:
        time_filter = "week"

    if not website_url:
        raise HTTPException(400, "website_url is required.")

    _ensure_llm_ready()

    proj = get_active_project(supabase, workspace["id"], project_id)
    if not proj:
        raise HTTPException(404, "No active project found. Please create a project first.")

    pipeline = create_auto_pipeline(
        supabase,
        {
            "project_id": proj["id"],
            "website_url": website_url,
            "status": "analyzing",
            "progress": 0,
            "current_step": "Analyzing website...",
            "started_at": datetime.now(UTC).isoformat(),
        },
    )

    background_tasks.add_task(
        run_auto_pipeline_background,
        pipeline["id"],
        website_url,
        proj["id"],
        workspace["id"],
        current_user["id"],
        time_filter,
    )

    return {
        "id": pipeline["id"],
        "project_id": pipeline["project_id"],
        "website_url": pipeline["website_url"],
        "status": pipeline["status"],
        "progress": pipeline["progress"],
        "current_step": pipeline.get("current_step"),
        "personas_count": pipeline.get("personas_generated", 0),
        "keywords_count": pipeline.get("keywords_generated", 0),
        "subreddits_count": pipeline.get("subreddits_found", 0),
        "opportunities_count": pipeline.get("opportunities_found", 0),
        "drafts_count": pipeline.get("drafts_generated", 0),
        "brand_summary": pipeline.get("brand_summary"),
        "created_at": pipeline.get("created_at"),
    }


@router.get("/auto-pipeline/{pipeline_id}")
def get_auto_pipeline(
    pipeline_id: str,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    """Get pipeline status and results."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    # Get all project IDs for this workspace
    from app.db.tables.projects import list_projects_for_workspace
    projects = list_projects_for_workspace(supabase, workspace["id"])
    project_ids = [p["id"] for p in projects]

    # Fetch pipeline once and verify it belongs to workspace
    pipeline = get_auto_pipeline_by_id(supabase, pipeline_id)
    if not pipeline or pipeline["project_id"] not in project_ids:
        raise HTTPException(404, "Pipeline not found.")

    response = {
        "id": pipeline["id"],
        "project_id": pipeline["project_id"],
        "website_url": pipeline["website_url"],
        "status": pipeline["status"],
        "progress": pipeline["progress"],
        "current_step": pipeline.get("current_step"),
        "brand_summary": pipeline.get("brand_summary"),
        "personas_count": pipeline.get("personas_generated", 0),
        "keywords_count": pipeline.get("keywords_generated", 0),
        "subreddits_count": pipeline.get("subreddits_found", 0),
        "opportunities_count": pipeline.get("opportunities_found", 0),
        "drafts_count": pipeline.get("drafts_generated", 0),
        "started_at": pipeline.get("started_at"),
        "completed_at": pipeline.get("completed_at"),
        "error_message": pipeline.get("error_message"),
    }

    if pipeline["status"] in RESULT_STATUSES:
        proj = get_project_by_id(supabase, pipeline["project_id"])
        if proj:
            # N+1 FIX: Batch load all related data instead of querying per-entity
            personas = list_personas_for_project(supabase, proj["id"], source="generated")
            keywords = list_discovery_keywords_for_project(supabase, proj["id"], source="generated")
            subreddits = list_monitored_subreddits_for_project(supabase, proj["id"])
            all_opportunities = list_opportunities_for_project(supabase, proj["id"], limit=100)
            visible_opportunities = [o for o in all_opportunities if o.get("status") in {"new", "drafting"}]
            drafts = list_reply_drafts_for_project(supabase, proj["id"])
            opportunity_titles = {o["id"]: o["title"] for o in all_opportunities}
            # Show actual project data rather than slicing to stale persisted
            # counts.  The persisted numbers (opportunities_found, drafts_generated)
            # may be zero if e.g. the LLM was rate-limited during draft generation,
            # but drafts may have been created manually/later.  Limiting to those
            # stale counts caused the UI to show "0 drafts" even when drafts exist.

            response["results"] = {
                "brand_summary": pipeline["brand_summary"] or "",
                "personas": [
                    {"name": p["name"], "role": p.get("role", ""), "summary": p["summary"], "pain_points": p.get("pain_points", [])}
                    for p in personas
                ],
                "keywords": [
                    {"keyword": k["keyword"], "score": k.get("priority_score", 0), "source": k.get("source", "")}
                    for k in keywords
                ],
                "subreddits": [
                    {"name": s["name"], "fit_score": s.get("fit_score", 0), "subscribers": s.get("subscribers", 0), "description": s.get("description", "")}
                    for s in subreddits
                ],
                "opportunities": [
                    {"title": o["title"], "subreddit": o["subreddit_name"], "platform": o.get("platform", "reddit"), "score": o.get("score", 0), "author": o.get("author", "")}
                    for o in visible_opportunities
                ],
                "drafts": [
                    {
                        "title": opportunity_titles.get(d["opportunity_id"], "Reply Draft"),
                        "opportunity_title": opportunity_titles.get(d["opportunity_id"], "Reply Draft"),
                        "content": d["content"],
                    }
                    for d in drafts
                ],
            }

    return response


@router.get("/auto-pipeline")
def list_auto_pipelines(
    project_id: int | None = Query(default=None, ge=1),
    limit: int = 20,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    """List all pipeline runs."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    proj = get_active_project(supabase, workspace["id"], project_id)
    if not proj:
        raise HTTPException(404, "No active project found. Please create a project first.")

    pipelines = list_auto_pipelines_for_project(supabase, proj["id"], limit=limit, offset=offset)

    return {
        "items": [
            {
                "id": p["id"],
                "project_id": p["project_id"],
                "website_url": p["website_url"],
                "status": p["status"],
                "progress": p["progress"],
                "current_step": p.get("current_step"),
                "personas_count": p.get("personas_generated", 0),
                "keywords_count": p.get("keywords_generated", 0),
                "subreddits_count": p.get("subreddits_found", 0),
                "opportunities_count": p.get("opportunities_found", 0),
                "drafts_count": p.get("drafts_generated", 0),
                "error_message": p.get("error_message"),
                "created_at": p.get("created_at"),
                "completed_at": p.get("completed_at"),
            }
            for p in pipelines
        ]
    }


@router.post("/auto-pipeline/{pipeline_id}/execute")
def execute_auto_pipeline(
    pipeline_id: str,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    """Execute the sales package (publish all drafts)."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    # Get all project IDs for this workspace
    from app.db.tables.projects import list_projects_for_workspace
    projects = list_projects_for_workspace(supabase, workspace["id"])
    project_ids = [p["id"] for p in projects]

    # Fetch pipeline once and verify it belongs to workspace
    pipeline = get_auto_pipeline_by_id(supabase, pipeline_id)
    if not pipeline or pipeline["project_id"] not in project_ids:
        raise HTTPException(404, "Pipeline not found.")

    if pipeline["status"] != "ready":
        raise HTTPException(400, "Pipeline is not ready for execution. Please complete the setup first.")

    reply_drafts = list_reply_drafts_for_project(supabase, pipeline["project_id"])

    # Update pipeline status
    from app.db.tables.analytics import update_auto_pipeline
    update_auto_pipeline(
        supabase,
        pipeline["id"],
        {
            "status": "executed",
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )

    return {
        "id": pipeline["id"],
        "status": "executed",
        "drafted_replies": len(reply_drafts),
        "message": "Drafts marked as ready. Copy each draft and post to Reddit manually — auto-posting is coming soon.",
    }
