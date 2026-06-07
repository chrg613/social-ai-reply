"""Company management endpoints."""
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from supabase import Client

from app.api.v1.deps import (
    ensure_workspace_membership,
    get_current_user,
    get_current_workspace,
)
from app.db.supabase_client import get_supabase, get_supabase_client
from app.db.tables.brand_keywords import list_brand_keywords_for_company
from app.db.tables.company import (
    create_company,
    delete_company,
    get_company_by_id,
    list_companies_for_workspace,
    update_company,
)
from app.db.tables.sources import create_source
from app.schemas.v1.brand_keywords import BrandKeywordResponse
from app.schemas.v1.company import (
    CompanyCreateRequest,
    CompanyResponse,
    CompanyUpdateRequest,
)
from app.services.product.brand_brain import BrandBrain
from app.services.product.keyword_expansion import KeywordExpansionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["company"])


def _run_company_analysis_background(company_id: int) -> None:
    """Background task for company website analysis using Brand Brain."""
    try:
        supabase = get_supabase_client()
        company = get_company_by_id(supabase, company_id)
        if not company:
            logger.warning("Company %s not found for analysis.", company_id)
            return
        website_url = company.get("website_url")
        if not website_url:
            logger.info("No website_url for company %s; skipping analysis.", company_id)
            return
        brain = BrandBrain()
        brain.analyze_website(website_url, company, supabase)
        logger.info("Brand Brain analysis completed for company %s", company_id)
    except Exception:
        logger.exception("Brand Brain analysis failed for company %s", company_id)


def _run_keyword_generation_background(company_id: int) -> None:
    """Background task for keyword expansion."""
    try:
        supabase = get_supabase_client()
        company = get_company_by_id(supabase, company_id)
        if not company:
            logger.warning("Company %s not found for keyword generation.", company_id)
            return
        service = KeywordExpansionService()
        keywords = service.expand(company)
        if keywords:
            service.store_keywords(supabase, company_id, keywords)
        logger.info("Keyword expansion completed for company %s (%s keywords)", company_id, len(keywords))
    except Exception:
        logger.exception("Keyword generation failed for company %s", company_id)


@router.get("/companies", response_model=list[CompanyResponse])
def list_companies(
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[CompanyResponse]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    rows = list_companies_for_workspace(supabase, workspace["id"])
    return [CompanyResponse.model_validate(row) for row in rows]


def _create_default_sources(supabase: Client, company_id: int) -> None:
    """Create default active sources for a new company."""
    defaults = [
        {"company_id": company_id, "platform": "reddit", "status": "active", "priority": 100, "config": {}},
        {"company_id": company_id, "platform": "hackernews", "status": "active", "priority": 90, "config": {}},
        {"company_id": company_id, "platform": "seo", "status": "active", "priority": 80, "config": {}},
        {"company_id": company_id, "platform": "geo", "status": "active", "priority": 70, "config": {}},
        {"company_id": company_id, "platform": "articles", "status": "active", "priority": 60, "config": {}},
        {"company_id": company_id, "platform": "x", "status": "active", "priority": 50, "config": {}},
        {"company_id": company_id, "platform": "linkedin", "status": "active", "priority": 40, "config": {}},
        {"company_id": company_id, "platform": "ugc", "status": "active", "priority": 30, "config": {}},
        {"company_id": company_id, "platform": "technical_seo", "status": "active", "priority": 20, "config": {}},
    ]
    for source_data in defaults:
        try:
            create_source(supabase, source_data)
        except Exception:
            logger.warning("Failed to create default source %s for company %s", source_data["platform"], company_id, exc_info=True)


@router.post("/companies", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company_endpoint(
    payload: CompanyCreateRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> CompanyResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    data = payload.model_dump()
    data["workspace_id"] = workspace["id"]
    company = create_company(supabase, data)
    _create_default_sources(supabase, company["id"])
    return CompanyResponse.model_validate(company)


@router.get("/companies/{company_id}", response_model=CompanyResponse)
def get_company(
    company_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> CompanyResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    company = get_company_by_id(supabase, company_id)
    if not company or company.get("workspace_id") != workspace["id"]:
        raise HTTPException(status_code=404, detail="Company not found.")
    return CompanyResponse.model_validate(company)


@router.put("/companies/{company_id}", response_model=CompanyResponse)
def update_company_endpoint(
    company_id: int,
    payload: CompanyUpdateRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> CompanyResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    company = get_company_by_id(supabase, company_id)
    if not company or company.get("workspace_id") != workspace["id"]:
        raise HTTPException(status_code=404, detail="Company not found.")
    updated = update_company(supabase, company_id, payload.model_dump(exclude_unset=True))
    return CompanyResponse.model_validate(updated)


@router.delete("/companies/{company_id}")
def delete_company_endpoint(
    company_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, bool]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    company = get_company_by_id(supabase, company_id)
    if not company or company.get("workspace_id") != workspace["id"]:
        raise HTTPException(status_code=404, detail="Company not found.")
    delete_company(supabase, company_id)
    return {"ok": True}


@router.post("/companies/{company_id}/analyze", status_code=status.HTTP_202_ACCEPTED)
def analyze_company(
    company_id: int,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    """Trigger brand brain website analysis."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    company = get_company_by_id(supabase, company_id)
    if not company or company.get("workspace_id") != workspace["id"]:
        raise HTTPException(status_code=404, detail="Company not found.")
    background_tasks.add_task(_run_company_analysis_background, company_id)
    return {"status": "accepted", "company_id": company_id, "message": "Analysis started."}


@router.post("/companies/{company_id}/keywords/generate", status_code=status.HTTP_202_ACCEPTED)
def generate_keywords(
    company_id: int,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    """Trigger keyword expansion for a company."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    company = get_company_by_id(supabase, company_id)
    if not company or company.get("workspace_id") != workspace["id"]:
        raise HTTPException(status_code=404, detail="Company not found.")
    background_tasks.add_task(_run_keyword_generation_background, company_id)
    return {"status": "accepted", "company_id": company_id, "message": "Keyword generation started."}


@router.get("/companies/{company_id}/keywords", response_model=list[BrandKeywordResponse])
def list_company_keywords(
    company_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[BrandKeywordResponse]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    company = get_company_by_id(supabase, company_id)
    if not company or company.get("workspace_id") != workspace["id"]:
        raise HTTPException(status_code=404, detail="Company not found.")
    rows = list_brand_keywords_for_company(supabase, company_id)
    return [BrandKeywordResponse.model_validate(row) for row in rows]
