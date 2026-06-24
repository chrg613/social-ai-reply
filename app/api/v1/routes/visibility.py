"""AI Visibility (prompt sets, runs, summaries) endpoints."""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from app.api.v1.deps import (
    ensure_workspace_membership,
    get_active_project,
    get_current_user,
    get_current_workspace,
    get_project,
)
from app.db.supabase_client import get_supabase
from app.db.tables.projects import get_brand_profile_by_project
from app.db.tables.system import create_activity_log
from app.db.tables.visibility import (
    create_ai_response,
    create_brand_mention,
    create_citation,
    create_prompt_run,
    list_prompt_runs_for_prompt_set,
    list_prompt_sets_for_project,
)
from app.db.tables.visibility import (
    create_prompt_set as create_prompt_set_db,
)
from app.services.infrastructure.llm.service import VisibilityRunner
from app.services.product.visibility import CitationExtractor, MentionDetector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["visibility"])


@router.get("/prompt-sets")
def list_prompt_sets(
    project_id: int | None = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    proj = get_active_project(supabase, workspace["id"], project_id)
    if not proj:
        raise HTTPException(404, "No active project found.")
    sets = list_prompt_sets_for_project(supabase, proj["id"])
    return {
        "items": [
            {
                "id": s["id"],
                "name": s["name"],
                "category": s["category"],
                "prompts": s.get("prompts", []),
                "target_models": s.get("target_models", []),
                "is_active": s.get("is_active", True),
                "schedule": s.get("schedule", "manual"),
                "created_at": s.get("created_at"),
            }
            for s in sets
        ]
    }


@router.post("/prompt-sets", status_code=201)
def create_prompt_set(
    payload: dict,
    project_id: int | None = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    proj = get_active_project(supabase, workspace["id"], project_id)
    if not proj:
        raise HTTPException(404, "No active project found.")
    ps = create_prompt_set_db(
        supabase,
        {
            "project_id": proj["id"],
            "name": payload.get("name", "Untitled"),
            "category": payload.get("category", "general"),
            "prompts": payload.get("prompts", []),
            "target_models": payload.get("target_models", ["chatgpt", "perplexity", "gemini", "claude"]),
            "schedule": payload.get("schedule", "manual"),
        },
    )
    create_activity_log(
        supabase,
        {
            "workspace_id": workspace["id"],
            "project_id": proj["id"],
            "actor_user_id": current_user["id"],
            "event_type": "prompt_set.created",
            "entity_type": "PromptSet",
            "entity_id": str(ps["id"]),
        },
    )
    return {"id": ps["id"], "name": ps["name"]}


@router.post("/prompt-sets/{psid}/run")
def run_prompt_set(
    psid: int,
    project_id: int | None = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    # Get prompt set and verify workspace access
    from app.db.tables.visibility import get_prompt_set_by_id
    ps = get_prompt_set_by_id(supabase, psid)
    if not ps:
        raise HTTPException(404, "Prompt set not found.")

    proj = get_project(supabase, workspace["id"], ps["project_id"])
    if project_id is not None and proj["id"] != project_id:
        raise HTTPException(404, "Prompt set not found in the selected project.")

    brand = get_brand_profile_by_project(supabase, proj["id"])
    brand_name = brand["brand_name"] if brand else proj["name"]
    competitors = []

    runner = VisibilityRunner()
    detector = MentionDetector()
    extractor = CitationExtractor()

    results = []
    for prompt_text in ps.get("prompts", []):
        for model in ps.get("target_models", ["chatgpt"]):
            pr = create_prompt_run(
                supabase,
                {
                    "prompt_set_id": ps["id"],
                    "model_name": model,
                    "prompt_text": prompt_text,
                    "status": "running",
                },
            )

            response_text = runner.run_prompt(prompt_text, model)
            if response_text:
                # Update prompt run as complete
                from app.db.tables.visibility import update_prompt_run
                update_prompt_run(
                    supabase,
                    pr["id"],
                    {
                        "status": "complete",
                        "completed_at": datetime.now(UTC).isoformat(),
                    },
                )

                mentions = detector.detect_mentions(response_text, brand_name, competitors)
                citations = extractor.extract_citations(response_text)

                ai_resp = create_ai_response(
                    supabase,
                    {
                        "prompt_run_id": pr["id"],
                        "model_name": model,
                        "raw_response": response_text,
                        "brand_mentioned": mentions["brand_mentioned"],
                        "competitor_mentions": mentions["competitor_mentions"],
                        "sentiment": mentions["sentiment"],
                        "response_length": len(response_text),
                    },
                )

                if mentions["brand_mentioned"]:
                    create_brand_mention(
                        supabase,
                        {
                            "ai_response_id": ai_resp["id"],
                            "entity_name": brand_name,
                            "mention_type": "brand",
                            "context_snippet": response_text[:200],
                        },
                    )
                for comp in mentions["competitor_mentions"]:
                    create_brand_mention(
                        supabase,
                        {
                            "ai_response_id": ai_resp["id"],
                            "entity_name": comp["name"],
                            "mention_type": "competitor",
                        },
                    )
                for cit in citations:
                    create_citation(
                        supabase,
                        {
                            "ai_response_id": ai_resp["id"],
                            "url": cit["url"],
                            "domain": cit["domain"],
                            "content_type": cit["content_type"],
                        },
                    )

                results.append({
                    "prompt": prompt_text[:80],
                    "model": model,
                    "brand_mentioned": mentions["brand_mentioned"],
                    "citations": len(citations),
                })
            else:
                update_prompt_run(
                    supabase,
                    pr["id"],
                    {
                        "status": "failed",
                        "error_message": "No response from model",
                    },
                )
                results.append({
                    "prompt": prompt_text[:80],
                    "model": model,
                    "brand_mentioned": False,
                    "citations": 0,
                    "error": True,
                })

    create_activity_log(
        supabase,
        {
            "workspace_id": workspace["id"],
            "project_id": proj["id"],
            "actor_user_id": current_user["id"],
            "event_type": "visibility.run",
            "entity_type": "PromptSet",
            "entity_id": str(ps["id"]),
        },
    )
    return {"prompt_set_id": ps["id"], "results": results, "total_runs": len(results)}


@router.get("/visibility/summary")
def visibility_summary(
    project_id: int | None = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    proj = get_active_project(supabase, workspace["id"], project_id)
    if not proj:
        raise HTTPException(404, "No active project found.")

    from app.db.tables.visibility import (
        count_ai_responses_with_brand_mention_for_project,
        count_ai_responses_with_model_and_mention,
        count_citations_for_project,
        count_prompt_runs_for_project,
        count_prompt_runs_with_model,
    )

    # N+1 FIX: Batch count queries instead of N+1 queries
    total_runs = count_prompt_runs_for_project(supabase, proj["id"])
    total_mentioned = count_ai_responses_with_brand_mention_for_project(supabase, proj["id"])
    total_citations = count_citations_for_project(supabase, proj["id"])
    sov = round((total_mentioned / total_runs * 100), 1) if total_runs > 0 else 0.0

    models = {}
    for model in ["chatgpt", "perplexity", "gemini", "claude"]:
        m_total = count_prompt_runs_with_model(supabase, proj["id"], model)
        m_mentioned = count_ai_responses_with_model_and_mention(supabase, proj["id"], model)
        models[model] = {
            "total_runs": m_total,
            "brand_mentioned": m_mentioned,
            "share_of_voice": round((m_mentioned / m_total * 100), 1) if m_total > 0 else 0.0,
        }

    return {
        "total_runs": total_runs,
        "brand_mentioned": total_mentioned,
        "share_of_voice": sov,
        "total_citations": total_citations,
        "models": models,
    }


@router.get("/visibility/prompts")
def visibility_prompt_results(
    limit: int = 20,
    offset: int = 0,
    model: str = None,
    project_id: int | None = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    proj = get_active_project(supabase, workspace["id"], project_id)
    if not proj:
        raise HTTPException(404, "No active project found.")

    # Get prompt runs with filtering
    runs = list_prompt_runs_for_prompt_set(
        supabase,
        prompt_set_id=None,  # None means all prompt sets
        project_id=proj["id"],
        model_filter=model,
        limit=limit,
        offset=offset,
    )

    # N+1 FIX: Batch fetch all AI responses for these runs
    run_ids = [r["id"] for r in runs]
    ai_responses_by_run = {}
    if run_ids:
        from app.db.tables.visibility import list_ai_responses_for_runs
        all_responses = list_ai_responses_for_runs(supabase, run_ids)
        ai_responses_by_run = {resp["prompt_run_id"]: resp for resp in all_responses}

    items = []
    for r in runs:
        resp = ai_responses_by_run.get(r["id"])
        items.append({
            "id": r["id"],
            "prompt_text": r["prompt_text"],
            "model_name": r["model_name"],
            "status": r["status"],
            "brand_mentioned": resp["brand_mentioned"] if resp else False,
            "competitor_mentions": resp.get("competitor_mentions", []) if resp else [],
            "sentiment": resp.get("sentiment") if resp else None,
            "citations_count": 0,  # Would need another batch query if needed
            "completed_at": r.get("completed_at"),
        })

    return {"items": items, "total": len(runs)}
