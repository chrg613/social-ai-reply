"""Hacker News Agent — discovers and scores HN stories for a company.

Steps:
1. Build search queries from Brand Brain.
2. Fetch top/new/ask/show stories from HN public API.
3. Filter for engagement (comments > 5 OR points > 10).
4. Normalize and deduplicate by item ID.
5. Run RelevanceEngine v2 with platform='hackernews'.
6. Generate drafts with HN-appropriate tone.
7. Store opportunities and update agent_runs.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.db.tables.agent_runs import create_agent_run, update_agent_run
from app.db.tables.brand_keywords import list_brand_keywords_for_company
from app.db.tables.company import get_company_by_id
from app.db.tables.discovery import (
    bulk_create_opportunities,
    get_opportunity_by_project_and_reddit_post,
    update_opportunity,
)
from app.services.infrastructure.apis.hackernews import HackerNewsAPI
from app.services.product.copilot._facade import ProductCopilot
from app.services.product.relevance_v2 import CandidatePost, RelevanceEngine

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)

_MAX_REJECTED_PER_RUN = 50
_MIN_HN_COMMENTS = 5
_MIN_HN_POINTS = 10


@dataclass
class AgentRunResult:
    items_fetched: int = 0
    items_kept: int = 0
    items_rejected: int = 0
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


class HackerNewsAgent:
    """Platform-aware Hacker News discovery agent."""

    def __init__(self) -> None:
        self._hn = HackerNewsAPI()
        self._copilot = ProductCopilot()

    def run(
        self,
        company_id: int,
        db: Client,
        config: dict[str, Any],
    ) -> AgentRunResult:
        """Execute a full HN discovery and drafting run."""
        result = AgentRunResult()
        started_at = datetime.now(UTC)
        search_window_days = config.get("search_window_days", 7)
        min_score = config.get("min_score", 60)
        draft_mode = config.get("draft_mode", "helpful_no_pitch")
        max_items = config.get("max_items", 160)

        # ── 1. Load Brand Brain ──────────────────────────────────────
        company = get_company_by_id(db, company_id)
        if not company:
            result.logs.append(f"ERROR: Company {company_id} not found")
            return result

        brand_keywords = list_brand_keywords_for_company(db, company_id, enabled_only=True)
        if not brand_keywords:
            result.logs.append(f"WARNING: No enabled brand keywords for company {company_id}")

        # Sort by weight, take top 10 per type
        keywords_by_type: dict[str, list[dict[str, Any]]] = {}
        for kw in brand_keywords:
            kw_type = str(kw.get("type", "core")).lower()
            keywords_by_type.setdefault(kw_type, []).append(kw)
        for ktype in keywords_by_type:
            keywords_by_type[ktype].sort(key=lambda x: float(x.get("weight", 1.0)), reverse=True)
            keywords_by_type[ktype] = keywords_by_type[ktype][:10]
        top_keywords = []
        for ktype in keywords_by_type:
            top_keywords.extend(keywords_by_type[ktype])
        top_keywords.sort(key=lambda x: float(x.get("weight", 1.0)), reverse=True)

        relevance_keywords = [
            {"keyword": kw["keyword"], "type": kw.get("type", "core"), "weight": kw.get("weight", 1.0)}
            for kw in top_keywords
        ]
        brand_profile = self._build_brand_profile(company)
        result.logs.append(f"Loaded {len(top_keywords)} brand keywords")

        # ── 2. Create agent run record ─────────────────────────────────
        run = create_agent_run(db, {
            "company_id": company_id,
            "agent_name": "hackernews_v2",
            "status": "running",
            "started_at": started_at.isoformat(),
        })
        run_id = run["id"]

        try:
            # ── 3. Fetch stories ───────────────────────────────────────
            cutoff = started_at - timedelta(days=search_window_days)
            story_ids: set[int] = set()

            # Fetch IDs from multiple feeds
            feeds = {
                "top": self._hn.get_top_story_ids(limit=50),
                "new": self._hn.get_new_story_ids(limit=50),
                "ask": self._hn.get_ask_story_ids(limit=30),
                "show": self._hn.get_show_story_ids(limit=30),
            }
            for feed_name, ids in feeds.items():
                result.logs.append(f"HN {feed_name} stories: {len(ids)} IDs fetched")
                for sid in ids:
                    story_ids.add(sid)
                time.sleep(0.3)  # Gentle spacing between feed fetches

            # Hydrate items
            candidates: list[dict[str, Any]] = []
            for sid in list(story_ids)[:max_items]:
                try:
                    item = self._hn.get_item(sid)
                    if not item:
                        continue
                    # Only story items with title
                    if item.get("type") != "story" or not item.get("title"):
                        continue
                    # Engagement filter
                    descendants = item.get("descendants") or 0
                    score = item.get("score") or 0
                    if descendants < _MIN_HN_COMMENTS and score < _MIN_HN_POINTS:
                        continue
                    # Time filter
                    item_time = item.get("time")
                    if item_time:
                        post_dt = datetime.fromtimestamp(item_time, tz=UTC)
                        if post_dt < cutoff:
                            continue
                    candidates.append(item)
                except Exception as exc:
                    logger.warning("HN item fetch failed for %s: %s", sid, exc)
                # Respect rate limit: 30 req / 10s ≈ 0.33s between requests
                time.sleep(0.35)

            result.items_fetched = len(candidates)
            result.logs.append(f"Hydrated {len(candidates)} candidate stories")

            # ── 4. Deduplicate by item ID ──────────────────────────────
            # Already deduped by set above, but double-check by id
            by_id: dict[int, dict[str, Any]] = {}
            for item in candidates:
                by_id[item["id"]] = item
            unique_items = list(by_id.values())

            # ── 5. Run relevance engine ────────────────────────────────
            engine = RelevanceEngine(relevance_threshold=min_score)
            kept_opportunities: list[dict[str, Any]] = []
            rejected_count = 0

            for item in unique_items:
                candidate = CandidatePost(
                    title=item.get("title", ""),
                    body=item.get("text", ""),
                    platform="hackernews",
                    source_name="news.ycombinator.com",
                    upvotes=item.get("score", 0),
                    comments_count=item.get("descendants", 0),
                    created_at=datetime.fromtimestamp(item["time"], tz=UTC) if item.get("time") else None,
                    author=item.get("by", ""),
                    post_url=f"https://news.ycombinator.com/item?id={item['id']}",
                )
                score_result = engine.score(candidate, brand_profile, relevance_keywords)

                if score_result.should_keep:
                    opp = self._build_opportunity(
                        item=item,
                        company_id=company_id,
                        score_result=score_result,
                    )
                    kept_opportunities.append(opp)
                else:
                    rejected_count += 1
                    if rejected_count <= _MAX_REJECTED_PER_RUN:
                        result.logs.append(
                            f"REJECTED '{item.get('title', '')[:60]}': {score_result.rejection_reason}"
                        )

            result.items_kept = len(kept_opportunities)
            result.items_rejected = rejected_count
            result.logs.append(f"Relevance: {len(kept_opportunities)} kept, {rejected_count} rejected")

            # ── 6. Generate drafts ─────────────────────────────────────
            for opp in kept_opportunities:
                try:
                    draft = self._generate_hn_draft(opp, brand_profile, mode=draft_mode)
                    opp["draft_reply"] = draft
                    opp["reason_relevant"] = opp.get("reason_relevant", "")
                except Exception as exc:
                    logger.warning("Draft generation failed for opp %s: %s", opp.get("title", ""), exc)
                    result.logs.append(f"Draft generation failed: {exc}")

            # ── 7. Store results ───────────────────────────────────────
            stored: list[dict[str, Any]] = []
            if kept_opportunities:
                new_opps: list[dict[str, Any]] = []
                updated = 0
                for opp in kept_opportunities:
                    existing = get_opportunity_by_project_and_reddit_post(
                        db, opp.get("project_id"), opp.get("reddit_post_id", "")
                    )
                    if existing:
                        if existing.get("status") in ("new", "rejected", None):
                            update_data = {
                                "score": opp["score"],
                                "semantic_similarity": opp.get("semantic_similarity"),
                                "matched_keywords": opp.get("matched_keywords"),
                                "intent": opp.get("intent"),
                                "reason_relevant": opp.get("reason_relevant"),
                                "risk_flags": opp.get("risk_flags"),
                                "draft_reply": opp.get("draft_reply"),
                                "status": "new",
                            }
                            update_opportunity(db, existing["id"], update_data)
                            updated += 1
                    else:
                        new_opps.append(opp)

                if new_opps:
                    stored = bulk_create_opportunities(db, new_opps)
                result.logs.append(f"Stored: {len(stored)} new, {updated} updated")

            result.opportunities = stored

            update_agent_run(db, run_id, {
                "status": "completed",
                "items_fetched": result.items_fetched,
                "items_kept": result.items_kept,
                "items_rejected": result.items_rejected,
                "finished_at": datetime.now(UTC).isoformat(),
                "logs_json": result.logs,
            })
        except Exception as exc:
            logger.exception("HackerNewsAgent run failed")
            result.logs.append(f"FATAL ERROR: {type(exc).__name__}: {exc}")
            update_agent_run(db, run_id, {
                "status": "error",
                "error_message": str(exc)[:500],
                "finished_at": datetime.now(UTC).isoformat(),
                "logs_json": result.logs,
            })

        return result

    def generate_show_hn_draft(self, company_profile: dict[str, Any]) -> dict[str, Any]:
        """Generate a 'Show HN' style post for the user's product.

        Returns dict with: titles (3 options), product_intro,
        technical_explanation, target_audience, why_built_it.
        """
        name = company_profile.get("name", "our product")
        description = company_profile.get("description", "")
        features = _jsonb_to_list(company_profile.get("features"))
        pain_points = _jsonb_to_list(company_profile.get("pain_points"))
        category = company_profile.get("category", "")

        titles = [
            f"Show HN: {name} — {description[:80]}",
            f"Show HN: I built {name} because {pain_points[0] if pain_points else 'of a problem I faced'}",
            f"Show HN: {name}, a {category} tool we wished existed",
        ]

        product_intro = (
            f"{name} is {description[:200]}. "
            f"It helps you {features[0] if features else 'solve a real problem'} "
            f"without the usual complexity."
        )

        technical_explanation = (
            "Built with a modern stack focused on reliability and performance. "
            "We kept the architecture simple on purpose — fewer moving parts, fewer surprises. "
            "Open to technical questions in the comments."
        )

        target_audience = (
            company_profile.get("target_audience", "")
            or "founders, developers, and operators who care about doing things right"
        )

        why_built_it = (
            f"We built {name} because {pain_points[0] if pain_points else 'existing solutions were too complicated'}. "
            f"After trying {len(pain_points) if pain_points else 'a few'} alternatives, "
            f"we decided to build exactly what we needed."
        )

        return {
            "titles": titles,
            "product_intro": product_intro,
            "technical_explanation": technical_explanation,
            "target_audience": target_audience,
            "why_built_it": why_built_it,
        }

    # ── Internal helpers ───────────────────────────────────────────────

    @staticmethod
    def _build_brand_profile(company: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": company.get("name", ""),
            "description": company.get("description", ""),
            "category": company.get("category", ""),
            "target_audience": company.get("target_audience", ""),
            "pain_points": _jsonb_to_list(company.get("pain_points")),
            "competitors": _jsonb_to_list(company.get("competitors")),
            "key_benefits": " ".join(_jsonb_to_list(company.get("benefits"))),
        }

    def _generate_hn_draft(
        self,
        opportunity: dict[str, Any],
        company_profile: dict[str, Any],
        mode: str,
    ) -> str:
        """Generate a draft with HN-appropriate tone."""
        title = opportunity.get("title", "")
        brand_name = company_profile.get("name", "our product")
        intent = opportunity.get("intent", "")

        # Try LLM first
        brand = {
            "brand_name": brand_name,
            "summary": company_profile.get("description", ""),
            "voice_notes": "technical, honest, non-marketing, no hype",
            "call_to_action": company_profile.get("preferred_cta", ""),
        }
        opp_for_copilot = dict(opportunity)
        opp_for_copilot["reply_mode"] = mode
        opp_for_copilot["subreddit"] = "hackernews"

        try:
            prompts = []
            content, rationale, _source = self._copilot.generate_reply(opp_for_copilot, brand, prompts)
            if content:
                return content
        except Exception as exc:
            logger.warning("ProductCopilot HN draft failed: %s", exc)

        # Fallback templates with HN tone
        if "ask" in intent.lower() or "question" in title.lower():
            return (
                f"Here's my take on this:\n\n"
                f"1. ...\n2. ...\n3. ...\n\n"
                f"If you're looking for a tool, {brand_name} handles this exact workflow. "
                f"Happy to answer questions if anyone is curious."
            )

        if "show" in intent.lower() or "launch" in title.lower():
            return (
                f"Congrats on the launch. A few thoughts:\n\n"
                f"- ...\n- ...\n\n"
                f"We're working on something similar at {brand_name} — would love to compare notes."
            )

        if mode == "founder_disclosure":
            return (
                f"Founder of {brand_name} here. We ran into this exact issue. "
                f"The approach that worked for us was ...\n\n"
                f"No pressure, but feel free to reach out if you want to chat."
            )

        if mode == "educational_only":
            return (
                "A couple of things that usually matter here:\n\n"
                "1. ...\n2. ...\n3. ...\n\n"
                "Source: built something in this space and learned the hard way."
            )

        # Default: helpful, no pitch
        return (
            f"A few observations that might help:\n\n"
            f"• ...\n• ...\n• ...\n\n"
            f"Built something related at {brand_name}, but this advice stands on its own."
        )

    @staticmethod
    def _build_opportunity(
        item: dict[str, Any],
        company_id: int,
        score_result: Any,
    ) -> dict[str, Any]:
        post_created = None
        if item.get("time"):
            post_created = datetime.fromtimestamp(item["time"], tz=UTC).isoformat()
        return {
            "project_id": item.get("project_id"),  # may be None; caller can patch
            "platform": "hackernews",
            "agent_name": "hackernews_v2",
            "reddit_post_id": str(item["id"]),
            "subreddit_name": "hackernews",
            "title": item.get("title", ""),
            "body": item.get("text", ""),
            "body_excerpt": (item.get("text") or "")[:1200],
            "permalink": f"https://news.ycombinator.com/item?id={item['id']}",
            "author": item.get("by", ""),
            "post_created_at": post_created,
            "upvotes": item.get("score", 0),
            "comments_count": item.get("descendants", 0),
            "score": score_result.relevance_score,
            "semantic_similarity": score_result.semantic_similarity,
            "matched_keywords": score_result.matched_keywords,
            "intent": score_result.intent,
            "reason_relevant": score_result.reason_relevant,
            "risk_flags": score_result.risk_flags,
            "rejection_reason": score_result.rejection_reason,
            "status": "new",
        }


# ── Module-level helpers ─────────────────────────────────────────────


def _jsonb_to_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []
