"""Keyword and subreddit discovery endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.api.v1.deps import (
    ensure_workspace_membership,
    get_current_user,
    get_current_workspace,
    get_project,
)
from app.db.supabase_client import get_supabase
from app.db.tables.discovery import (
    create_discovery_keyword,
    create_monitored_subreddit,
    delete_discovery_keyword,
    delete_monitored_subreddit,
    get_discovery_keyword_by_id,
    get_monitored_subreddit_by_id,
    list_keywords_for_project,
    list_subreddits_for_project,
)
from app.schemas.v1.discovery import (
    KeywordGenerateRequest,
    KeywordRequest,
    KeywordResponse,
    SubredditDiscoverRequest,
    SubredditRequest,
    SubredditResponse,
)
from app.services.product.copilot import ProductCopilot
from app.services.product.discovery import (
    discover_and_store_subreddits,
    get_project_search_keywords,
    refresh_subreddit_analysis,
)
from app.services.product.entitlements import (
    count_active_keywords,
    count_active_subreddits,
    enforce_limit,
    get_limit,
)
from app.services.product.reddit import RedditClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["discovery"])


@router.get("/discovery/keywords", response_model=list[KeywordResponse])
def list_keywords(
    project_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[KeywordResponse]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    # Validate project access
    get_project(supabase, workspace["id"], project_id)
    rows = list_keywords_for_project(supabase, project_id)
    return [KeywordResponse.model_validate(row) for row in rows]


@router.post("/discovery/keywords", response_model=KeywordResponse, status_code=status.HTTP_201_CREATED)
def create_keyword(
    payload: KeywordRequest,
    project_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> KeywordResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    # Validate project access
    get_project(supabase, workspace["id"], project_id)

    if payload.is_active:
        enforce_limit(supabase, workspace, "keywords", count_active_keywords(supabase, project_id))

    keyword_data = {"project_id": project_id, "source": "manual", **payload.model_dump()}
    row = create_discovery_keyword(supabase, keyword_data)
    return KeywordResponse.model_validate(row)


@router.post("/discovery/keywords/generate", response_model=list[KeywordResponse])
def generate_keywords(
    payload: KeywordGenerateRequest,
    project_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[KeywordResponse]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    project = get_project(supabase, workspace["id"], project_id)

    # Get active personas
    from app.db.tables.discovery import list_personas_for_project
    personas = list_personas_for_project(supabase, project_id, include_inactive=False)

    generated = ProductCopilot().generate_keywords(project.get("brand_profile"), personas, payload.count)
    created = []

    # Batch-fetch all existing keywords for duplicate detection
    existing_keywords = list_keywords_for_project(supabase, project_id)
    existing_keyword_set = {k["keyword"] for k in existing_keywords}

    # Resolve limit once, outside the loop
    current_count = count_active_keywords(supabase, project_id)
    max_keywords = get_limit(supabase, workspace, "keywords")
    available_slots = max_keywords - current_count

    for item in generated:
        if len(created) >= available_slots:
            break
        if item.keyword in existing_keyword_set:
            continue

        keyword_data: dict = {
            "project_id": project_id,
            "keyword": item.keyword,
            "rationale": item.rationale,
            "priority_score": item.priority_score,
            "category": item.category,
            "source": "generated",
            "is_active": True,
        }
        try:
            row = create_discovery_keyword(supabase, keyword_data)
        except Exception:
            # category column may not exist yet — retry without it
            keyword_data.pop("category", None)
            try:
                row = create_discovery_keyword(supabase, keyword_data)
            except Exception as inner_e:
                logger.warning("Failed to insert keyword '%s': %s", item.keyword, inner_e)
                continue
        created.append(row)

    return [KeywordResponse.model_validate(row) for row in created]


@router.delete("/discovery/keywords/{keyword_id}")
def delete_keyword(
    keyword_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, bool]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    row = get_discovery_keyword_by_id(supabase, keyword_id)
    if not row:
        raise HTTPException(status_code=404, detail="Keyword not found.")

    # Verify workspace access via project
    get_project(supabase, workspace["id"], row["project_id"])

    delete_discovery_keyword(supabase, keyword_id)
    return {"ok": True}


@router.get("/discovery/subreddits", response_model=list[SubredditResponse])
def list_subreddits(
    project_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[SubredditResponse]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    # Validate project access
    get_project(supabase, workspace["id"], project_id)
    rows = list_subreddits_for_project(supabase, project_id)
    return [SubredditResponse.model_validate(row) for row in rows]


@router.post("/discovery/subreddits", response_model=SubredditResponse, status_code=status.HTTP_201_CREATED)
def create_subreddit(
    payload: SubredditRequest,
    project_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> SubredditResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    # Validate project access
    get_project(supabase, workspace["id"], project_id)

    if payload.is_active:
        enforce_limit(supabase, workspace, "subreddits", count_active_subreddits(supabase, project_id))

    subreddit_data = {"project_id": project_id, **payload.model_dump()}
    row = create_monitored_subreddit(supabase, subreddit_data)
    return SubredditResponse.model_validate(row)


@router.post("/discovery/subreddits/discover", response_model=list[SubredditResponse])
def discover_subreddits(
    payload: SubredditDiscoverRequest,
    project_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[SubredditResponse]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    project = get_project(supabase, workspace["id"], project_id)

    keywords = list_keywords_for_project(supabase, project_id)
    active_keywords = [k for k in keywords if k.get("is_active", True)]

    if not active_keywords:
        raise HTTPException(status_code=400, detail="Generate or add keywords before discovering subreddits.")

    search_keywords = get_project_search_keywords(supabase, project)
    if not search_keywords:
        raise HTTPException(status_code=400, detail="Add more specific keywords before discovering subreddits.")

    remaining_slots = max(get_limit(supabase, workspace, "subreddits") - count_active_subreddits(supabase, project_id), 0)
    if remaining_slots == 0:
        return []

    created = discover_and_store_subreddits(
        supabase,
        project,
        max_subreddits=min(payload.max_subreddits, remaining_slots),
        reddit=RedditClient(),
    )
    return [SubredditResponse.model_validate(row) for row in created]


@router.post("/subreddits/{subreddit_id}/analyze", response_model=SubredditResponse)
def analyze_subreddit(
    subreddit_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> SubredditResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    subreddit = get_monitored_subreddit_by_id(supabase, subreddit_id)
    if not subreddit:
        raise HTTPException(status_code=404, detail="Subreddit not found.")

    # Verify workspace access
    project = get_project(supabase, workspace["id"], subreddit["project_id"])

    refresh_subreddit_analysis(supabase, project, subreddit, reddit=RedditClient())

    # Refresh from DB
    updated = get_monitored_subreddit_by_id(supabase, subreddit_id)
    return SubredditResponse.model_validate(updated)


@router.delete("/discovery/subreddits/{subreddit_id}")
def delete_subreddit(
    subreddit_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, bool]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    row = get_monitored_subreddit_by_id(supabase, subreddit_id)
    if not row:
        raise HTTPException(status_code=404, detail="Subreddit not found.")

    # Verify workspace access via project
    get_project(supabase, workspace["id"], row["project_id"])

    delete_monitored_subreddit(supabase, subreddit_id)
    return {"ok": True}


