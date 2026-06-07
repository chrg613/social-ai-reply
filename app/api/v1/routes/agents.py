"""Agent run management endpoints."""
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, status
from supabase import Client

from app.api.v1.deps import (
    ensure_workspace_membership,
    get_current_user,
    get_current_workspace,
)
from app.db.supabase_client import get_supabase
from app.db.tables.agent_runs import (
    create_agent_run,
    get_agent_run_by_id,
    list_agent_runs_for_company,
    update_agent_run,
)
from app.schemas.v1.agent_runs import AgentRunCreateRequest, AgentRunResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["agents"])


def run_agent_background(run_id: Any, company_id: int, agent_name: str) -> None:
    from app.db.supabase_client import get_supabase_client
    db = get_supabase_client()
    from app.services.infrastructure.scheduler.service import SchedulerService
    scheduler = SchedulerService()
    try:
        scheduler.run_agent(agent_name, company_id, db, run_id=run_id)
    except Exception:
        logger.exception("Agent run failed")
        try:
            update_agent_run(db, run_id, {
                "status": "failed",
                "error_message": "Unhandled exception in background task",
            })
        except Exception:
            logger.exception("Failed to update agent_run status after error")


@router.post("/agents/run", status_code=status.HTTP_202_ACCEPTED)
def run_agent(
    payload: AgentRunCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    run = create_agent_run(
        supabase,
        {
            "company_id": payload.company_id,
            "agent_name": payload.agent_name,
            "status": "running",
        },
    )
    background_tasks.add_task(
        run_agent_background,
        run["id"],
        payload.company_id,
        payload.agent_name,
    )
    return {"run_id": run["id"], "status": "running"}


@router.post("/agents/run-all", status_code=status.HTTP_202_ACCEPTED)
def run_all_agents(
    background_tasks: BackgroundTasks,
    payload: dict = Body(...),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    company_id = payload.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required.")

    from app.services.infrastructure.scheduler.service import SchedulerService
    scheduler = SchedulerService()
    enabled = scheduler.get_enabled_agents(company_id, supabase)
    runs = []
    for agent_name in enabled:
        run = create_agent_run(
            supabase,
            {
                "company_id": company_id,
                "agent_name": agent_name,
                "status": "running",
            },
        )
        background_tasks.add_task(
            run_agent_background,
            run["id"],
            company_id,
            agent_name,
        )
        runs.append({"run_id": run["id"], "agent_name": agent_name})
    return {"status": "running", "runs": runs}


@router.get("/agents/runs", response_model=list[AgentRunResponse])
def list_agent_runs(
    company_id: int = Query(..., ge=1),
    agent_name: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[AgentRunResponse]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    rows = list_agent_runs_for_company(supabase, company_id, agent_name=agent_name)
    return [AgentRunResponse.model_validate(row) for row in rows]


@router.get("/agents/runs/{run_id}", response_model=AgentRunResponse)
def get_agent_run(
    run_id: str,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> AgentRunResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    run = get_agent_run_by_id(supabase, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    return AgentRunResponse.model_validate(run)


@router.get("/agents/status")
def get_agents_status(
    company_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[dict[str, Any]]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    from app.services.infrastructure.scheduler.service import SchedulerService
    scheduler = SchedulerService()
    registry = scheduler.get_agent_registry()
    status_list = []
    for agent_name in registry:
        status_info = scheduler.get_agent_status(company_id, agent_name, supabase)
        last_run = status_info["last_run"]
        status_list.append(
            {
                "agent_name": agent_name,
                "is_running": status_info["is_running"],
                "last_run": AgentRunResponse.model_validate(last_run).model_dump() if last_run else None,
                "next_run_time": status_info["next_run_time"].isoformat() if status_info["next_run_time"] else None,
            }
        )
    return status_list
