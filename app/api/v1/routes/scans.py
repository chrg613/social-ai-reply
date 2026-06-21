"""Scan run endpoints."""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from supabase import Client

from app.api.v1.deps import ensure_workspace_membership, get_active_project, get_current_user, get_current_workspace
from app.db.supabase_client import get_supabase
from app.db.tables.discovery import create_scan_run, get_scan_run_by_id
from app.db.tables.projects import get_project_by_id
from app.schemas.v1.discovery import ScanRequest, ScanRunResponse
from app.services.product.scanner import run_scan

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["scans"])


def _run_scan_background(db: Client, project: dict, payload: ScanRequest, scan_run_id: str) -> None:
    try:
        run_scan(db, project, payload, scan_run_id=scan_run_id)
    except Exception:  # noqa: BLE001 — run_scan already persisted the error status
        logger.exception("Background scan %s failed", scan_run_id)

    # Also run multi-platform scan if extra platforms requested
    extra_platforms = payload.platforms
    if not extra_platforms and payload.platform == "all":
        extra_platforms = ["twitter", "instagram", "linkedin"]
    if extra_platforms:
        try:
            from app.services.product.platform_scanner import run_platform_scan
            run_platform_scan(
                db, project,
                platforms=extra_platforms,
                scan_run_id=scan_run_id,
                limit_per_platform=payload.max_posts_per_subreddit,
                min_score=payload.min_score,
            )
        except Exception:
            logger.exception("Multi-platform scan within %s failed", scan_run_id)


@router.post("/scans", response_model=ScanRunResponse)
def create_scan(
    payload: ScanRequest,
    background_tasks: BackgroundTasks,
    project_id: int = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> ScanRunResponse:
    """Start a scan and return immediately; poll GET /v1/scans/{id} for progress.

    When ``platforms`` is provided (e.g., ``["twitter", "linkedin"]``), the scan
    runs the standard Reddit scanner **plus** the multi-platform scanner in the
    same background task.  Set ``platform`` to ``"all"`` as a shortcut for all
    non-Reddit platforms.
    """
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    effective_project_id = project_id or payload.project_id
    proj = get_active_project(supabase, workspace["id"], effective_project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="No active project found.")

    # Fail fast on setup problems — these used to surface synchronously and the
    # frontend expects a 400, not a scan run that instantly errors.
    from app.db.tables.discovery import list_discovery_keywords_for_project, list_monitored_subreddits_for_project
    if not any(k.get("is_active", True) for k in list_discovery_keywords_for_project(supabase, proj["id"])):
        raise HTTPException(status_code=400, detail="Add discovery keywords before scanning.")
    if not any(s.get("is_active", True) for s in list_monitored_subreddits_for_project(supabase, proj["id"])):
        raise HTTPException(status_code=400, detail="Add monitored subreddits before scanning.")

    run = create_scan_run(supabase, {
        "project_id": proj["id"],
        "status": "running",
        "search_window_hours": payload.search_window_hours,
        "posts_scanned": 0,
        "opportunities_found": 0,
        "started_at": datetime.now(UTC).isoformat(),
    })
    background_tasks.add_task(_run_scan_background, supabase, proj, payload, run["id"])
    return ScanRunResponse.model_validate(run)


@router.get("/scans/{scan_id}", response_model=ScanRunResponse)
def get_scan(
    scan_id: str,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> ScanRunResponse:
    """Poll the status/progress of a scan run."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    run = get_scan_run_by_id(supabase, scan_id)
    if not run:
        raise HTTPException(status_code=404, detail="Scan run not found.")
    project = get_project_by_id(supabase, run["project_id"])
    if not project or project.get("workspace_id") != workspace["id"]:
        raise HTTPException(status_code=404, detail="Scan run not found.")
    return ScanRunResponse.model_validate(run)


# ── Multi-platform scanning ─────────────────────────────────────────────


class PlatformScanRequest(ScanRequest):
    """Extended scan request that supports multi-platform scanning."""
    platforms: list[str] = ["twitter"]
    limit_per_platform: int = 25


@router.post("/scans/platforms")
def create_platform_scan(
    payload: PlatformScanRequest,
    background_tasks: BackgroundTasks,
    project_id: int = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """Start a multi-platform scan (Twitter/X, Instagram, etc.).

    This runs alongside the existing Reddit scanner. It uses RapidAPI-powered
    adapters to fetch posts from non-Reddit platforms, score them, and create
    opportunities.
    """
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    effective_project_id = project_id or payload.project_id
    proj = get_active_project(supabase, workspace["id"], effective_project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="No active project found.")

    run = create_scan_run(supabase, {
        "project_id": proj["id"],
        "status": "running",
        "search_window_hours": payload.search_window_hours,
        "posts_scanned": 0,
        "opportunities_found": 0,
        "started_at": datetime.now(UTC).isoformat(),
    })

    def _run_platform_scan_bg(db: Client, project: dict, platforms: list[str], scan_run_id: str, limit: int) -> None:
        try:
            from app.services.product.platform_scanner import run_platform_scan
            result = run_platform_scan(
                db, project,
                platforms=platforms,
                scan_run_id=scan_run_id,
                limit_per_platform=limit,
            )
            from app.db.tables.discovery import update_scan_run
            update_scan_run(db, scan_run_id, {
                "status": "completed",
                "completed_at": datetime.now(UTC).isoformat(),
                "posts_scanned": result.get("posts_scanned", 0),
                "opportunities_found": result.get("opportunities_found", 0),
            })
        except Exception:
            logger.exception("Platform scan %s failed", scan_run_id)
            try:
                from app.db.tables.discovery import update_scan_run as _update
                _update(db, scan_run_id, {
                    "status": "failed",
                    "error_message": "Platform scan failed",
                    "completed_at": datetime.now(UTC).isoformat(),
                })
            except Exception:
                pass

    background_tasks.add_task(
        _run_platform_scan_bg,
        supabase, proj, payload.platforms, run["id"], payload.limit_per_platform,
    )
    return {"scan_run_id": run["id"], "platforms": payload.platforms, "status": "running"}


@router.get("/platforms/health")
async def platform_health(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Check connectivity of all configured platform adapters.

    Returns per-platform health status, rate limit info, and search strategy.
    """
    from app.services.infrastructure.platforms.router import PLATFORM_INFO, PlatformRouter

    all_platforms = [p for p in PLATFORM_INFO if p != "x"]  # skip "x" alias
    router_instance = PlatformRouter(platforms=all_platforms)
    health_results = await router_instance.health_check_all()

    platform_details = {}
    for name in all_platforms:
        info = PLATFORM_INFO.get(name, {})
        platform_details[name] = {
            "healthy": health_results.get(name, False),
            "host": info.get("host", "unknown"),
            "search_strategy": info.get("search", "unknown"),
            "rate_limit": info.get("limit", "unknown"),
        }

    return {"platforms": platform_details}
