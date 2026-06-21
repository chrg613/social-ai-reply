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
    return CandidatePost(
        title=post.title or "",
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
) -> list[UnifiedPost]:
    """Run the PlatformRouter search asynchronously."""
    router = PlatformRouter(platforms=platforms)
    return await router.search_all(
        keywords=search_keywords,
        limit_per_platform=limit_per_platform,
    )


def run_platform_scan(
    db: Client,
    project: dict[str, Any],
    *,
    platforms: list[str] | None = None,
    scan_run_id: str | None = None,
    limit_per_platform: int = 25,
    min_score: int = 15,
) -> dict[str, Any]:
    """Scan non-Reddit platforms for opportunities.

    This is designed to be called *after* (or instead of) the existing Reddit
    scanner. It uses the PlatformRouter + RapidAPI adapters to fetch posts
    from Twitter/X, Instagram, TikTok, LinkedIn, etc.

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
    search_keywords = get_project_search_keywords(db, project, limit=15)

    if not search_keywords:
        return {"error": "No active keywords found", "opportunities_found": 0}

    # Run async search in a sync context
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an existing async context (e.g., FastAPI)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                posts = pool.submit(
                    asyncio.run,
                    _async_platform_scan(platforms, search_keywords, limit_per_platform),
                ).result(timeout=120)
        else:
            posts = loop.run_until_complete(
                _async_platform_scan(platforms, search_keywords, limit_per_platform)
            )
    except RuntimeError:
        posts = asyncio.run(
            _async_platform_scan(platforms, search_keywords, limit_per_platform)
        )
    except Exception as e:
        logger.error("Platform scan failed: %s", e)
        return {"error": str(e), "opportunities_found": 0}

    # Score and filter posts
    engine = RelevanceEngine(
        relevance_threshold=min_score,
        semantic_threshold=0.0,
    )
    engine_brand = _engine_brand_profile(brand)
    engine_kw = _engine_keywords(search_keywords)

    opportunities_found = 0
    posts_scanned = len(posts)

    for post in posts:
        candidate = _candidate_from_unified(post)
        relevance = engine.score(
            candidate,
            engine_brand,
            engine_kw,
            source_meta=None,
            source_rules=[],
        )

        if not relevance.should_keep:
            continue

        score_payload = _result_payload(relevance)

        # Create opportunity
        # Review queue: low-confidence opportunities get status "review"
        # so they don't clutter the main feed.
        opp_status = "review" if relevance.confidence < 0.4 else "new"
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
