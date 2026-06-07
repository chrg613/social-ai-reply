"""Reddit Agent v2 — replaces the old scanner with a platform-aware pipeline.

Steps:
1. Build search queries from Brand Brain (company profile + brand keywords).
2. Fetch candidate posts via RedditDiscoveryService.
3. Normalize and deduplicate (by URL + title cosine similarity).
4. Run RelevanceEngine v2 scoring.
5. Generate reply drafts for kept opportunities.
6. Bulk store results and update agent_runs record.
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
    list_monitored_subreddits_for_project,
    update_opportunity,
)
from app.db.tables.sources import list_sources_for_company_and_platform
from app.services.infrastructure.embeddings.service import EmbeddingService
from app.services.product.copilot._facade import ProductCopilot
from app.services.product.reddit_discovery import RedditDiscoveryService
from app.services.product.relevance import normalize_phrase
from app.services.product.relevance_v2 import CandidatePost, RelevanceEngine

if TYPE_CHECKING:
    from supabase import Client

    from app.services.product.reddit import RedditPost

logger = logging.getLogger(__name__)

_MAX_REJECTED_PER_RUN = 50
_TITLE_SIMILARITY_THRESHOLD = 0.9


@dataclass
class AgentRunResult:
    items_fetched: int = 0
    items_kept: int = 0
    items_rejected: int = 0
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


class RedditAgent:
    """Platform-aware Reddit discovery agent."""

    def __init__(self) -> None:
        self._reddit = RedditDiscoveryService()
        self._copilot = ProductCopilot()
        self._embedding = EmbeddingService()

    def run(
        self,
        company_id: int,
        project_id: int,
        db: Client,
        config: dict[str, Any],
    ) -> AgentRunResult:
        """Execute a full Reddit discovery and drafting run."""
        result = AgentRunResult()
        started_at = datetime.now(UTC)
        search_window_days = config.get("search_window_days", 7)
        min_score = config.get("min_score", 60)
        draft_mode = config.get("draft_mode", "helpful_no_pitch")
        max_results_per_query = config.get("max_results_per_query", 25)

        # ── 1. Load Brand Brain ──────────────────────────────────────
        company = get_company_by_id(db, company_id)
        if not company:
            result.logs.append(f"ERROR: Company {company_id} not found")
            return result

        brand_keywords = list_brand_keywords_for_company(db, company_id, enabled_only=True)
        if not brand_keywords:
            result.logs.append(f"WARNING: No enabled brand keywords for company {company_id}")

        # Sort by weight descending, take top 10 per type, max 20 total
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
        top_keywords = top_keywords[:20]

        # Map to RelevanceEngine expected shape
        relevance_keywords = [
            {"keyword": kw["keyword"], "type": kw.get("type", "core"), "weight": kw.get("weight", 1.0)}
            for kw in top_keywords
        ]

        # Build brand_profile dict for RelevanceEngine
        brand_profile = self._build_brand_profile(company)

        # Build search queries
        search_queries = self._build_search_queries(top_keywords)
        result.logs.append(f"Built {len(search_queries)} search queries from {len(top_keywords)} keywords")

        # ── 2. Create agent run record ─────────────────────────────────
        run = create_agent_run(db, {
            "company_id": company_id,
            "agent_name": "reddit_v2",
            "status": "running",
            "started_at": started_at.isoformat(),
        })
        run_id = run["id"]

        try:
            # ── 3. Fetch candidates ────────────────────────────────────
            candidates: list[RedditPost] = []
            cutoff = started_at - timedelta(days=search_window_days)

            # A. Search each query via discovery service
            for query in search_queries:
                try:
                    posts = self._reddit.search_posts(
                        keywords=[query],
                        subreddits=None,
                        limit=max_results_per_query,
                    )
                    result.logs.append(f"Query '{query[:60]}' returned {len(posts)} posts")
                    candidates.extend(posts)
                except Exception as exc:
                    msg = f"Search failed for query '{query[:60]}': {type(exc).__name__}: {exc}"
                    logger.warning(msg)
                    result.logs.append(msg)
                # Respect existing throttling in reddit_discovery.py (handled internally)
                time.sleep(0.5)

            # B. Fetch from configured subreddits / sources
            subreddits = list_monitored_subreddits_for_project(db, project_id)
            active_subreddits = [s for s in subreddits if s.get("is_active", True)]
            sources = list_sources_for_company_and_platform(db, company_id, "reddit")
            active_sources = [s for s in sources if s.get("status", "active") == "active"]

            # Merge explicit subreddit names from both tables
            explicit_subs: set[str] = set()
            for s in active_subreddits:
                explicit_subs.add(str(s["name"]).strip().lower())
            for s in active_sources:
                explicit_subs.add(str(s.get("source_name", "")).strip().lower())

            for sub_name in explicit_subs:
                try:
                    feed_posts = self._reddit.list_subreddit_posts(sub_name, sort="new", limit=max_results_per_query)
                    result.logs.append(f"r/{sub_name} feed returned {len(feed_posts)} posts")
                    candidates.extend(feed_posts)
                except Exception as exc:
                    msg = f"Feed failed for r/{sub_name}: {type(exc).__name__}: {exc}"
                    logger.warning(msg)
                    result.logs.append(msg)

            # ── 4. Normalize and deduplicate ───────────────────────────
            deduped = self._normalize_and_deduplicate(candidates, cutoff)
            result.items_fetched = len(deduped)
            result.logs.append(f"After deduplication: {len(deduped)} unique candidates")

            # ── 5. Run relevance engine ────────────────────────────────
            engine = RelevanceEngine(relevance_threshold=min_score)
            kept_opportunities: list[dict[str, Any]] = []
            rejected_count = 0

            for post in deduped:
                candidate = CandidatePost(
                    title=post.title,
                    body=post.body,
                    platform="reddit",
                    source_name=post.subreddit,
                    upvotes=post.score,
                    comments_count=post.num_comments,
                    created_at=post.created_at,
                    author=post.author,
                    post_url=post.permalink,
                )
                score_result = engine.score(candidate, brand_profile, relevance_keywords)

                if score_result.should_keep:
                    opp = self._build_opportunity(
                        post=post,
                        project_id=project_id,
                        company_id=company_id,
                        score_result=score_result,
                    )
                    kept_opportunities.append(opp)
                else:
                    rejected_count += 1
                    if rejected_count <= _MAX_REJECTED_PER_RUN:
                        result.logs.append(
                            f"REJECTED '{post.title[:60]}': {score_result.rejection_reason}"
                        )

            result.items_kept = len(kept_opportunities)
            result.items_rejected = rejected_count
            result.logs.append(f"Relevance engine: {len(kept_opportunities)} kept, {rejected_count} rejected")

            # ── 6. Generate drafts ─────────────────────────────────────
            for opp in kept_opportunities:
                try:
                    draft = self.generate_draft(opp, brand_profile, mode=draft_mode)
                    opp["draft_reply"] = draft
                    opp["reason_relevant"] = opp.get("reason_relevant", "")
                except Exception as exc:
                    logger.warning("Draft generation failed for opp %s: %s", opp.get("title", ""), exc)
                    result.logs.append(f"Draft generation failed: {exc}")

            # ── 7. Store results ───────────────────────────────────────
            stored: list[dict[str, Any]] = []
            if kept_opportunities:
                # Check for existing opportunities to avoid overwriting
                new_opps: list[dict[str, Any]] = []
                updated = 0
                for opp in kept_opportunities:
                    existing = get_opportunity_by_project_and_reddit_post(
                        db, project_id, opp.get("reddit_post_id", "")
                    )
                    if existing:
                        # Update with new scores and draft if status allows
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

            # ── 8. Finalize agent run ────────────────────────────────────
            update_agent_run(db, run_id, {
                "status": "completed",
                "items_fetched": result.items_fetched,
                "items_kept": result.items_kept,
                "items_rejected": result.items_rejected,
                "finished_at": datetime.now(UTC).isoformat(),
                "logs_json": result.logs,
            })
        except Exception as exc:
            logger.exception("RedditAgent run failed")
            result.logs.append(f"FATAL ERROR: {type(exc).__name__}: {exc}")
            update_agent_run(db, run_id, {
                "status": "error",
                "error_message": str(exc)[:500],
                "finished_at": datetime.now(UTC).isoformat(),
                "logs_json": result.logs,
            })

        return result

    def generate_draft(
        self,
        opportunity: dict[str, Any],
        company_profile: dict[str, Any],
        mode: str = "helpful_no_pitch",
    ) -> str:
        """Generate a reply draft for a kept opportunity.

        Modes:
        - helpful_no_pitch: answer helpfully, no product mention
        - soft_mention: mention product only if genuinely relevant
        - founder_disclosure: mention you're the founder / team member
        - educational_only: pure educational value, no pitch
        """
        # Build a minimal brand dict compatible with ProductCopilot
        brand = {
            "brand_name": company_profile.get("name", ""),
            "summary": company_profile.get("description", ""),
            "voice_notes": company_profile.get("brand_voice", ""),
            "call_to_action": company_profile.get("preferred_cta", ""),
        }

        # Enrich opportunity with mode context so the copilot can adapt tone
        opp_for_copilot = dict(opportunity)
        opp_for_copilot["reply_mode"] = mode
        opp_for_copilot["subreddit"] = opportunity.get("subreddit_name", "")

        # Try ProductCopilot first (uses LLM)
        try:
            prompts = []  # No custom prompts for now; copilot uses default system prompt
            content, rationale, _source = self._copilot.generate_reply(opp_for_copilot, brand, prompts)
            if content:
                return content
        except Exception as exc:
            logger.warning("ProductCopilot draft generation failed: %s", exc)

        # Fallback: simple template
        return self._fallback_draft(opportunity, company_profile, mode)

    # ── Internal helpers ───────────────────────────────────────────────

    @staticmethod
    def _build_brand_profile(company: dict[str, Any]) -> dict[str, Any]:
        """Map company_profiles row to RelevanceEngine brand_profile shape."""
        return {
            "name": company.get("name", ""),
            "description": company.get("description", ""),
            "category": company.get("category", ""),
            "target_audience": company.get("target_audience", ""),
            "pain_points": _jsonb_to_list(company.get("pain_points")),
            "competitors": _jsonb_to_list(company.get("competitors")),
            "key_benefits": " ".join(_jsonb_to_list(company.get("benefits"))),
        }

    @staticmethod
    def _build_search_queries(keywords: list[dict[str, Any]]) -> list[str]:
        """Generate Reddit-specific search queries from top keywords."""
        queries: list[str] = []
        seen: set[str] = set()
        for kw in keywords:
            if len(queries) >= 15:
                break
            term = str(kw.get("keyword", "")).strip()
            if not term or len(term) < 3:
                continue
            # Skip queries that are too long or look like sentences
            if len(term.split()) > 5:
                continue
            # site query
            site_q = f"site:reddit.com {term}"
            if site_q not in seen:
                queries.append(site_q)
                seen.add(site_q)
        return queries

    def _normalize_and_deduplicate(
        self,
        posts: list[RedditPost],
        cutoff: datetime,
    ) -> list[RedditPost]:
        """Normalize text, filter by age, dedupe by URL and title similarity."""
        # Filter by cutoff and normalize
        filtered: list[RedditPost] = []
        for post in posts:
            if post.created_at is not None:
                post_dt = post.created_at if post.created_at.tzinfo else post.created_at.replace(tzinfo=UTC)
                if post_dt < cutoff:
                    continue
            filtered.append(post)

        # Deduplicate by permalink
        by_url: dict[str, RedditPost] = {}
        for post in filtered:
            key = post.permalink.strip().lower()
            if not key:
                continue
            existing = by_url.get(key)
            if existing is None or post.score > existing.score:
                by_url[key] = post

        unique_posts = list(by_url.values())

        # Deduplicate by title similarity (keep highest-scored)
        embeddings: dict[str, list[float]] = {}
        titles = [normalize_phrase(p.title) for p in unique_posts]
        if titles:
            try:
                embs = self._embedding.embed_batch(titles)
                for p, emb in zip(unique_posts, embs, strict=False):
                    embeddings[id(p)] = emb
            except Exception as exc:
                logger.warning("Embedding batch failed during dedup: %s", exc)

        kept: list[RedditPost] = []
        for post in unique_posts:
            emb_a = embeddings.get(id(post))
            if emb_a is None:
                kept.append(post)
                continue
            is_dup = False
            for other in kept:
                emb_b = embeddings.get(id(other))
                if emb_b is None:
                    continue
                try:
                    sim = self._embedding.cosine_similarity(emb_a, emb_b)
                except Exception:
                    continue
                if sim > _TITLE_SIMILARITY_THRESHOLD:
                    is_dup = True
                    if post.score > other.score:
                        # Replace other with this higher-scored post
                        kept.remove(other)
                        kept.append(post)
                    break
            if not is_dup:
                kept.append(post)

        return kept

    @staticmethod
    def _build_opportunity(
        post: RedditPost,
        project_id: int,
        company_id: int,
        score_result: Any,
    ) -> dict[str, Any]:
        """Build an opportunity row from a scored Reddit post."""
        created_utc = post.created_at.isoformat() if post.created_at else None
        return {
            "project_id": project_id,
            "platform": "reddit",
            "agent_name": "reddit_v2",
            "reddit_post_id": post.post_id,
            "subreddit_name": post.subreddit,
            "title": post.title,
            "body": post.body,
            "body_excerpt": post.body[:1200],
            "permalink": post.permalink,
            "author": post.author,
            "post_created_at": created_utc,
            "upvotes": post.score,
            "comments_count": post.num_comments,
            "score": score_result.relevance_score,
            "semantic_similarity": score_result.semantic_similarity,
            "matched_keywords": score_result.matched_keywords,
            "intent": score_result.intent,
            "reason_relevant": score_result.reason_relevant,
            "risk_flags": score_result.risk_flags,
            "rejection_reason": score_result.rejection_reason,
            "status": "new",
        }

    @staticmethod
    def _fallback_draft(
        opportunity: dict[str, Any],
        company_profile: dict[str, Any],
        mode: str,
    ) -> str:
        """Template-based fallback draft when LLM is unavailable."""
        title = opportunity.get("title", "")
        body = opportunity.get("body_excerpt", "")[:400]
        brand_name = company_profile.get("name", "our product")

        if mode == "founder_disclosure":
            return (
                f"Hey — I saw your post about '{title[:80]}'. "
                f"I'm the founder of {brand_name}, and this is exactly the problem we built it to solve. "
                f"Here's what I'd suggest based on our experience..."
            )
        if mode == "soft_mention":
            return (
                f"Great question. From what I've seen, {brand_name} might be worth looking into for this. "
                f"It handles {body[:120]}... Hope that helps!"
            )
        if mode == "educational_only":
            return (
                f"Here are a few things that typically work well for '{title[:80]}':\n\n"
                f"1. ...\n2. ...\n3. ...\n\n"
                f"Feel free to ask if you want more detail."
            )
        # helpful_no_pitch (default)
        return (
            f"I saw your post about '{title[:80]}'. "
            f"Here are a few thoughts that might help:\n\n"
            f"• ...\n• ...\n• ...\n\n"
            f"Hope that gives you a useful starting point."
        )


# ── Module-level helpers ─────────────────────────────────────────────


def _jsonb_to_list(value: Any) -> list[str]:
    """Coerce a JSONB column value to a list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []


def _guess_subreddit(keyword_type: str) -> str:
    """Naive subreddit guess for query-building purposes."""
    mapping = {
        "core": "technology",
        "pain_point": "startups",
        "problem": "entrepreneur",
        "feature": "saas",
    }
    return mapping.get(keyword_type, "technology")
