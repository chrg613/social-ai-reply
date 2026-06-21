"""Background task to run the auto-pipeline from website URL to sales package."""

import logging
import time
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar

from app.db.tables.analytics import get_auto_pipeline_by_id, update_auto_pipeline
from app.db.tables.content import create_reply_draft
from app.db.tables.discovery import (
    list_monitored_subreddits_for_project,
    list_opportunities_for_project,
    list_personas_for_project,
    update_opportunity,
)
from app.db.tables.projects import (
    create_brand_profile,
    get_brand_profile_by_project,
    get_project_by_id,
    list_prompt_templates_for_project,
    update_brand_profile,
)
from app.db.tables.system import create_notification
from app.schemas.v1.discovery import ScanRequest
from app.services.product.copilot import ProductCopilot
from app.services.product.discovery import discover_and_store_subreddits
from app.services.product.scanner import revalidate_opportunity, run_scan
from app.services.product.scoring import MIN_RELEVANT_OPPORTUNITY_SCORE

log = logging.getLogger("signalflow.pipeline")
TARGET_PIPELINE_SUBREDDITS = 10
TARGET_PIPELINE_KEYWORDS = 10
_LLM_RETRY_DELAY_SECONDS = 5.0

T = TypeVar("T")

# Brand profile fields the pipeline produces and downstream steps consume.
_BRAND_FIELDS = (
    "brand_name",
    "summary",
    "product_summary",
    "target_audience",
    "call_to_action",
    "voice_notes",
    "business_domain",
)


def _retry_once(step_name: str, fn: Callable[[], T]) -> T:
    """Run an LLM step, retrying once after a short delay on any failure."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        log.warning("%s failed (%s); retrying once in %.0fs", step_name, exc, _LLM_RETRY_DELAY_SECONDS)
        time.sleep(_LLM_RETRY_DELAY_SECONDS)
        return fn()


def run_auto_pipeline_background(
    pipeline_id: str,
    website_url: str,
    project_id: int,
    workspace_id: int,
    user_id: int,
):
    from app.db.supabase_client import get_supabase_client
    db = get_supabase_client()

    log.info("=== AUTO-PIPELINE START === id=%s url=%s project=%s", pipeline_id, website_url, project_id)

    try:
        pipeline = get_auto_pipeline_by_id(db, pipeline_id)
        if not pipeline:
            log.error("Pipeline %s not found in DB — aborting.", pipeline_id)
            return

        proj = get_project_by_id(db, project_id)
        if not proj:
            log.error("Project %s not found in DB — aborting.", project_id)
            return

        copilot = ProductCopilot()
        log.info("Step 1/8: Analyzing website %s", website_url)

        # ── Step 1: Analyze Website (0→15%) ─────────────────────
        update_auto_pipeline(db, pipeline_id, {
            "status": "analyzing",
            "progress": 5,
            "current_step": "Analyzing website content...",
        })

        brand = get_brand_profile_by_project(db, project_id)
        brand_complete = bool(
            brand
            and (brand.get("summary") or "").strip()
            and (brand.get("business_domain") or "").strip()
        )

        if brand_complete:
            # Resume path: a previous (possibly failed) run already produced a
            # full brand profile — reuse it instead of re-running the LLM.
            log.info("Brand profile already complete for project %s — skipping website analysis", project_id)
            update_auto_pipeline(db, pipeline_id, {"brand_summary": brand.get("summary"), "progress": 15})
        else:
            try:
                website_analysis = _retry_once(
                    "Website analysis", lambda: copilot.analyze_website(website_url)
                )
                log.info("Website analysis OK — brand=%s summary_len=%d",
                         website_analysis.brand_name, len(website_analysis.summary or ""))
            except Exception as e:
                log.error("Website analysis FAILED: %s\n%s", e, traceback.format_exc())
                raise

            update_auto_pipeline(db, pipeline_id, {"brand_summary": website_analysis.summary, "progress": 15})

            analysis_fields = {key: getattr(website_analysis, key) for key in _BRAND_FIELDS}
            if brand:
                updated_brand = update_brand_profile(db, brand["id"], analysis_fields)
                if updated_brand is None:
                    log.warning(
                        "BrandProfile update returned no row for project %s; refetching persisted record",
                        project_id,
                    )
                    updated_brand = get_brand_profile_by_project(db, project_id)
                    if updated_brand is None:
                        raise RuntimeError(f"Brand profile update did not persist for project {project_id}.")
                brand = updated_brand
                log.info("Updated existing BrandProfile id=%s", brand["id"])
            else:
                brand = create_brand_profile(db, {
                    "project_id": project_id,
                    **analysis_fields,
                })
                log.info("Created new BrandProfile for project %s", project_id)

        # Attach brand profile to proj so downstream discovery steps have
        # domain context. discover_and_store_subreddits and the helpers it
        # calls (get_project_search_keywords, assess_subreddit_candidate)
        # all read project["brand_profile"] — without this, business_domain
        # is empty and discovery filters out nearly every candidate.
        proj["brand_profile"] = brand

        # ── Step 2: Generate Personas (15→30%) ──────────────────
        log.info("Step 2/8: Generating personas")
        update_auto_pipeline(db, pipeline_id, {
            "status": "generating_personas",
            "progress": 20,
            "current_step": "Generating target personas...",
        })

        # Read brand fields from the persisted row so the resume path (which
        # skips website analysis) and the fresh path share one source of truth.
        brand_dict = {key: brand.get(key) for key in _BRAND_FIELDS}

        existing_personas = list_personas_for_project(db, project_id)
        if existing_personas:
            log.info("Project %s already has %d personas — skipping generation", project_id, len(existing_personas))
            update_auto_pipeline(db, pipeline_id, {"personas_generated": len(existing_personas), "progress": 30})
        else:
            try:
                personas_data = _retry_once(
                    "Persona generation", lambda: copilot.suggest_personas(brand_dict, count=4)
                )
                log.info("Generated %d personas", len(personas_data))
            except Exception as e:
                log.error("Persona generation FAILED: %s\n%s", e, traceback.format_exc())
                raise

            from app.db.tables.discovery import create_persona
            for p_data in personas_data:
                create_persona(db, {
                    "project_id": project_id,
                    "name": p_data["name"],
                    "role": p_data.get("role"),
                    "summary": p_data["summary"],
                    "pain_points": p_data.get("pain_points", []),
                    "goals": p_data.get("goals", []),
                    "triggers": p_data.get("triggers", []),
                    "preferred_subreddits": p_data.get("preferred_subreddits", []),
                    "source": p_data.get("source", "generated"),
                    "is_active": True,
                })
            update_auto_pipeline(db, pipeline_id, {"personas_generated": len(personas_data), "progress": 30})

        # ── Step 3: Discover Keywords (30→45%) ──────────────────
        log.info("Step 3/8: Discovering keywords")
        update_auto_pipeline(db, pipeline_id, {
            "status": "discovering_keywords",
            "progress": 35,
            "current_step": "Discovering relevant keywords...",
        })

        personas_list = list_personas_for_project(db, project_id)
        from app.db.tables.discovery import create_discovery_keyword, list_discovery_keywords_for_project
        existing_kw_rows = list_discovery_keywords_for_project(db, project_id)

        # On re-runs, deactivate old auto-generated keywords so fresh ones replace them.
        # Manual keywords (source != 'generated') are always preserved.
        stale_rationale_prefixes = ("Domain-specific keyword", "Heuristic keyword")
        stale_generated = [
            row for row in existing_kw_rows
            if row.get("source") == "generated"
            and any((row.get("rationale") or "").startswith(p) for p in stale_rationale_prefixes)
        ]
        if stale_generated:
            from app.db.tables.discovery import update_discovery_keyword
            for row in stale_generated:
                update_discovery_keyword(db, row["id"], {"is_active": False})
            log.info("Deactivated %d stale generated keywords", len(stale_generated))
            # Refresh the active keyword set after deactivation
            existing_kw_rows = list_discovery_keywords_for_project(db, project_id)

        existing_kw = {row["keyword"] for row in existing_kw_rows}

        if len(existing_kw) >= TARGET_PIPELINE_KEYWORDS:
            log.info("Project %s already has %d quality keywords — skipping generation", project_id, len(existing_kw))
            update_auto_pipeline(db, pipeline_id, {"keywords_generated": len(existing_kw), "progress": 45})
        else:
            try:
                keywords_data = _retry_once(
                    "Keyword generation",
                    lambda: copilot.generate_keywords(brand_dict, personas_list, count=15),
                )
                log.info("Generated %d keywords", len(keywords_data))
            except Exception as e:
                log.error("Keyword generation FAILED: %s\n%s", e, traceback.format_exc())
                raise

            new_kw_count = 0
            # copilot.generate_keywords returns list[GeneratedKeyword] (a @dataclass),
            # NOT list[dict] — use attribute access, not subscript. suggest_personas
            # returns list[dict] so the pattern is different for personas above.
            for k_data in keywords_data:
                if k_data.keyword in existing_kw:
                    log.info("Keyword '%s' already exists — skipping", k_data.keyword)
                    continue
                create_discovery_keyword(db, {
                    "project_id": project_id,
                    "keyword": k_data.keyword,
                    "rationale": k_data.rationale,
                    "priority_score": k_data.priority_score,
                    "category": k_data.category,
                    "source": "generated",
                    "is_active": True,
                })
                existing_kw.add(k_data.keyword)
                new_kw_count += 1
            update_auto_pipeline(db, pipeline_id, {"keywords_generated": len(keywords_data), "progress": 45})
            log.info("Inserted %d new keywords (%d already existed)", new_kw_count, len(keywords_data) - new_kw_count)

        # ── Step 4: Discover Subreddits (45→60%) ────────────────
        log.info("Step 4/8: Discovering subreddits")
        update_auto_pipeline(db, pipeline_id, {
            "status": "finding_subreddits",
            "progress": 50,
            "current_step": "Discovering relevant subreddits...",
        })

        existing_sub_count = len(list_monitored_subreddits_for_project(db, project_id))
        subreddits_to_discover = max(TARGET_PIPELINE_SUBREDDITS - existing_sub_count, 0)
        try:
            if subreddits_to_discover > 0:
                created_subreddits = discover_and_store_subreddits(
                    db,
                    proj,
                    max_subreddits=subreddits_to_discover,
                )
                discovered_subreddits = [row["name"] for row in created_subreddits]
            else:
                discovered_subreddits = []
                log.info(
                    "Skipping subreddit discovery because project %s already has %d active subreddits",
                    project_id,
                    existing_sub_count,
                )
        except Exception as e:
            log.error("Subreddit discovery FAILED (non-fatal, continuing with existing): %s\n%s", e, traceback.format_exc())
            discovered_subreddits = []

        if not discovered_subreddits and subreddits_to_discover > 0:
            log.warning("Subreddit discovery returned 0 results for project %s — continuing with existing subreddits", project_id)

        total_subreddits = existing_sub_count + len(discovered_subreddits)
        update_auto_pipeline(db, pipeline_id, {
            "subreddits_found": total_subreddits,
            "progress": 60,
        })
        log.info("Discovered %d new subreddits (%d already existed)", len(discovered_subreddits), existing_sub_count)

        # If we still have zero subreddits, the scan will fail — bail out early
        # with a clear message instead of letting run_scan raise a confusing 400.
        if total_subreddits == 0:
            error_msg = (
                "No subreddits could be discovered. This usually means Reddit's public "
                "search is temporarily rate-limiting requests from this server. Please add "
                "subreddits manually from the Discovery page, or try again in a few minutes."
            )
            log.error("Pipeline aborting: %s", error_msg)
            update_auto_pipeline(db, pipeline_id, {
                "status": "failed",
                "error_message": error_msg,
                "completed_at": datetime.now(UTC).isoformat(),
            })
            create_notification(db, {
                "workspace_id": workspace_id,
                "type": "pipeline_error",
                "title": "Pipeline: No subreddits found",
                "message": error_msg,
            })
            return

        # ── Step 5: Scan Reddit for Opportunities (60→70%) ────────
        log.info("Step 5/8: Scanning Reddit for opportunities")
        update_auto_pipeline(db, pipeline_id, {
            "status": "scanning_opportunities",
            "progress": 62,
            "current_step": "Cooling down before scanning (Reddit rate-limit recovery)...",
        })

        # Cool down after discovery — Reddit rate-limits aggressively and the
        # discovery phase may have exhausted the HTTP budget.  A short pause
        # lets the rate-limiter window slide and resets our circuit breakers so
        # the scanner starts with a clean slate.
        import time as _time

        from app.services.product.reddit_discovery import _HTTP_BUDGET
        _time.sleep(10)
        _HTTP_BUDGET._hosts.clear()  # reset all circuit breakers

        opp_found = 0
        try:
            scan_req = ScanRequest(
                project_id=project_id,
                search_window_hours=72,
                max_posts_per_subreddit=25,
                min_score=15,
            )
            scan_run = run_scan(db, proj, scan_req)
            if scan_run.get("fatal_error"):
                raise RuntimeError(scan_run.get("error_message") or "Opportunity scan could not access Reddit.")
            primary_opp_found = scan_run["opportunities_found"]
            opp_found = primary_opp_found
            # Fallback scan: when the narrow 72-hour window yields nothing,
            # widen the time horizon to 30 days AND drop the score floor so
            # the user gets *something* to review.
            if opp_found <= 3:
                fallback_scan_req = ScanRequest(
                    project_id=project_id,
                    search_window_hours=720,
                    max_posts_per_subreddit=25,
                    min_score=max(MIN_RELEVANT_OPPORTUNITY_SCORE - 10, 15),
                )
                fallback_scan_run = run_scan(db, proj, fallback_scan_req)
                if fallback_scan_run.get("fatal_error"):
                    raise RuntimeError(fallback_scan_run.get("error_message") or "Opportunity scan could not access Reddit.")
                opp_found = primary_opp_found + fallback_scan_run["opportunities_found"]
            log.info("Reddit scan complete — %d opportunities found", opp_found)
        except Exception as e:
            log.error("Reddit scan step failed: %s\n%s", e, traceback.format_exc())
            update_auto_pipeline(db, pipeline_id, {
                "status": "failed",
                "error_message": f"Opportunity scan failed: {str(e)[:500]}",
                "completed_at": datetime.now(UTC).isoformat(),
            })
            return
        update_auto_pipeline(db, pipeline_id, {"opportunities_found": opp_found, "progress": 70})

        # ── Step 5b: Multi-Platform Scan (70→80%) ────────────────
        # Scan Twitter, Instagram, LinkedIn for additional opportunities
        # using the RapidAPI adapters. This is non-fatal: if platform
        # scanning fails (no API key, network error, etc.) the pipeline
        # continues with whatever Reddit already found.
        log.info("Step 5b/8: Scanning social platforms (Twitter, Instagram, LinkedIn)")
        update_auto_pipeline(db, pipeline_id, {
            "status": "scanning_platforms",
            "progress": 72,
            "current_step": "Scanning Twitter, Instagram, LinkedIn for opportunities...",
        })

        platform_opp_found = 0
        try:
            from app.services.product.platform_scanner import run_platform_scan

            available_platforms = []
            # Check which platforms we can scan (need RAPIDAPI_KEY)
            import os
            if os.getenv("RAPIDAPI_KEY"):
                available_platforms = ["twitter", "instagram", "linkedin"]
            else:
                log.info("RAPIDAPI_KEY not set — skipping multi-platform scan")

            if available_platforms:
                platform_result = run_platform_scan(
                    db,
                    proj,
                    platforms=available_platforms,
                    limit_per_platform=25,
                    min_score=15,
                )
                platform_opp_found = platform_result.get("opportunities_found", 0)
                platform_error = platform_result.get("error")
                if platform_error:
                    log.warning("Platform scan returned error (non-fatal): %s", platform_error)
                else:
                    log.info(
                        "Multi-platform scan complete — %d opportunities from %s",
                        platform_opp_found,
                        ", ".join(available_platforms),
                    )
        except Exception as e:
            log.warning("Multi-platform scan failed (non-fatal, continuing): %s\n%s", e, traceback.format_exc())

        total_opp_found = opp_found + platform_opp_found
        update_auto_pipeline(db, pipeline_id, {
            "opportunities_found": total_opp_found,
            "progress": 80,
            "current_step": f"Found {total_opp_found} opportunities ({opp_found} Reddit + {platform_opp_found} social)",
        })

        # ── Step 6: Generate Drafts (75→95%) ────────────────────
        log.info("Step 6/8: Generating reply drafts")
        update_auto_pipeline(db, pipeline_id, {
            "status": "generating_drafts",
            "progress": 80,
            "current_step": "Generating reply drafts...",
        })

        from app.api.v1.deps import ensure_default_prompts
        ensure_default_prompts(db, project_id)
        prompts = list_prompt_templates_for_project(db, project_id)

        opportunities = list_opportunities_for_project(db, project_id, status="new", limit=10)

        drafts_count = 0
        for opp in opportunities:
            try:
                is_valid, _score = revalidate_opportunity(db, proj, opp)
                if not is_valid:
                    update_opportunity(db, opp["id"], {"status": "ignored"})
                    continue
                content, rationale, _source_prompt = copilot.generate_reply(
                    opp, brand_dict, prompts,
                    platform=opp.get("platform"),
                )
                create_reply_draft(db, {
                    "project_id": project_id,
                    "opportunity_id": opp["id"],
                    "content": content,
                    "rationale": rationale,
                })
                update_opportunity(db, opp["id"], {"status": "drafting"})
                drafts_count += 1
            except Exception as e:
                log.warning("Draft generation failed for opp %s: %s", opp["id"], e)

        update_auto_pipeline(db, pipeline_id, {"drafts_generated": drafts_count, "progress": 95})
        log.info("Generated %d drafts for %d opportunities", drafts_count, len(opportunities))

        # ── Step 7: Finalize (95→100%) ──────────────────────────
        log.info("Step 7/8: Finalizing sales package")
        update_auto_pipeline(db, pipeline_id, {
            "current_step": "Finalizing sales package...",
        })

        update_auto_pipeline(db, pipeline_id, {
            "status": "ready",
            "progress": 100,
            "current_step": "Complete!",
            "completed_at": datetime.now(UTC).isoformat(),
        })

        # Create notification
        try:
            create_notification(db, {
                "workspace_id": workspace_id,
                "user_id": user_id,
                "title": "Sales Package Ready!",
                "body": f"Your auto-pipeline for {proj['name']} is complete. Review and launch your sales package.",
                "type": "opportunity",
            })
        except Exception as e:
            log.warning("Notification creation failed (non-fatal): %s", e)

        log.info("=== AUTO-PIPELINE COMPLETE === id=%s status=ready", pipeline_id)

    except Exception as e:
        log.error("=== AUTO-PIPELINE FAILED === id=%s error=%s\n%s", pipeline_id, e, traceback.format_exc())
        try:
            update_auto_pipeline(db, pipeline_id, {
                "status": "failed",
                "error_message": str(e)[:500],
                "completed_at": datetime.now(UTC).isoformat(),
            })
        except Exception as inner:
            log.error("Failed to save error status: %s", inner)
