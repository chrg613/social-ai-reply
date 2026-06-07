"""Source management endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.api.v1.deps import (
    ensure_workspace_membership,
    get_current_user,
    get_current_workspace,
)
from app.db.supabase_client import get_supabase
from app.db.tables.company import get_company_by_id
from app.db.tables.sources import (
    create_source,
    delete_source,
    get_source_by_id,
    list_sources_for_company,
    update_source,
)
from app.schemas.v1.sources import (
    SourceCreateRequest,
    SourceResponse,
    SourceUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["sources"])


def _ensure_source_access(supabase: Client, source_id: int, workspace_id: int) -> dict:
    """Verify a source exists and its company belongs to the workspace."""
    source = get_source_by_id(supabase, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found.")
    company = get_company_by_id(supabase, source["company_id"])
    if not company or company.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=404, detail="Source not found.")
    return source


@router.get("/sources", response_model=list[SourceResponse])
def list_sources(
    company_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[SourceResponse]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    rows = list_sources_for_company(supabase, company_id)
    return [SourceResponse.model_validate(row) for row in rows]


@router.post("/sources", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
def create_source_endpoint(
    payload: SourceCreateRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> SourceResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    data = payload.model_dump()
    source = create_source(supabase, data)
    return SourceResponse.model_validate(source)


@router.get("/sources/{source_id}", response_model=SourceResponse)
def get_source(
    source_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> SourceResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    source = _ensure_source_access(supabase, source_id, workspace["id"])
    return SourceResponse.model_validate(source)


@router.put("/sources/{source_id}", response_model=SourceResponse)
def update_source_endpoint(
    source_id: int,
    payload: SourceUpdateRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> SourceResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    _ensure_source_access(supabase, source_id, workspace["id"])
    updated = update_source(supabase, source_id, payload.model_dump(exclude_unset=True))
    return SourceResponse.model_validate(updated)


@router.delete("/sources/{source_id}")
def delete_source_endpoint(
    source_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, bool]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    _ensure_source_access(supabase, source_id, workspace["id"])
    delete_source(supabase, source_id)
    return {"ok": True}
