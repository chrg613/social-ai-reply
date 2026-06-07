"""Technical SEO agent API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, status
from supabase import Client

from app.api.v1.deps import ensure_workspace_membership, get_current_user, get_current_workspace
from app.db.supabase_client import get_supabase
from app.db.tables.agent_runs import get_last_agent_run
from app.db.tables.company import get_company_by_id
from app.db.tables.discovery import list_opportunities_for_project
from app.db.tables.projects import list_projects_for_workspace
from app.services.agents.technical_seo_agent import TechnicalSEOAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["technical-seo"])

agent = TechnicalSEOAgent()


def _run_technical_seo_task(company_id: int, config: dict[str, Any], db: Client) -> None:
    try:
        agent.run(company_id, db, config)
    except Exception:
        logger.exception("Background technical SEO run failed")


@router.post("/technical-seo/run", status_code=status.HTTP_202_ACCEPTED)
def run_technical_seo(
    payload: dict = Body(...),
    background_tasks: BackgroundTasks = None,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    company_id = payload.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required.")

    company = get_company_by_id(supabase, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    if company.get("workspace_id") != workspace["id"]:
        raise HTTPException(status_code=403, detail="Access denied.")

    background_tasks.add_task(_run_technical_seo_task, company_id, payload, supabase)
    return {"status": "running", "agent": "technical_seo"}


@router.get("/technical-seo/audit")
def get_technical_audit(
    company_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    company = get_company_by_id(supabase, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    run = get_last_agent_run(supabase, company_id, "technical_seo")
    projects = list_projects_for_workspace(supabase, workspace["id"])
    project_id = projects[0]["id"] if projects else None

    opps = []
    if project_id:
        opps = list_opportunities_for_project(supabase, project_id, limit=100)

    issues = [o for o in opps if o.get("platform") == "technical_seo" and o.get("opportunity_type") == "code_issue"]

    return {
        "last_run": run,
        "issues": issues,
        "issue_count": len(issues),
    }


@router.get("/technical-seo/issues")
def list_issues_by_severity(
    company_id: int = Query(..., ge=1),
    severity: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[dict[str, Any]]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    company = get_company_by_id(supabase, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    projects = list_projects_for_workspace(supabase, workspace["id"])
    project_id = projects[0]["id"] if projects else None

    opps = []
    if project_id:
        opps = list_opportunities_for_project(supabase, project_id, limit=100)

    issues = [o for o in opps if o.get("platform") == "technical_seo" and o.get("opportunity_type") == "code_issue"]

    if severity:
        issues = [o for o in issues if o.get("severity") == severity]

    return issues
