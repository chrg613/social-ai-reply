"""Reply and post draft endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.api.v1.deps import (
    ensure_default_prompts,
    ensure_workspace_membership,
    get_active_project,
    get_current_user,
    get_current_workspace,
    get_project,
)
from app.db.supabase_client import get_supabase
from app.db.tables.content import (
    count_reply_drafts_for_project,
    create_post_draft,
    create_reply_draft,
    get_post_draft_by_id,
    get_reply_draft_by_id,
    list_post_drafts_for_project,
    list_reply_drafts_for_opportunities,
)
from app.db.tables.content import (
    update_post_draft as update_post_draft_db,
)
from app.db.tables.content import (
    update_reply_draft as update_reply_draft_db,
)
from app.db.tables.discovery import (
    count_opportunities_for_project,
    get_opportunity_by_id,
    get_subreddit_by_project_and_name,
    list_opportunities_for_project,
    update_opportunity,
)
from app.db.tables.projects import list_prompt_templates_for_project
from app.db.tables.voice_profiles import (
    get_default_voice_profile_for_project,
    get_voice_profile_by_id,
)
from app.schemas.v1.content import (
    PostDraftRequest,
    PostDraftResponse,
    PostDraftUpdateRequest,
    ReplyDraftRequest,
    ReplyDraftResponse,
    ReplyDraftUpdateRequest,
)
from app.services.product.copilot import ProductCopilot
from app.services.product.copilot.reply import generate_reply
from app.services.product.scanner import revalidate_opportunity

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["drafts"])


@router.post("/drafts/replies", response_model=ReplyDraftResponse, status_code=status.HTTP_201_CREATED)
def generate_reply_draft(
    payload: ReplyDraftRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> ReplyDraftResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    opportunity = get_opportunity_by_id(supabase, payload.opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found.")

    # Verify workspace access
    project = get_project(supabase, workspace["id"], opportunity["project_id"])

    # Revalidation uses a Reddit-specific scoring engine (RedditPost model,
    # topical gate). Non-Reddit opportunities (Twitter, LinkedIn, Instagram)
    # were already scored during scanning and would always fail the Reddit
    # revalidation gate. Skip it for them.
    opp_platform = (opportunity.get("platform") or "reddit").lower()
    if opp_platform == "reddit":
        is_valid, _score = revalidate_opportunity(supabase, project, opportunity)
        if not is_valid:
            update_opportunity(supabase, opportunity["id"], {"status": "ignored"})
            raise HTTPException(status_code=422, detail="Opportunity no longer meets the relevance threshold.")

    ensure_default_prompts(supabase, project["id"])
    prompts = list_prompt_templates_for_project(supabase, project["id"])

    # Resolve the voice profile: explicit request > project default > none.
    voice_profile = None
    if payload.voice_profile_id is not None:
        voice_profile = get_voice_profile_by_id(supabase, payload.voice_profile_id)
        if not voice_profile or voice_profile["project_id"] != project["id"]:
            raise HTTPException(status_code=404, detail="Voice profile not found.")
    else:
        voice_profile = get_default_voice_profile_for_project(supabase, project["id"])

    # Load per-subreddit tone rules from the opportunity's monitored subreddit, if any.
    subreddit_tone_rules = None
    subreddit_name = opportunity.get("subreddit_name") or opportunity.get("subreddit")
    if subreddit_name:
        monitored = get_subreddit_by_project_and_name(supabase, project["id"], subreddit_name)
        if monitored:
            subreddit_tone_rules = monitored.get("tone_rules")

    # Resolve effective platform: explicit override > opportunity's platform > "reddit"
    effective_platform = payload.platform or opportunity.get("platform") or "reddit"

    if payload.variants > 1:
        # Multi-variant generation
        from app.services.product.copilot.reply import generate_reply_variants

        variants = generate_reply_variants(
            opportunity,
            project.get("brand_profile"),
            prompts,
            voice_profile=voice_profile,
            subreddit_tone_rules=subreddit_tone_rules,
            platform=effective_platform,
            count=payload.variants,
        )
        if not variants:
            raise HTTPException(status_code=500, detail="Failed to generate any reply variants.")

        # Save all variants as drafts, return the first one
        first_draft = None
        for i, (content, rationale, source_prompt) in enumerate(variants):
            draft = create_reply_draft(
                supabase,
                {
                    "project_id": project["id"],
                    "opportunity_id": opportunity["id"],
                    "content": content,
                    "rationale": rationale,
                    "source_prompt": source_prompt,
                    "version": i + 1,
                },
            )
            if first_draft is None:
                first_draft = draft

        update_opportunity(supabase, opportunity["id"], {"status": "drafting"})
        return ReplyDraftResponse.model_validate(first_draft)

    # Single reply (default path — unchanged behavior)
    content, rationale, source_prompt = generate_reply(
        opportunity,
        project.get("brand_profile"),
        prompts,
        voice_profile=voice_profile,
        subreddit_tone_rules=subreddit_tone_rules,
        platform=effective_platform,
    )

    draft = create_reply_draft(
        supabase,
        {
            "project_id": project["id"],
            "opportunity_id": opportunity["id"],
            "content": content,
            "rationale": rationale,
            "source_prompt": source_prompt,
            "version": 1,
        },
    )

    # Update opportunity status
    update_opportunity(supabase, opportunity["id"], {"status": "drafting"})

    return ReplyDraftResponse.model_validate(draft)


@router.get("/drafts/replies")
def list_reply_drafts(
    status_filter: str = Query(default="drafting", alias="status"),
    project_id: int | None = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    """List reply drafts with enriched opportunity data for Content Studio.

    FIXED: Uses batch queries instead of N+1 queries.
    """
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    proj = get_active_project(supabase, workspace["id"], project_id)
    if not proj:
        return []

    # Get all opportunities for the project with the given status (batch query)
    opps = list_opportunities_for_project(supabase, proj["id"], status=status_filter, limit=200)
    if not opps:
        return []

    opportunity_ids = [o["id"] for o in opps]
    opp_by_id = {o["id"]: o for o in opps}

    # Get all reply drafts for these opportunities in a single batch query
    # Then select the latest draft for each opportunity
    all_drafts = list_reply_drafts_for_opportunities(supabase, opportunity_ids)

    # Group by opportunity and get latest
    latest_drafts = {}
    for draft in all_drafts:
        opp_id = draft["opportunity_id"]
        if opp_id not in latest_drafts or draft["id"] > latest_drafts[opp_id]["id"]:
            latest_drafts[opp_id] = draft

    results = []
    for opp_id, draft in latest_drafts.items():
        opp = opp_by_id.get(opp_id)
        if opp:
            results.append({
                "id": draft["id"],
                "opportunity_id": opp["id"],
                "content": draft["content"],
                "rationale": draft.get("rationale", ""),
                "version": draft["version"],
                "created_at": draft.get("created_at"),
                "opportunity_title": opp["title"],
                "opportunity_subreddit": opp["subreddit_name"],
                "permalink": opp["permalink"],
                "body_excerpt": opp.get("body_excerpt", ""),
                "platform": opp.get("platform", "reddit"),
                "score": opp.get("score"),
            })

    # Sort by created_at descending
    results.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return results


@router.get("/drafts/count")
def get_draft_counts(
    project_id: int | None = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    """Count drafting and published reply drafts for a project.

    Returns accurate counts from the database rather than deriving them
    from a limited opportunity list.
    """
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    proj = get_active_project(supabase, workspace["id"], project_id)
    if not proj:
        return {"drafting": 0, "published": 0, "total": 0}

    drafting = count_reply_drafts_for_project(supabase, proj["id"])
    published = count_opportunities_for_project(supabase, proj["id"], status="posted")
    return {"drafting": drafting, "published": published, "total": drafting + published}


@router.put("/drafts/replies/{draft_id}", response_model=ReplyDraftResponse)
def update_reply_draft(
    draft_id: int,
    payload: ReplyDraftUpdateRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> ReplyDraftResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    draft = get_reply_draft_by_id(supabase, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Reply draft not found.")

    # Verify workspace access via project
    get_project(supabase, workspace["id"], draft["project_id"])

    updated = update_reply_draft_db(
        supabase,
        draft_id,
        {
            "content": payload.content,
            "rationale": payload.rationale,
        },
    )
    return ReplyDraftResponse.model_validate(updated)


@router.post("/drafts/posts", response_model=PostDraftResponse, status_code=status.HTTP_201_CREATED)
def generate_post_draft(
    payload: PostDraftRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> PostDraftResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    project = get_project(supabase, workspace["id"], payload.project_id)

    ensure_default_prompts(supabase, project["id"])
    prompts = list_prompt_templates_for_project(supabase, project["id"])

    title, body, rationale = ProductCopilot().generate_post(project.get("brand_profile"), prompts)

    # Get next version - batch query
    existing_drafts = list_post_drafts_for_project(supabase, project["id"])
    version = (max((d["version"] for d in existing_drafts), default=0)) + 1

    post_prompts = [p for p in prompts if p.get("prompt_type") == "post"]
    source_prompt = "\n".join(p.get("instructions", "") for p in post_prompts)

    draft = create_post_draft(
        supabase,
        {
            "project_id": project["id"],
            "title": title,
            "body": body,
            "rationale": rationale,
            "source_prompt": source_prompt,
            "version": version,
        },
    )
    return PostDraftResponse.model_validate(draft)


@router.get("/drafts/posts", response_model=list[PostDraftResponse])
def list_post_drafts(
    project_id: int | None = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[PostDraftResponse]:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    proj = get_active_project(supabase, workspace["id"], project_id)
    if not proj:
        return []

    rows = list_post_drafts_for_project(supabase, proj["id"])
    return [PostDraftResponse.model_validate(row) for row in rows]


@router.put("/drafts/posts/{draft_id}", response_model=PostDraftResponse)
def update_post_draft(
    draft_id: int,
    payload: PostDraftUpdateRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> PostDraftResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    draft = get_post_draft_by_id(supabase, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Post draft not found.")

    # Verify workspace access via project
    get_project(supabase, workspace["id"], draft["project_id"])

    updated = update_post_draft_db(
        supabase,
        draft_id,
        {
            "title": payload.title,
            "body": payload.body,
            "rationale": payload.rationale,
        },
    )
    return PostDraftResponse.model_validate(updated)



def list_reply_drafts_for_opportunity(supabase: Client, opportunity_id: int) -> list:
    """Helper to list reply drafts for an opportunity."""
    from app.db.tables.content import list_reply_drafts_for_opportunity as _list
    return _list(supabase, opportunity_id)
