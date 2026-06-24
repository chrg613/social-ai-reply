"""Project management endpoints."""
import logging

from fastapi import APIRouter, Depends, Query, status
from supabase import Client

from app.api.v1.deps import (
    ensure_workspace_membership,
    get_active_project,
    get_current_user,
    get_current_workspace,
    get_project,
    subscription_response,
)
from app.db.supabase_client import get_supabase
from app.db.tables.discovery import list_personas_for_project as list_personas
from app.db.tables.discovery import list_subreddits_for_project
from app.db.tables.projects import (
    create_brand_profile,
    create_project,
    create_prompt_template,
    delete_brand_profile,
    delete_project,
    get_brand_profile_by_project,
    list_projects_for_workspace,
    list_prompt_templates_for_project,
    update_project,
)
from app.schemas.v1.discovery import OpportunityResponse
from app.schemas.v1.projects import (
    DashboardResponse,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    SetupStatus,
)
from app.services.product.entitlements import enforce_limit
from app.utils.slug import unique_slug

logger = logging.getLogger(__name__)


def _ensure_default_prompts_inline(supabase, project_id: int) -> None:
    """Ensure default prompt templates exist for a project."""
    defaults = [
        {
            "prompt_type": "reply",
            "name": "Helpful Reply",
            "system_prompt": "You write grounded Reddit replies that help first and pitch never.",
            "instructions": "Start with empathy, answer the actual question, avoid hard CTAs, and only mention the product when invited.",
        },
        {
            "prompt_type": "post",
            "name": "Educational Post",
            "system_prompt": "You write Reddit posts that teach from direct experience.",
            "instructions": "Use first-hand lessons, concrete examples, and end with an invitation for discussion rather than a promo CTA.",
        },
        {
            "prompt_type": "analysis",
            "name": "Signal Review",
            "system_prompt": "You summarize opportunities with clarity and no fluff.",
            "instructions": "Highlight why the thread matters, what the risk is, and how the brand can contribute credibly.",
        },
    ]
    existing = list_prompt_templates_for_project(supabase, project_id)
    existing_types = {p["prompt_type"] for p in existing}
    for prompt in defaults:
        if prompt["prompt_type"] not in existing_types:
            prompt_data = {**prompt, "project_id": project_id, "is_default": True}
            create_prompt_template(supabase, prompt_data)

router = APIRouter(prefix="/v1", tags=["projects"])


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    project_id: int | None = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> DashboardResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    projects = list_projects_for_workspace(supabase, workspace["id"])
    selected_project = get_active_project(supabase, workspace["id"], project_id)
    project_ids = [selected_project["id"]] if selected_project else [p["id"] for p in projects]

    # Get top opportunities
    top_opportunities = []
    if project_ids:
        from app.db.tables.discovery import list_opportunities_for_project
        for pid in project_ids[:1]:  # Limit to first project
            opps = list_opportunities_for_project(supabase, pid, limit=12)
            top_opportunities.extend(opps)

    # Build setup status
    setup = SetupStatus()
    if selected_project:
        pid = selected_project["id"]
        brand = get_brand_profile_by_project(supabase, pid)
        setup.brand_configured = brand is not None and bool(brand.get("brand_name"))
        setup.personas_count = len(list_personas(supabase, pid))
        setup.subreddits_count = len(list_subreddits_for_project(supabase, pid))
    elif project_ids:
        pid = project_ids[0]
        brand = get_brand_profile_by_project(supabase, pid)
        setup.brand_configured = brand is not None and bool(brand.get("brand_name"))
        setup.personas_count = len(list_personas(supabase, pid))
        setup.subreddits_count = len(list_subreddits_for_project(supabase, pid))

    return DashboardResponse(
        projects=[ProjectResponse.model_validate(p) for p in projects],
        top_opportunities=[OpportunityResponse.model_validate(o) for o in top_opportunities],
        subscription=subscription_response(supabase, workspace).model_dump(),
        setup_status=setup,
        drafts_count=sum(1 for o in top_opportunities if o.get("status") == "drafting"),
        published_count=sum(1 for o in top_opportunities if o.get("status") == "posted"),
    )


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[ProjectResponse]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    rows = list_projects_for_workspace(supabase, workspace["id"])
    return [ProjectResponse.model_validate(row) for row in rows]


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project_endpoint(
    payload: ProjectCreateRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> ProjectResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    # Check limit
    project_count = len(list_projects_for_workspace(supabase, workspace["id"]))
    enforce_limit(supabase, workspace, "projects", project_count)

    slug = unique_slug(supabase, "projects", payload.name.strip(), "workspace_id", workspace["id"])

    project_data = {
        "workspace_id": workspace["id"],
        "name": payload.name.strip(),
        "slug": slug,
        "description": payload.description,
        "status": "active",
    }
    project = create_project(supabase, project_data)

    # Create brand profile
    create_brand_profile(
        supabase,
        {
            "project_id": project["id"],
            "brand_name": project["name"],
            "summary": None,
            "voice_notes": None,
            "product_summary": None,
            "target_audience": None,
            "call_to_action": None,
            "business_domain": None,
            "linkedin_url": None,
        },
    )

    # Ensure default prompts
    _ensure_default_prompts_inline(supabase, project["id"])

    return ProjectResponse.model_validate(project)


@router.put("/projects/{project_id}", response_model=ProjectResponse)
def update_project_endpoint(
    project_id: int,
    payload: ProjectUpdateRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> ProjectResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    # Validate project access
    get_project(supabase, workspace["id"], project_id)

    update_data = {
        "name": payload.name.strip(),
        "description": payload.description,
        "status": payload.status,
    }
    updated = update_project(supabase, project_id, update_data)
    return ProjectResponse.model_validate(updated)


@router.delete("/projects/{project_id}")
def delete_project_endpoint(
    project_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, bool]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    # Validate project access
    get_project(supabase, workspace["id"], project_id)

    # Delete brand profile first
    brand = get_brand_profile_by_project(supabase, project_id)
    if brand:
        delete_brand_profile(supabase, brand["id"])

    delete_project(supabase, project_id)
    return {"ok": True}
