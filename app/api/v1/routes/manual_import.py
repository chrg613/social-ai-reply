"""Manual import endpoints for X/Twitter and LinkedIn posts."""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from supabase import Client

from app.api.v1.deps import (
    ensure_workspace_membership,
    get_current_user,
    get_current_workspace,
)
from app.db.supabase_client import get_supabase
from app.db.tables.brand_keywords import list_brand_keywords_for_company
from app.db.tables.company import get_company_by_id
from app.db.tables.discovery import create_opportunity
from app.schemas.v1.discovery import OpportunityResponse
from app.services.product.relevance_v2 import CandidatePost, RelevanceEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["manual-import"])


def _build_brand_profile(company: dict[str, Any]) -> dict[str, Any]:
    """Map company_profiles row to a brand_profile dict."""
    pain_points = company.get("pain_points", [])
    benefits = company.get("benefits", [])
    competitors = company.get("competitors", [])

    def _to_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str):
            return [value]
        return []

    return {
        "name": company.get("name", ""),
        "description": company.get("description", ""),
        "category": company.get("category", ""),
        "target_audience": company.get("target_audience", ""),
        "pain_points": _to_list(pain_points),
        "competitors": _to_list(competitors),
        "key_benefits": " ".join(_to_list(benefits)),
    }


def _generate_manual_draft_reply(post_text: str, company: dict[str, Any]) -> str:
    """Generate a draft reply for a manually imported post."""
    brand_name = company.get("name", "our product")
    category = company.get("category", "")
    excerpt = post_text[:120]

    return (
        f"Saw your post about '{excerpt}...'\n\n"
        f"At {brand_name}, this is exactly the space we operate in. "
        f"Here's a thoughtful response you could share:\n\n"
        f"— Acknowledge the specific point they made\n"
        f"— Share a brief insight or lesson from {category or 'our work'}\n"
        f"— Offer a specific resource or next step (no hard pitch)\n\n"
        f"Adapt this to your voice before posting."
    )


def _score_and_create_manual_opportunity(
    supabase: Client,
    company_id: int,
    platform: str,
    post_url: str | None,
    post_text: str,
    author: str | None,
    min_score: int | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Run a manual import through the relevance engine and create an opportunity if it passes.

    Returns:
        (opportunity_dict, None) if kept, or (None, rejection_reason) if rejected.
    """
    company = get_company_by_id(supabase, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    brand_profile = _build_brand_profile(company)
    brand_keywords = list_brand_keywords_for_company(supabase, company_id, enabled_only=True)

    relevance_keywords = [
        {"keyword": kw["keyword"], "type": kw.get("type", "core"), "weight": kw.get("weight", 1.0)}
        for kw in brand_keywords
    ]

    engine = RelevanceEngine(relevance_threshold=min_score)
    candidate = CandidatePost(
        title=post_text[:200],
        body=post_text,
        platform=platform,
        source_name=platform,
        upvotes=0,
        comments_count=0,
        created_at=datetime.now(UTC),
        author=author or "",
        post_url=post_url or "",
    )

    score_result = engine.score(candidate, brand_profile, relevance_keywords)

    if score_result.should_keep:
        draft_reply = _generate_manual_draft_reply(post_text, company)
        opp = create_opportunity(
            supabase,
            {
                "company_id": company_id,
                "platform": platform,
                "post_url": post_url,
                "title": post_text[:200],
                "content": post_text,
                "author": author,
                "agent_name": "manual_import",
                "status": "new",
                "score": score_result.relevance_score,
                "semantic_similarity": score_result.semantic_similarity,
                "matched_keywords": score_result.matched_keywords,
                "intent": score_result.intent,
                "reason_relevant": score_result.reason_relevant,
                "risk_flags": score_result.risk_flags,
                "draft_reply": draft_reply,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        return opp, None

    return None, score_result.rejection_reason


def _ensure_company_in_workspace(supabase: Client, company_id: int, workspace_id: int) -> None:
    company = get_company_by_id(supabase, company_id)
    if not company or company.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=404, detail="Company not found.")


@router.post("/manual-import/x", response_model=OpportunityResponse, status_code=status.HTTP_201_CREATED)
def import_x_post(
    payload: dict = Body(...),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> OpportunityResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    company_id = payload.get("company_id")
    post_url = payload.get("post_url")
    post_text = payload.get("post_text")
    author = payload.get("author")
    min_score = payload.get("min_score")

    if not company_id or not post_text:
        raise HTTPException(status_code=400, detail="company_id and post_text are required.")
    _ensure_company_in_workspace(supabase, company_id, workspace["id"])

    opp, rejection_reason = _score_and_create_manual_opportunity(
        supabase, company_id, "x", post_url, post_text, author, min_score=min_score
    )
    if opp is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Post rejected by relevance filter: {rejection_reason}",
        )
    return OpportunityResponse.model_validate(opp)


@router.post("/manual-import/x/csv", status_code=status.HTTP_201_CREATED)
def import_x_csv(
    payload: list[dict] = Body(...),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    created: list[int] = []
    rejected: list[dict] = []
    for item in payload:
        company_id = item.get("company_id")
        post_url = item.get("post_url")
        post_text = item.get("post_text")
        author = item.get("author")
        min_score = item.get("min_score")
        if not company_id or not post_text:
            continue
        _ensure_company_in_workspace(supabase, company_id, workspace["id"])
        try:
            opp, rejection_reason = _score_and_create_manual_opportunity(
                supabase, company_id, "x", post_url, post_text, author, min_score=min_score
            )
            if opp:
                created.append(opp["id"])
            else:
                rejected.append({"post_text": post_text[:100], "reason": rejection_reason})
        except HTTPException:
            # Company validation failure — skip this row
            continue
    return {"created": len(created), "ids": created, "rejected": len(rejected), "rejections": rejected}


@router.post("/manual-import/linkedin", response_model=OpportunityResponse, status_code=status.HTTP_201_CREATED)
def import_linkedin_post(
    payload: dict = Body(...),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> OpportunityResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    company_id = payload.get("company_id")
    post_url = payload.get("post_url")
    post_text = payload.get("post_text")
    author = payload.get("author")
    min_score = payload.get("min_score")

    if not company_id or not post_text:
        raise HTTPException(status_code=400, detail="company_id and post_text are required.")
    _ensure_company_in_workspace(supabase, company_id, workspace["id"])

    opp, rejection_reason = _score_and_create_manual_opportunity(
        supabase, company_id, "linkedin", post_url, post_text, author, min_score=min_score
    )
    if opp is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Post rejected by relevance filter: {rejection_reason}",
        )
    return OpportunityResponse.model_validate(opp)


@router.post("/manual-import/linkedin/csv", status_code=status.HTTP_201_CREATED)
def import_linkedin_csv(
    payload: list[dict] = Body(...),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    created: list[int] = []
    rejected: list[dict] = []
    for item in payload:
        company_id = item.get("company_id")
        post_url = item.get("post_url")
        post_text = item.get("post_text")
        author = item.get("author")
        min_score = item.get("min_score")
        if not company_id or not post_text:
            continue
        _ensure_company_in_workspace(supabase, company_id, workspace["id"])
        try:
            opp, rejection_reason = _score_and_create_manual_opportunity(
                supabase, company_id, "linkedin", post_url, post_text, author, min_score=min_score
            )
            if opp:
                created.append(opp["id"])
            else:
                rejected.append({"post_text": post_text[:100], "reason": rejection_reason})
        except HTTPException:
            continue
    return {"created": len(created), "ids": created, "rejected": len(rejected), "rejections": rejected}


@router.get("/manual-import/queries")
def get_suggested_queries(
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    queries = {
        "x": [
            "from:company_name product OR tool",
            "from:company_name launch OR announcement",
            "to:company_name help OR support",
        ],
        "linkedin": [
            "site:linkedin.com/posts company_name product",
            "site:linkedin.com/posts company_name industry insights",
        ],
    }
    return {"queries": queries}
