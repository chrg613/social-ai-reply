"""Multi-platform scanning via the adapter system.

This module provides the bridge between the new PlatformRouter (RapidAPI-powered)
and the existing opportunity pipeline. It can be used:
  1. As a supplement to the existing Reddit scanner (add Twitter results alongside)
  2. As a standalone scan for non-Reddit platforms

The existing `run_scan()` in scanner.py remains untouched for Reddit — this module
handles the *additional* platforms only.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from app.db.tables.discovery import (
    batch_get_opportunities_by_reddit_posts,
    create_opportunity,
    update_scan_run,
)
from app.db.tables.projects import get_brand_profile_by_project
from app.services.infrastructure.platforms.router import PlatformRouter
from app.services.product.discovery import get_project_search_keywords
from app.services.product.intent_ladder import stage_from_intent
from app.services.product.relevance_v2 import CandidatePost, RelevanceEngine, RelevanceResult

if TYPE_CHECKING:
    from supabase import Client

    from app.services.infrastructure.platforms.models import UnifiedPost

logger = logging.getLogger(__name__)


def _candidate_from_unified(post: UnifiedPost) -> CandidatePost:
    """Convert a UnifiedPost to a CandidatePost for scoring."""
    # Tweets and some LinkedIn posts have no title — use body excerpt instead
    # so the relevance engine has text to score against.
    title = post.title or post.body[:200]
    return CandidatePost(
        title=title,
        body=post.body,
        platform=post.platform,
        source_name=post.subreddit or post.platform,
        upvotes=post.upvotes,
        comments_count=post.comments_count,
        created_at=post.created_at,
        author=post.author,
        post_url=post.url,
    )


def _result_payload(result: RelevanceResult) -> dict[str, Any]:
    """Build opportunity column dict from a RelevanceResult."""
    stage, stage_confidence = stage_from_intent(result.intent)
    reasons = [result.reason_relevant] if result.reason_relevant else []
    if result.rejection_reason:
        reasons.insert(0, result.rejection_reason)
    return {
        "score": result.relevance_score,
        "score_reasons": reasons,
        "keyword_hits": result.matched_keywords[:5],
        "rule_risk": result.rule_risk,
        "intent": result.intent,
        "intent_confidence": stage_confidence,
        "buying_stage": stage,
        "semantic_similarity": result.semantic_similarity,
        "matched_keywords": result.matched_keywords,
        "risk_flags": result.risk_flags,
        "reason_relevant": result.reason_relevant or None,
        "rejection_reason": result.rejection_reason,
        "scoring_breakdown": result.scoring_breakdown,
        "confidence": result.confidence,
    }


def _engine_brand_profile(brand: dict[str, Any] | None) -> dict[str, Any]:
    brand = brand or {}
    description = " ".join(filter(None, [brand.get("summary"), brand.get("product_summary")]))
    return {
        "name": brand.get("brand_name", ""),
        "brand_name": brand.get("brand_name", ""),
        "description": description,
        "category": brand.get("business_domain", ""),
        "target_audience": brand.get("target_audience", ""),
        "pain_points": [],
        "competitors": [],
    }


def _engine_keywords(keywords: list[str]) -> list[dict[str, Any]]:
    return [{"keyword": kw, "type": "core"} for kw in keywords]


async def _async_platform_scan(
    platforms: list[str],
    search_keywords: list[str],
    limit_per_platform: int = 25,
    subreddits: list[str] | None = None,
    time_filter: str = "week",
) -> list[UnifiedPost]:
    """Run the PlatformRouter search asynchronously."""
    # If Reddit is included and we have subreddits, configure the adapter
    # to browse them instead of just fetching popular posts.
    if subreddits and "reddit" in platforms:
        from app.services.infrastructure.platforms.router import _get_adapter

        reddit_adapter = _get_adapter("reddit")
        reddit_adapter.set_subreddits(subreddits)

    router = PlatformRouter(platforms=platforms)
    return await router.search_all(
        keywords=search_keywords,
        limit_per_platform=limit_per_platform,
        fetch_comments=True,
        time_filter=time_filter,
    )


def run_platform_scan(
    db: Client,
    project: dict[str, Any],
    *,
    platforms: list[str] | None = None,
    scan_run_id: str | None = None,
    limit_per_platform: int = 25,
    min_score: int = 15,
    time_filter: str = "week",
) -> dict[str, Any]:
    """Scan platforms for opportunities using RapidAPI adapters.

    Supports all platforms including Reddit. When Reddit is in the list,
    monitored subreddits are loaded from the DB and browsed via RapidAPI.

    Args:
        db: Supabase client.
        project: Project dict with id, workspace_id.
        platforms: List of platforms to scan. Defaults to ["twitter"].
        scan_run_id: Optional existing scan_run to update (for combined scans).
        limit_per_platform: Max posts to fetch per platform.
        min_score: Minimum relevance score to keep.

    Returns:
        Summary dict with opportunities_found, posts_scanned, platforms_scanned.
    """
    if platforms is None:
        platforms = ["twitter"]

    brand = get_brand_profile_by_project(db, project["id"])
    search_keywords = get_project_search_keywords(db, project, limit=30)

    if not search_keywords:
        return {"error": "No active keywords found", "opportunities_found": 0}

    # Load monitored subreddits when Reddit is in the scan list
    subreddits: list[str] | None = None
    if "reddit" in platforms:
        from app.db.tables.discovery import list_monitored_subreddits_for_project

        active_subs = list_monitored_subreddits_for_project(db, project["id"])
        subreddits = [s["name"] for s in active_subs if s.get("is_active", True)]
        if subreddits:
            logger.info("Reddit scan will browse %d subreddits: %s", len(subreddits), subreddits[:5])
        else:
            logger.warning("No active monitored subreddits — Reddit scan may return limited results")

    # Run async search in a sync context.
    # BackgroundTasks in FastAPI run in a thread, not the event loop, so we
    # must NOT touch the running loop directly — that deadlocks.  Instead,
    # we always spin up a fresh event loop via asyncio.run(), wrapped with a
    # hard wall-clock timeout so a hung API call can never block forever.
    total_timeout_seconds = 180 if "reddit" in platforms else 90
    try:
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="platform_scan") as pool:
            future = pool.submit(
                asyncio.run,
                _async_platform_scan(platforms, search_keywords, limit_per_platform, subreddits=subreddits, time_filter=time_filter),
            )
            posts = future.result(timeout=total_timeout_seconds)
    except _cf.TimeoutError:
        logger.warning(
            "Platform scan timed out after %ds — returning zero results",
            total_timeout_seconds,
        )
        posts = []
    except Exception as e:
        logger.error("Platform scan failed: %s", e)
        return {"error": str(e), "opportunities_found": 0}

    # Score and filter posts
    # Non-Reddit posts (tweets, LinkedIn) are shorter and naturally score
    # lower than long Reddit threads.  Use a relaxed threshold so they
    # aren't all filtered out.
    effective_threshold = max(5, min_score - 10)
    engine = RelevanceEngine(
        relevance_threshold=effective_threshold,
        semantic_threshold=0.0,
    )
    engine_brand = _engine_brand_profile(brand)
    engine_kw = _engine_keywords(search_keywords)

    opportunities_found = 0
    posts_scanned = len(posts)

    # Deduplicate: check which posts already have opportunities
    all_reddit_post_ids = [f"{post.platform}_{post.external_id}" for post in posts]
    existing_opps = batch_get_opportunities_by_reddit_posts(db, project["id"], all_reddit_post_ids) if all_reddit_post_ids else {}

    for post in posts:
        candidate = _candidate_from_unified(post)
        reddit_post_id = f"{post.platform}_{post.external_id}"

        # Skip if opportunity already exists for this post
        if reddit_post_id in existing_opps:
            logger.debug("Skipping duplicate %s opportunity: %s", post.platform, reddit_post_id)
            continue

        relevance = engine.score(
            candidate,
            engine_brand,
            engine_kw,
            source_meta=None,
            source_rules=[],
        )

        logger.info(
            "[%s] Post '%s' scored %d, keep=%s, reason=%s",
            post.platform,
            (post.title or post.body)[:50],
            relevance.relevance_score,
            relevance.should_keep,
            relevance.rejection_reason,
        )

        if not relevance.should_keep:
            # Rescue borderline posts that have keyword matches — give
            # them a chance to be reviewed manually instead of being
            # silently dropped.
            if relevance.relevance_score >= 10 and relevance.matched_keywords:
                logger.info(
                    "[%s] Rescuing borderline post (score=%d, kw=%s) as 'review'",
                    post.platform,
                    relevance.relevance_score,
                    relevance.matched_keywords[:3],
                )
            else:
                continue

        score_payload = _result_payload(relevance)

        # Posts that passed the threshold get "new"; rescued borderline posts
        # that only survived the keyword-match rescue get "review".
        opp_status = "new" if relevance.should_keep else "review"
        opp_data = {
            "project_id": project["id"],
            "platform": post.platform,
            "reddit_post_id": f"{post.platform}_{post.external_id}",
            "title": post.title or post.body[:100],
            "author": post.author,
            "subreddit_name": post.subreddit or post.platform,
            "body_excerpt": post.body[:1200],
            "permalink": post.url,
            "upvotes": post.upvotes,
            "comments_count": post.comments_count,
            "status": opp_status,
            "source_type": "post",
            **score_payload,
        }

        if scan_run_id:
            opp_data["scan_run_id"] = scan_run_id

        try:
            create_opportunity(db, opp_data)
            opportunities_found += 1
        except Exception as e:
            logger.warning("Failed to create %s opportunity: %s", post.platform, e)

    # Update scan run if provided
    if scan_run_id:
        with contextlib.suppress(Exception):
            update_scan_run(db, scan_run_id, {
                "posts_scanned": posts_scanned,
                "opportunities_found": opportunities_found,
            })

    logger.info(
        "Platform scan complete: %d posts scanned, %d opportunities from %s",
        posts_scanned, opportunities_found, platforms,
    )

    return {
        "platforms_scanned": platforms,
        "posts_scanned": posts_scanned,
        "opportunities_found": opportunities_found,
    }
