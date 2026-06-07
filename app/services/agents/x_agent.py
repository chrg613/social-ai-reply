"""X/Twitter Agent — manual content generation mode (no live API fetching).

Since the X free API is unreliable, this agent generates helpful content drafts
for the user to post manually on X. It pulls from the company profile, brand
keywords, existing Reddit/HN opportunities, and competitor angles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.db.tables.agent_runs import create_agent_run, update_agent_run
from app.db.tables.brand_keywords import list_brand_keywords_for_company
from app.db.tables.company import get_company_by_id
from app.db.tables.discovery import bulk_create_opportunities
from app.db.tables.projects import list_projects_for_workspace
from app.services.product.copilot.llm_client import LLMClient

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)

_CONTENT_TYPES = [
    "reply",
    "quote",
    "original",
    "thread",
    "founder_update",
    "product_tip",
    "pain_point",
]


@dataclass
class AgentRunResult:
    items_fetched: int = 0
    items_kept: int = 0
    items_rejected: int = 0
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


class XAgent:
    """Manual-mode X/Twitter content generation agent."""

    def __init__(self) -> None:
        self._llm = LLMClient()

    def run(
        self,
        company_id: int,
        db: Client,
        config: dict[str, Any],
    ) -> AgentRunResult:
        """Execute a manual-mode X content generation run."""
        result = AgentRunResult()
        started_at = datetime.now(UTC)
        max_drafts = config.get("max_drafts", 12)

        project_id = _get_project_id_for_company(db, company_id, config)
        if not project_id:
            result.logs.append(f"ERROR: No project found for company {company_id}")
            return result

        company = get_company_by_id(db, company_id)
        if not company:
            result.logs.append(f"ERROR: Company {company_id} not found")
            return result

        brand_keywords = list_brand_keywords_for_company(db, company_id, enabled_only=True)

        run = create_agent_run(
            db,
            {
                "company_id": company_id,
                "agent_name": "x_manual",
                "status": "running",
                "started_at": started_at.isoformat(),
            },
        )
        run_id = run["id"]

        try:
            # Collect content ideas from brand data + existing opportunities
            ideas = self._collect_content_ideas(db, project_id, company, brand_keywords)
            result.items_fetched = len(ideas)
            result.logs.append(f"Generated {len(ideas)} content ideas")

            # Generate drafts for each idea (cycle through content types)
            opportunities: list[dict] = []
            for idx, idea in enumerate(ideas[:max_drafts]):
                content_type = _CONTENT_TYPES[idx % len(_CONTENT_TYPES)]
                try:
                    draft = self.generate_post_draft(idea, company, content_type)
                    opportunities.append(
                        {
                            "project_id": project_id,
                            "platform": "x",
                            "agent_name": "x_manual",
                            "opportunity_type": "content_draft",
                            "title": draft["title"],
                            "body": draft["content"],
                            "draft_post": draft["content"],
                            "score": 90 + min(idx, 9),
                            "status": "new",
                            "reason_relevant": draft["rationale"],
                            "matched_keywords": draft.get("hashtags", []),
                        }
                    )
                    result.logs.append(f"Draft: {draft['title'][:60]} ({content_type})")
                except Exception as exc:
                    logger.warning("Draft generation failed for %s: %s", idea, exc)
                    result.logs.append(f"Draft generation failed: {exc}")

            result.items_kept = len(opportunities)

            if opportunities:
                stored = bulk_create_opportunities(db, opportunities)
                result.opportunities = stored
                result.logs.append(f"Stored {len(stored)} X content drafts")

            update_agent_run(
                db,
                run_id,
                {
                    "status": "completed",
                    "items_fetched": result.items_fetched,
                    "items_kept": result.items_kept,
                    "items_rejected": result.items_rejected,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "logs_json": result.logs,
                },
            )
        except Exception as exc:
            logger.exception("XAgent run failed")
            result.logs.append(f"FATAL ERROR: {type(exc).__name__}: {exc}")
            update_agent_run(
                db,
                run_id,
                {
                    "status": "error",
                    "error_message": str(exc)[:500],
                    "finished_at": datetime.now(UTC).isoformat(),
                    "logs_json": result.logs,
                },
            )

        return result

    def generate_post_draft(
        self,
        idea: str,
        company_profile: dict[str, Any],
        content_type: str,
    ) -> dict[str, Any]:
        """Generate an X post draft for a content idea.

        Args:
            idea: The content idea / angle.
            company_profile: Company profile dict.
            content_type: One of reply, quote, original, thread, founder_update,
                product_tip, pain_point.

        Returns:
            Dict with keys: title, content, rationale, hashtags, content_type.
        """
        system_prompt = (
            "You are an expert X/Twitter content strategist. "
            "Generate a post draft in JSON format. Return ONLY valid JSON with no markdown formatting. "
            "Keep the tone concise, punchy, and conversational."
        )
        user_content = self._build_llm_prompt(idea, company_profile, content_type)

        try:
            response = self._llm.call(system_prompt, user_content, temperature=0.7)
            if isinstance(response, dict):
                draft = response
            elif isinstance(response, list) and response:
                draft = response[0]
            else:
                draft = {}
            if not isinstance(draft, dict) or not draft.get("content"):
                draft = self._fallback_draft(idea, company_profile, content_type)
        except Exception as exc:
            logger.warning("LLM draft generation failed: %s", exc)
            draft = self._fallback_draft(idea, company_profile, content_type)

        draft.setdefault("title", idea[:120])
        draft.setdefault("content", idea[:280])
        draft.setdefault("rationale", "Generated from brand profile")
        draft.setdefault("hashtags", [])
        draft.setdefault("content_type", content_type)
        return draft

    def get_monitoring_queries(self, company_profile: dict[str, Any]) -> list[str]:
        """Return X search queries for manual monitoring.

        Args:
            company_profile: Company profile dict.

        Returns:
            List of X search query strings.
        """
        queries: list[str] = []
        brand_name = company_profile.get("name", "")
        keywords = _jsonb_to_list(
            company_profile.get("keywords") or company_profile.get("brand_keywords", [])
        )
        competitors = _jsonb_to_list(company_profile.get("competitors", []))
        category = company_profile.get("category", "")
        pain_points = _jsonb_to_list(company_profile.get("pain_points", []))

        for kw in keywords[:5]:
            if kw:
                queries.append(f"{kw} -filter:retweets")

        for comp in competitors[:3]:
            if comp:
                handle = comp.replace(" ", "").replace("@", "")
                queries.append(f"from:{handle} {category or 'product'}")

        if brand_name:
            queries.append(f'"{brand_name}"')
            queries.append(f'to:"{brand_name}" OR @"{brand_name}"')

        for pp in pain_points[:2]:
            if pp:
                queries.append(f"{pp} -filter:retweets")

        if category:
            queries.append(f"{category} tip OR hack -filter:retweets")

        return queries[:10]

    # ── Internal helpers ───────────────────────────────────────────────

    @staticmethod
    def _build_brand_profile(company: dict[str, Any]) -> dict[str, Any]:
        """Map company_profiles row to a brand_profile dict."""
        return {
            "name": company.get("name", ""),
            "description": company.get("description", ""),
            "category": company.get("category", ""),
            "target_audience": company.get("target_audience", ""),
            "pain_points": _jsonb_to_list(company.get("pain_points")),
            "competitors": _jsonb_to_list(company.get("competitors")),
            "key_benefits": " ".join(_jsonb_to_list(company.get("benefits", []))),
        }

    def _collect_content_ideas(
        self,
        db: Client,
        project_id: int,
        company: dict[str, Any],
        brand_keywords: list[dict[str, Any]],
    ) -> list[str]:
        """Generate content ideas from brand data and existing opportunities."""
        ideas: list[str] = []
        seen: set[str] = set()
        brand_name = company.get("name", "")
        category = company.get("category", "")
        pain_points = _jsonb_to_list(company.get("pain_points", []))
        features = _jsonb_to_list(company.get("features", []))
        competitors = _jsonb_to_list(company.get("competitors", []))
        target_audience = company.get("target_audience", "")

        def _add(text: str) -> None:
            key = text.lower().strip()
            if key and key not in seen:
                ideas.append(text)
                seen.add(key)

        # Pain points
        for pp in pain_points[:3]:
            _add(f"Frustrated with {pp}? Here's what we learned building {brand_name}...")

        # Features
        for feat in features[:3]:
            _add(f"Just shipped {feat}. Here's why it matters for {target_audience or 'our users'}...")

        # Existing community insights
        try:
            result = (
                db.table("opportunities")
                .select("*")
                .eq("project_id", project_id)
                .in_("platform", ["reddit", "hackernews"])
                .execute()
            )
            seen_topics: set[str] = set()
            for opp in result.data:
                title = opp.get("title", "")
                if title and len(seen_topics) < 3:
                    topic = title.split("?")[0].split(".")[0][:60]
                    if topic not in seen_topics:
                        _add(f"We saw people asking about {topic} this week. Here's our take...")
                        seen_topics.add(topic)
        except Exception as exc:
            logger.warning("Failed to fetch existing opportunities: %s", exc)

        # Competitor angles
        for comp in competitors[:2]:
            _add(f"Why we built {brand_name} after {comp} failed us...")

        # Industry trend + product angle
        if category:
            _add(f"The biggest shift in {category} this year — and what we're doing about it.")
            _add(f"3 {category} myths that still cost people money (and how to avoid them).")

        # Brand keywords
        for kw in brand_keywords[:3]:
            term = kw.get("keyword", "")
            if term:
                _add(f"Quick tip: the easiest way to improve {term} without spending a dime.")

        # Founder update
        if brand_name:
            _add(f"We just hit a milestone with {brand_name}. Here's what we learned this month...")

        return ideas

    @staticmethod
    def _build_llm_prompt(
        idea: str,
        company_profile: dict[str, Any],
        content_type: str,
    ) -> str:
        """Build the LLM prompt for a specific content type."""
        brand_name = company_profile.get("name", "")
        audience = company_profile.get("target_audience", "")
        category = company_profile.get("category", "")

        type_instructions = {
            "reply": (
                "Write a concise, helpful reply to a hypothetical post. "
                "Add value, don't pitch. Under 280 chars if possible."
            ),
            "quote": (
                "Write a quote-post: quote a hypothetical statement, then add "
                "your commentary. Punchy and opinionated."
            ),
            "original": (
                "Write a standalone original post: strong hook + value + soft CTA. "
                "Make it scroll-stopping."
            ),
            "thread": (
                "Write a 3-5 tweet thread. Provide a numbered list inside the thread. "
                "Each tweet under 280 chars."
            ),
            "founder_update": (
                "Write a founder update. Be vulnerable, specific, and share a real lesson. "
                "No generic motivational fluff."
            ),
            "product_tip": (
                "Write a quick, actionable product tip. Something the reader can try today. "
                "Specific steps, not vague advice."
            ),
            "pain_point": (
                "Write a pain-point post. Call out a common mistake in the industry, "
                "then offer a contrarian or better way."
            ),
        }

        instruction = type_instructions.get(content_type, type_instructions["original"])

        return (
            f"Idea: {idea}\n"
            f"Brand: {brand_name}\n"
            f"Audience: {audience}\n"
            f"Category: {category}\n"
            f"Content type: {content_type}\n"
            f"Instruction: {instruction}\n\n"
            "Return JSON with these fields:\n"
            '- "title" (short headline)\n'
            '- "content" (the full post text)\n'
            '- "rationale" (why this works)\n'
            '- "hashtags" (list of 2-4 relevant hashtags, no # symbol)'
        )

    @staticmethod
    def _fallback_draft(
        idea: str,
        company_profile: dict[str, Any],
        content_type: str,
    ) -> dict[str, Any]:
        """Template-based fallback when LLM is unavailable."""
        brand_name = company_profile.get("name", "our product")
        category = company_profile.get("category", "")

        if content_type == "reply":
            content = (
                f"Great point. From our experience at {brand_name}, "
                f"the thing that moves the needle is execution, not theory. "
                f"Happy to share specifics if helpful."
            )
        elif content_type == "quote":
            content = (
                f'"{idea[:100]}"\n\n'
                f"This is exactly why we built {brand_name}. "
                f"The gap between advice and action is where real value lives."
            )
        elif content_type == "thread":
            content = (
                f"1/ {idea[:120]}\n\n"
                f"2/ Most people overthink this. Start small, measure, iterate.\n\n"
                f"3/ At {brand_name}, we see the best results when teams focus on one metric.\n\n"
                f"4/ If you're struggling with {category or 'this'}, reply and I'll share a framework."
            )
        elif content_type == "founder_update":
            content = (
                f"We just shipped something at {brand_name} that we've been testing for 3 months. "
                f"The biggest surprise? Customers cared less about the feature and more about speed. "
                f"Lesson: talk to users before you build."
            )
        elif content_type == "product_tip":
            content = (
                f"Quick tip: if you use {brand_name}, try setting a 24-hour review cycle. "
                f"It cuts decision lag by half. That's it. That's the tip."
            )
        elif content_type == "pain_point":
            content = (
                f"The biggest mistake I see in {category or 'this space'}: "
                f"chasing trends instead of fixing fundamentals. "
                f"Build a boring system that works before you chase a shiny tactic."
            )
        else:  # original
            content = (
                f"{idea[:200]}\n\n"
                f"At {brand_name}, we've learned that consistency beats intensity. "
                f"What's one small habit that's moved the needle for you?"
            )

        return {
            "title": idea[:120],
            "content": content,
            "rationale": f"Fallback template for {content_type}",
            "hashtags": [category.replace(" ", "")] if category else ["startup"],
            "content_type": content_type,
        }


# ── Module-level helpers ─────────────────────────────────────────────


def _jsonb_to_list(value: Any) -> list[str]:
    """Coerce a JSONB column value to a list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []


def _get_project_id_for_company(db: Client, company_id: int, config: dict[str, Any]) -> int | None:
    """Resolve project_id from config or company/workspace."""
    project_id = config.get("project_id")
    if project_id:
        return int(project_id)
    company = get_company_by_id(db, company_id)
    if not company:
        return None
    workspace_id = company.get("workspace_id")
    if not workspace_id:
        return None
    projects = list_projects_for_workspace(db, workspace_id)
    if projects:
        return projects[0]["id"]
    return None
