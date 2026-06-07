"""LinkedIn Agent — manual content generation mode (no live API fetching).

Since LinkedIn's free API has tight rate limits and unreliable access, this agent
generates helpful content drafts for the user to post manually on LinkedIn.
It pulls from the company profile, brand keywords, existing opportunities,
and founder/product angles.
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
    "founder_story",
    "educational",
    "case_study",
    "product_update",
    "pain_point",
    "comparison",
    "carousel",
    "comment_reply",
]


@dataclass
class AgentRunResult:
    items_fetched: int = 0
    items_kept: int = 0
    items_rejected: int = 0
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


class LinkedInAgent:
    """Manual-mode LinkedIn content generation agent."""

    def __init__(self) -> None:
        self._llm = LLMClient()

    def run(
        self,
        company_id: int,
        db: Client,
        config: dict[str, Any],
    ) -> AgentRunResult:
        """Execute a manual-mode LinkedIn content generation run."""
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
                "agent_name": "linkedin_manual",
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
                            "platform": "linkedin",
                            "agent_name": "linkedin_manual",
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
                result.logs.append(f"Stored {len(stored)} LinkedIn content drafts")

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
            logger.exception("LinkedInAgent run failed")
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
        """Generate a LinkedIn post draft for a content idea.

        Args:
            idea: The content idea / angle.
            company_profile: Company profile dict.
            content_type: One of founder_story, educational, case_study,
                product_update, pain_point, comparison, carousel, comment_reply.

        Returns:
            Dict with keys: title, content, rationale, hashtags, content_type.
        """
        system_prompt = (
            "You are an expert LinkedIn content strategist. "
            "Generate a post draft in JSON format. Return ONLY valid JSON with no markdown formatting. "
            "Tone: professional, specific, human, no generic motivational nonsense."
        )
        user_content = self._build_llm_prompt(idea, company_profile, content_type)

        try:
            response = self._llm.call(system_prompt, user_content, temperature=0.6)
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
        draft.setdefault("content", idea[:1500])
        draft.setdefault("rationale", "Generated from brand profile")
        draft.setdefault("hashtags", [])
        draft.setdefault("content_type", content_type)
        return draft

    def get_monitoring_queries(self, company_profile: dict[str, Any]) -> list[str]:
        """Return LinkedIn search queries for manual monitoring.

        Args:
            company_profile: Company profile dict.

        Returns:
            List of LinkedIn search query strings.
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
                queries.append(f'{kw} in posts')

        for comp in competitors[:3]:
            if comp:
                queries.append(f'"{comp}" in posts')

        if brand_name:
            queries.append(f'"{brand_name}" in posts')

        if category:
            queries.append(f'"{category}" in posts')

        for pp in pain_points[:2]:
            if pp:
                queries.append(f'"{pp}" in posts')

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
        """Generate LinkedIn content ideas from brand data and existing opportunities."""
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
            _add(f"3 mistakes {target_audience or 'teams'} make with {pp} — and how to avoid them.")

        # SEO / article topics
        try:
            result = (
                db.table("opportunities")
                .select("*")
                .eq("project_id", project_id)
                .eq("platform", "seo")
                .eq("opportunity_type", "keyword_gap")
                .execute()
            )
            for opp in result.data[:2]:
                title = opp.get("title", "")
                if title:
                    kw = title.replace("Missing content for keyword: ", "").strip()
                    if kw:
                        _add(f"We wrote about {kw}. Here's the TL;DR for busy {target_audience or 'leaders'}.")
        except Exception as exc:
            logger.warning("Failed to fetch SEO gaps: %s", exc)

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
                        _add(f"We noticed people asking about {topic} this week. Here's our take.")
                        seen_topics.add(topic)
        except Exception as exc:
            logger.warning("Failed to fetch community questions: %s", exc)

        # Founder story
        if brand_name:
            _add(f"Why I quit my previous role to build {brand_name}.")
            _add(f"The moment I knew {brand_name} was worth the risk.")

        # Use case
        if target_audience and brand_name:
            _add(f"How {target_audience} uses {brand_name} to cut costs and save time.")

        # Customer problem
        if category:
            _add(f"The #1 problem in {category} nobody talks about (and how we're fixing it).")

        # Product features
        for feat in features[:2]:
            _add(f"We just shipped {feat}. Here's what changed for our customers.")

        # Competitor comparison
        for comp in competitors[:2]:
            _add(f"{comp} vs {brand_name}: an honest comparison from someone who's used both.")

        # Brand keywords
        for kw in brand_keywords[:3]:
            term = kw.get("keyword", "")
            if term:
                _add(f"The real reason most {term} strategies fail — and the one that doesn't.")

        return ideas

    @staticmethod
    def _build_llm_prompt(
        idea: str,
        company_profile: dict[str, Any],
        content_type: str,
    ) -> str:
        """Build the LLM prompt for a specific LinkedIn content type."""
        brand_name = company_profile.get("name", "")
        audience = company_profile.get("target_audience", "")
        category = company_profile.get("category", "")

        type_instructions = {
            "founder_story": (
                "Write a personal founder story. Be vulnerable, specific, and honest. "
                "Share a real moment or failure. No generic 'hustle culture' advice. "
                "200-400 words."
            ),
            "educational": (
                "Write an educational post that teaches something useful. Use data or a concrete example. "
                "Structure: hook, insight, actionable takeaway. 150-300 words."
            ),
            "case_study": (
                "Write a mini case study: problem, approach, result. "
                "Be specific with numbers or outcomes. 200-350 words."
            ),
            "product_update": (
                "Write a product update post. Focus on the customer impact, not the feature list. "
                "Why does this matter? 150-250 words."
            ),
            "pain_point": (
                "Write a pain-point post. Name a hidden cost or frustration in the industry. "
                "Offer a contrarian or better approach. 150-300 words."
            ),
            "comparison": (
                "Write an honest comparison post. Be fair to competitors, but clear about your differentiation. "
                "Back claims with specifics. 200-350 words."
            ),
            "carousel": (
                "Write a carousel outline: 5-7 slides with a punchy title for each. "
                "First slide is the hook, last slide is the CTA."
            ),
            "comment_reply": (
                "Write a helpful comment reply to a hypothetical LinkedIn post. "
                "Add depth, ask a follow-up question, or share a specific resource. "
                "Under 100 words."
            ),
        }

        instruction = type_instructions.get(content_type, type_instructions["educational"])

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
            '- "rationale" (why this works for LinkedIn)\n'
            '- "hashtags" (list of 3-5 relevant hashtags, no # symbol)'
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
        audience = company_profile.get("target_audience", "professionals")

        if content_type == "founder_story":
            content = (
                f"Three years ago, I walked away from a stable job to build {brand_name}.\n\n"
                f"Everyone said I was crazy. The first 6 months proved them right — "
                f"we had no customers, a broken prototype, and a team of two.\n\n"
                f"But one conversation changed everything. A {audience} told us exactly "
                f"what was missing. We rebuilt around that feedback.\n\n"
                f"Today, {brand_name} helps hundreds of {audience} every week.\n\n"
                f"The lesson? Listen before you scale."
            )
        elif content_type == "educational":
            content = (
                f"Most {category or 'teams'} focus on the wrong metric.\n\n"
                f"They chase vanity numbers instead of the one signal that actually predicts revenue: "
                f"speed to value.\n\n"
                f"At {brand_name}, we measured 200 onboarding flows. The top 10% had one thing in common — "
                f"users got to their first win in under 5 minutes.\n\n"
                f"Here's how to find your 5-minute moment:\n"
                f"1. Map the first action that delivers real value\n"
                f"2. Remove every step before it\n"
                f"3. Measure time-to-outcome, not time-to-login\n\n"
                f"Small change. Big impact."
            )
        elif content_type == "case_study":
            content = (
                f"How a 12-person {category or 'team'} cut reporting time by 70% using {brand_name}.\n\n"
                f"Problem: Weekly reports took 6 hours. Data lived in 4 tools.\n\n"
                f"Approach: We connected their stack and built one automated view.\n\n"
                f"Result: Reports now take under 2 hours. The ops lead got her Fridays back.\n\n"
                f"The best part? It took one afternoon to set up.\n\n"
                f"Sometimes the biggest wins come from removing work, not adding more."
            )
        elif content_type == "product_update":
            content = (
                f"We just shipped a small update to {brand_name} that makes a big difference.\n\n"
                f"You can now export reports directly to CSV — no copy-paste, no formatting headaches.\n\n"
                f"Why this matters: our users told us they spend 30+ minutes formatting spreadsheets every week. "
                f"This cuts that to zero.\n\n"
                f"It's not the flashiest feature we've built. But it's the one that saves real time.\n\n"
                f"What small friction should we remove next? Let me know in the comments."
            )
        elif content_type == "pain_point":
            content = (
                f"The hidden cost of {category or 'outdated workflows'} isn't the tool. It's the context switching.\n\n"
                f"Every time your team switches apps, they lose 23 minutes of focus. "
                f"Do that 5 times a day and you've lost 2 hours.\n\n"
                f"We built {brand_name} because we were tired of paying that tax.\n\n"
                f"One workspace. One source of truth. One place to get work done.\n\n"
                f"If your team uses more than 4 tools daily, you're probably feeling this."
            )
        elif content_type == "comparison":
            content = (
                f"I've used both {brand_name} and the leading alternative. Here's the honest difference.\n\n"
                f"The competitor is powerful — no doubt. But power without speed becomes complexity.\n\n"
                f"{brand_name} trades some advanced features for a setup time under 10 minutes.\n\n"
                f"If you're a {audience} who needs to move fast, that's the tradeoff that matters.\n\n"
                f"If you need enterprise-grade compliance and a 6-month implementation, go with the incumbent.\n\n"
                f"Choose the tool that fits your timeline, not your ambition."
            )
        elif content_type == "carousel":
            content = (
                f"Slide 1: The #1 mistake {audience} make with {category or 'their workflow'}\n"
                f"Slide 2: It costs more than you think (time + morale)\n"
                f"Slide 3: The fix is simpler than you expect\n"
                f"Slide 4: 3 steps to implement this week\n"
                f"Slide 5: Real result from a team that tried it\n"
                f"Slide 6: How {brand_name} handles the heavy lifting\n"
                f"Slide 7: Save this post + try step 1 today"
            )
        elif content_type == "comment_reply":
            content = (
                f"Great post. From our work with {audience}, the teams that scale fastest "
                f"are the ones that document decisions — not just outcomes. "
                f"We built a lightweight decision log into {brand_name} and it changed how our customers review work. "
                f"Happy to share the template if useful."
            )
        else:
            content = (
                f"{idea[:200]}\n\n"
                f"At {brand_name}, we've seen that the teams who win are the ones "
                f"who make small, consistent improvements. What's one change you've made this quarter "
                f"that paid off?"
            )

        return {
            "title": idea[:120],
            "content": content,
            "rationale": f"Fallback template for {content_type}",
            "hashtags": [category.replace(" ", "")] if category else ["leadership", "strategy"],
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
