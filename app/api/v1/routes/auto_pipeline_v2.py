"""Auto Pipeline v2 — one-click run for the multi-agent platform.

Paste a website URL and the system automatically:
1. Creates a company profile
2. Analyzes the website (Brand Brain)
3. Generates keywords
4. Runs all 9 agents
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from supabase import Client

from app.api.v1.deps import ensure_workspace_membership, get_current_user, get_current_workspace
from app.db.supabase_client import get_supabase, get_supabase_client
from app.db.tables.company import create_company, get_company_by_id
from app.services.infrastructure.scheduler.service import SchedulerService
from app.services.product.brand_brain import BrandBrain
from app.services.product.keyword_expansion import KeywordExpansionService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["auto-pipeline"])


class AutoPipelineV2Request(BaseModel):
    website_url: str = Field(min_length=5, max_length=2000)
    name: str = Field(min_length=1, max_length=255, default="")
    project_id: int | None = Field(default=None)


class AutoPipelineV2Response(BaseModel):
    company_id: int
    status: str
    message: str


def _run_full_pipeline_background(company_id: int) -> None:
    """Background task: analyze website, generate keywords, run all agents."""
    try:
        supabase = get_supabase_client()
        company = get_company_by_id(supabase, company_id)
        if not company:
            logger.warning("Company %s not found for auto-pipeline.", company_id)
            return

        website_url = company.get("website_url")
        if website_url:
            logger.info("[Auto Pipeline v2] Starting Brand Brain analysis for company %s", company_id)
            brain = BrandBrain()
            brain.analyze_website(website_url, company, supabase)
            logger.info("[Auto Pipeline v2] Brand Brain analysis completed for company %s", company_id)

        logger.info("[Auto Pipeline v2] Starting keyword expansion for company %s", company_id)
        service = KeywordExpansionService()
        keywords = service.expand(company)
        if keywords:
            service.store_keywords(supabase, company_id, keywords)
        logger.info("[Auto Pipeline v2] Keyword expansion completed (%s keywords)", len(keywords))

        logger.info("[Auto Pipeline v2] Starting all agents for company %s", company_id)
        scheduler = SchedulerService()
        scheduler.run_all(company_id, supabase)
        logger.info("[Auto Pipeline v2] All agents triggered for company %s", company_id)

    except Exception:
        logger.exception("[Auto Pipeline v2] Failed for company %s", company_id)


@router.post("/auto-pipeline/v2/run", response_model=AutoPipelineV2Response, status_code=status.HTTP_202_ACCEPTED)
def start_auto_pipeline_v2(
    payload: AutoPipelineV2Request,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> AutoPipelineV2Response:
    """Start the full multi-agent pipeline from just a website URL."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    # Derive company name from URL if not provided
    name = payload.name or payload.website_url.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0].split(".")[0]
    name = name.replace("-", " ").replace("_", " ").title() or "My Company"

    company_id = None
    if payload.project_id:
        from app.db.tables.projects import get_project_by_id
        project = get_project_by_id(supabase, payload.project_id)
        if project and project.get("company_id"):
            company_id = project["company_id"]
            # Optionally update the website URL if it changed
            from app.db.tables.company import update_company
            update_company(supabase, company_id, {"website_url": payload.website_url})

    if not company_id:
        company_data = {
            "workspace_id": workspace["id"],
            "name": name,
            "website_url": payload.website_url,
            "description": None,
            "category": None,
            "target_audience": None,
            "geography": None,
            "language": "en",
            "features": None,
            "benefits": None,
            "pain_points": None,
            "competitors": None,
            "brand_voice": None,
            "forbidden_claims": None,
            "preferred_cta": None,
            "is_active": True,
        }
        company = create_company(supabase, company_data)
        company_id = company["id"]

        if payload.project_id:
            from app.db.tables.projects import update_project
            update_project(supabase, payload.project_id, {"company_id": company_id})

    background_tasks.add_task(_run_full_pipeline_background, company_id)

    return AutoPipelineV2Response(
        company_id=company_id,
        status="started",
        message="Auto-pipeline started. Brand Brain analysis, keyword expansion, and all 9 agents are running in the background. Go to Agent Runs to track progress.",
    )


@router.get("/auto-pipeline/v2/status/{company_id}")
def get_auto_pipeline_v2_status(
    company_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """Get the status of the auto-pipeline for a company."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    company = get_company_by_id(supabase, company_id)
    if not company or company.get("workspace_id") != workspace["id"]:
        raise HTTPException(status_code=404, detail="Company not found.")

    from app.db.tables.agent_runs import list_agent_runs_for_company
    from app.db.tables.brand_keywords import list_brand_keywords_for_company

    runs = list_agent_runs_for_company(supabase, company_id)
    keywords = list_brand_keywords_for_company(supabase, company_id)

    completed = sum(1 for r in runs if r.get("status") == "completed")
    failed = sum(1 for r in runs if r.get("status") == "failed")
    total = len(runs)

    return {
        "company_id": company_id,
        "company_name": company.get("name"),
        "has_extracted_summary": bool(company.get("extracted_summary")),
        "keywords_count": len(keywords),
        "agents_total": total,
        "agents_completed": completed,
        "agents_failed": failed,
        "agents_running": total - completed - failed,
        "runs": [
            {
                "agent_name": r.get("agent_name"),
                "status": r.get("status"),
                "items_fetched": r.get("items_fetched"),
                "items_kept": r.get("items_kept"),
                "started_at": r.get("started_at"),
                "completed_at": r.get("completed_at"),
            }
            for r in runs
        ],
    }
