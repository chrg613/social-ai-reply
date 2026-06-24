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
from app.services.product.copilot import ProductCopilot
from app.services.product.discovery import discover_and_store_subreddits
from app.services.product.scanner import revalidate_opportunity

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
    """Run an LLM step, retrying once after a short delay on transient failures.

    Only retries on transient errors (network, timeout, rate limit). Permanent
    errors (ValueError, TypeError, KeyError, auth errors) are not retried
    (Issue #63).
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        if _is_transient_error(exc):
            log.warning(
                "%s failed with transient error (%s: %s); retrying once in %.0fs",
                step_name, type(exc).__name__, exc, _LLM_RETRY_DELAY_SECONDS,
            )
            time.sleep(_LLM_RETRY_DELAY_SECONDS)
            return fn()
        # Permanent error — re-raise immediately without retry.
        raise


def _is_transient_error(exc: Exception) -> bool:
    """Return True for errors that may succeed on retry (network, rate limit, timeout)."""
    transient_types = (
        TimeoutError,
        ConnectionError,
        OSError,  # network-related I/O errors
    )
    if isinstance(exc, transient_types):
        return True
    # RuntimeError is used by the LLM service for provider failures. Treat it
    # as transient ONLY when its message clearly indicates a retryable cause
    # (rate limit / 5xx / network). A bare RuntimeError from config or
    # programming bugs must not be retried — it would mask permanent failures
    # (Issue: PR review).
    if isinstance(exc, RuntimeError):
        msg = str(exc).lower()
        transient_indicators = (
            "rate limit",
            "rate_limit",
            "429",
            " 500",
            " 502",
            " 503",
            " 504",
            "timeout",
            "connection",
            "temporarily unavailable",
            "retry",
            "overloaded",
        )
        return any(indicator in msg for indicator in transient_indicators)
    # httpx transient errors
    try:
        import httpx

        if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError,
                            httpx.PoolTimeout, httpx.ConnectTimeout)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in (429, 500, 502, 503, 504)
    except ImportError:
        pass
    # Don't retry on permanent errors (ValueError, TypeError, KeyError, auth errors, etc.)
    return False


def run_auto_pipeline_background(
    pipeline_id: str,
    website_url: str,
    project_id: int,
    workspace_id: int,
    user_id: int,
    time_filter: str = "week",
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

        # ── Step 4: Discover Communities & Scan All Platforms (45→80%) ──
        log.info("Step 4/8: Discovering communities and scanning all platforms")
        update_auto_pipeline(db, pipeline_id, {
            "status": "scanning_all",
            "progress": 50,
            "current_step": "Finding communities and scanning all platforms...",
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

        # ── Step 5: Scan All Platforms (60→80%) ────────────────────
        # Unified scan using RapidAPI adapters for Reddit, Twitter,
        # Instagram, and LinkedIn.  Reddit browses ALL monitored
        # subreddits via the RapidAPI reddit34 adapter + fetches
        # comments for top posts.
        log.info("Step 5/8: Scanning all platforms for opportunities")
        update_auto_pipeline(db, pipeline_id, {
            "progress": 62,
            "status": "scanning_all",
            "current_step": "Scanning Reddit, Twitter, Instagram, LinkedIn...",
        })

        total_opp_found = 0
        try:
            from app.services.product.platform_scanner import run_platform_scan

            available_platforms = ["reddit"]  # Reddit always included
            from app.core.config import get_settings as _get_settings
            if _get_settings().rapidapi_key:
                available_platforms.extend(["twitter", "instagram", "linkedin"])
            else:
                log.info("RAPIDAPI_KEY not set — scanning Reddit only")

            platform_result = run_platform_scan(
                db,
                proj,
                platforms=available_platforms,
                limit_per_platform=50,
                min_score=10,
                time_filter=time_filter,
            )
            total_opp_found = platform_result.get("opportunities_found", 0)
            platform_error = platform_result.get("error")
            if platform_error:
                log.warning("Platform scan returned error (non-fatal): %s", platform_error)
            else:
                log.info(
                    "Multi-platform scan complete — %d opportunities from %s",
                    total_opp_found,
                    ", ".join(available_platforms),
                )
        except Exception as e:
            log.error("Platform scan failed: %s\n%s", e, traceback.format_exc())
            update_auto_pipeline(db, pipeline_id, {
                "status": "failed",
                "error_message": f"Opportunity scan failed: {str(e)[:500]}",
                "completed_at": datetime.now(UTC).isoformat(),
            })
            return

        update_auto_pipeline(db, pipeline_id, {
            "opportunities_found": total_opp_found,
            "progress": 80,
            "current_step": f"Found {total_opp_found} opportunities across all platforms",
        })

        # ── Step 5c: Check Opportunities (80→83%) ────────────────
        log.info("Step 5c/8: Checking opportunities")
        update_auto_pipeline(db, pipeline_id, {
            "status": "checking_opportunities",
            "progress": 82,
            "current_step": f"Checking {total_opp_found} opportunities for relevance...",
        })

        # ── Step 5d: Competitor Intelligence (83→85%) ─────────────
        log.info("Step 5d/8: Competitor intelligence scan")
        update_auto_pipeline(db, pipeline_id, {
            "status": "analyzing_competitors",
            "progress": 83,
            "current_step": "Analyzing competitor mentions...",
        })
        try:
            import asyncio

            from app.services.product.competitor_intel import (
                get_project_competitors,
                process_competitor_opportunities,
            )

            competitors = get_project_competitors(db, project_id)
            if competitors:
                # Build post dicts from the scanned opportunities for competitor detection
                opps_for_comp = list_opportunities_for_project(db, project_id, limit=100)
                post_dicts = [
                    {
                        "title": o.get("title", ""),
                        "body": o.get("body_text", ""),
                        "selftext": o.get("body_text", ""),
                        "platform": o.get("platform", "reddit"),
                        "url": o.get("reddit_post_url") or o.get("post_url", ""),
                        "opportunity_id": o.get("id"),
                    }
                    for o in opps_for_comp
                ]
                # Create a fresh event loop for the async competitor analysis.
                # FastAPI's BackgroundTask may already have a running loop,
                # so asyncio.get_event_loop().run_until_complete() would crash.
                loop = asyncio.new_event_loop()
                try:
                    comp_mentions = loop.run_until_complete(
                        process_competitor_opportunities(db, project_id, post_dicts, competitors)
                    )
                finally:
                    loop.close()
                log.info("Competitor intel: %d mentions detected", len(comp_mentions))
                update_auto_pipeline(db, pipeline_id, {
                    "progress": 85,
                    "current_step": f"Found {len(comp_mentions)} competitor mentions",
                })
            else:
                log.info("No competitors configured — skipping competitor intel")
                update_auto_pipeline(db, pipeline_id, {"progress": 85})
        except Exception as e:
            log.warning("Competitor intel step failed (non-fatal): %s", e)
            update_auto_pipeline(db, pipeline_id, {"progress": 85})

        # ── Step 6: Generate Drafts (85→95%) ────────────────────
        log.info("Step 6/8: Generating reply drafts")
        update_auto_pipeline(db, pipeline_id, {
            "status": "generating_drafts",
            "progress": 85,
            "current_step": "Generating reply drafts...",
        })

        from app.api.v1.deps import ensure_default_prompts
        ensure_default_prompts(db, project_id)
        prompts = list_prompt_templates_for_project(db, project_id)

        opportunities = list_opportunities_for_project(db, project_id, status="new", limit=20)

        drafts_count = 0
        for opp in opportunities:
            try:
                # Revalidation uses a Reddit-specific engine (RedditPost model +
                # topical gate). Non-Reddit opportunities were already scored
                # during scanning and always fail the Reddit gate — skip them.
                opp_platform = (opp.get("platform") or "reddit").lower()
                if opp_platform == "reddit":
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
