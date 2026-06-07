"""Articles Agent — generates article briefs from brand data and gaps."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.db.tables.agent_runs import create_agent_run, update_agent_run
from app.db.tables.brand_keywords import list_brand_keywords_for_company
from app.db.tables.company import get_company_by_id
from app.db.tables.discovery import (
    bulk_create_opportunities,
    get_opportunity_by_id,
)
from app.db.tables.projects import list_projects_for_workspace
from app.services.product.copilot.llm_client import LLMClient

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)


@dataclass
class AgentRunResult:
    items_fetched: int = 0
    items_kept: int = 0
    items_rejected: int = 0
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


class ArticlesAgent:
    """Articles agent that generates article briefs from brand data."""

    def __init__(self) -> None:
        self._llm = LLMClient()

    def run(self, company_id: int, db: Client, config: dict[str, Any]) -> AgentRunResult:
        result = AgentRunResult()
        started_at = datetime.now(UTC)

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
                "agent_name": "articles",
                "status": "running",
                "started_at": started_at.isoformat(),
            },
        )
        run_id = run["id"]

        try:
            # Collect topics
            topics = self._collect_topics(db, project_id, company, brand_keywords)

            # Generate briefs for top topics
            max_briefs = config.get("max_briefs", 10)
            briefs: list[dict] = []
            for topic in topics[:max_briefs]:
                try:
                    brief = self.generate_brief(
                        topic=topic["title"],
                        keyword=topic["keyword"],
                        company_profile=company,
                    )
                    briefs.append(brief)
                    result.logs.append(f"Generated brief for topic: {topic['title'][:60]}")
                except Exception as exc:
                    logger.warning("Brief generation failed for %s: %s", topic.get("title", ""), exc)
                    result.logs.append(f"Brief generation failed: {exc}")

            # Build opportunities
            opportunities: list[dict] = []
            for brief in briefs:
                brief_json = json.dumps(brief, indent=2)
                opportunities.append(
                    {
                        "project_id": project_id,
                        "platform": "article",
                        "agent_name": "articles",
                        "title": brief["title"],
                        "body": brief_json[:4000],
                        "opportunity_type": "article_brief",
                        "severity": "medium",
                        "score": 95,
                        "status": "new",
                        "draft_article": brief_json,
                    }
                )

            result.items_fetched = len(topics)
            result.items_kept = len(opportunities)
            result.logs.append(
                f"Articles agent: {len(briefs)} briefs generated from {len(topics)} topics"
            )

            if opportunities:
                stored = bulk_create_opportunities(db, opportunities)
                result.opportunities = stored
                result.logs.append(f"Stored {len(stored)} opportunities")

            update_agent_run(
                db,
                run_id,
                {
                    "status": "completed",
                    "items_fetched": result.items_fetched,
                    "items_kept": result.items_kept,
                    "items_rejected": 0,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "logs_json": result.logs,
                },
            )
        except Exception as exc:
            logger.exception("ArticlesAgent run failed")
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

    def _collect_topics(
        self,
        db: Client,
        project_id: int,
        company: dict,
        brand_keywords: list[dict],
    ) -> list[dict]:
        topics: list[dict] = []
        seen: set[str] = set()

        # 1. SEO keyword gaps
        try:
            result = (
                db.table("opportunities")
                .select("*")
                .eq("project_id", project_id)
                .eq("platform", "seo")
                .eq("opportunity_type", "keyword_gap")
                .execute()
            )
            for opp in result.data:
                title = opp.get("title", "")
                if title and title not in seen:
                    topics.append(
                        {
                            "title": title,
                            "keyword": _extract_keyword_from_title(title),
                            "source": "seo_gap",
                        }
                    )
                    seen.add(title)
        except Exception as exc:
            logger.warning("Failed to fetch SEO gaps: %s", exc)

        # 2. Reddit/HN questions
        try:
            result = (
                db.table("opportunities")
                .select("*")
                .eq("project_id", project_id)
                .in_("platform", ["reddit", "hackernews"])
                .eq("intent", "asking_for_help")
                .execute()
            )
            for opp in result.data:
                title = opp.get("title", "")
                if title and title not in seen:
                    topics.append(
                        {
                            "title": title,
                            "keyword": _extract_keyword_from_title(title),
                            "source": "community_question",
                        }
                    )
                    seen.add(title)
        except Exception as exc:
            logger.warning("Failed to fetch community questions: %s", exc)

        # 3. GEO target questions
        category = company.get("category", "")
        pain_points = _jsonb_to_list(company.get("pain_points"))
        competitors = _jsonb_to_list(company.get("competitors"))
        target_audience = company.get("target_audience", "")

        if category:
            t = f"Best {category} tools for 2024"
            if t not in seen:
                topics.append({"title": t, "keyword": category, "source": "geo"})
                seen.add(t)

        for pp in pain_points[:2]:
            t = f"How to solve {pp}"
            if t not in seen:
                topics.append({"title": t, "keyword": pp, "source": "pain_point"})
                seen.add(t)

        for comp in competitors[:2]:
            t = f"Best alternatives to {comp}"
            if t not in seen:
                topics.append({"title": t, "keyword": comp, "source": "competitor"})
                seen.add(t)

        if target_audience:
            t = f"Tools for {target_audience}: a complete guide"
            if t not in seen:
                topics.append({"title": t, "keyword": target_audience, "source": "audience"})
                seen.add(t)

        # 4. Product features
        features = _jsonb_to_list(company.get("features"))
        for feat in features[:2]:
            t = f"How to use {feat}"
            if t not in seen:
                topics.append({"title": t, "keyword": feat, "source": "feature"})
                seen.add(t)

        # 5. Brand keywords (long-tail)
        for kw in brand_keywords[:5]:
            term = kw.get("keyword", "")
            if term and term not in seen:
                t = f"Complete guide to {term}"
                if t not in seen:
                    topics.append({"title": t, "keyword": term, "source": "keyword"})
                    seen.add(t)

        return topics

    def generate_brief(self, topic: str, keyword: str, company_profile: dict) -> dict:
        system_prompt = (
            "You are an expert content strategist. Generate a structured article brief in JSON format. "
            "Return ONLY valid JSON with no markdown formatting."
        )
        user_content = (
            f"Topic: {topic}\n"
            f"Target keyword: {keyword}\n"
            f"Company: {company_profile.get('name', '')}\n"
            f"Description: {company_profile.get('description', '')}\n"
            f"Category: {company_profile.get('category', '')}\n"
            f"Target audience: {company_profile.get('target_audience', '')}\n"
            f"Pain points: {', '.join(_jsonb_to_list(company_profile.get('pain_points')))}\n\n"
            "Generate an article brief with these fields:\n"
            "- title\n"
            "- target_keyword\n"
            "- search_intent (informational, transactional, navigational)\n"
            "- audience\n"
            "- angle (what makes this article unique)\n"
            "- outline (list of H2/H3 sections as strings)\n"
            "- key_points (5-7 bullet points)\n"
            "- product_mention_section (where and how to mention the product)\n"
            "- cta (call to action)\n"
            "- faq (3-5 questions with answers)\n"
            "- internal_links (suggested internal pages to link)\n"
            "- meta_title (60 chars max)\n"
            "- meta_description (160 chars max)\n"
        )

        try:
            response = self._llm.call(system_prompt, user_content, temperature=0.4)
            if isinstance(response, dict):
                brief = response
            elif isinstance(response, list) and response:
                brief = response[0]
            else:
                brief = {}
            if not isinstance(brief, dict) or not brief.get("title"):
                brief = self._fallback_brief(topic, keyword, company_profile)
        except Exception as exc:
            logger.warning("LLM brief generation failed: %s", exc)
            brief = self._fallback_brief(topic, keyword, company_profile)

        # Ensure all required fields
        brief.setdefault("title", topic)
        brief.setdefault("target_keyword", keyword)
        brief.setdefault("search_intent", "informational")
        brief.setdefault("audience", company_profile.get("target_audience", ""))
        brief.setdefault("angle", f"Practical, actionable guide for {keyword}")
        brief.setdefault(
            "outline",
            [
                f"Introduction to {keyword}",
                "Key concepts",
                "How to implement",
                "Best practices",
                "Conclusion",
            ],
        )
        brief.setdefault(
            "key_points",
            [f"Understand {keyword}", "Apply best practices", "Measure results"],
        )
        brief.setdefault(
            "product_mention_section",
            "Mention product naturally in the solution section",
        )
        brief.setdefault("cta", "Learn more or try our solution")
        brief.setdefault(
            "faq",
            [{"question": f"What is {keyword}?", "answer": "A brief explanation."}],
        )
        brief.setdefault("internal_links", ["/features", "/pricing", "/about"])
        brief.setdefault("meta_title", topic[:60])
        brief.setdefault(
            "meta_description",
            f"Learn about {keyword} and how to get started."[:160],
        )

        return brief

    @staticmethod
    def _fallback_brief(topic: str, keyword: str, company_profile: dict) -> dict:
        return {
            "title": topic,
            "target_keyword": keyword,
            "search_intent": "informational",
            "audience": company_profile.get("target_audience", ""),
            "angle": f"Practical, actionable guide for {keyword}",
            "outline": [
                f"Introduction to {keyword}",
                "Key concepts",
                "How to implement",
                "Best practices",
                "Conclusion",
            ],
            "key_points": [
                f"Understand {keyword}",
                "Apply best practices",
                "Measure results",
            ],
            "product_mention_section": "Mention product naturally in the solution section",
            "cta": "Learn more or try our solution",
            "faq": [
                {"question": f"What is {keyword}?", "answer": "A brief explanation."}
            ],
            "internal_links": ["/features", "/pricing", "/about"],
            "meta_title": topic[:60],
            "meta_description": f"Learn about {keyword} and how to get started."[:160],
        }

    def export_brief(self, opportunity_id: int, db: Client) -> str:
        opp = get_opportunity_by_id(db, opportunity_id)
        if not opp:
            return ""

        draft = opp.get("draft_article", "") or opp.get("body", "")
        try:
            brief = json.loads(draft)
        except json.JSONDecodeError:
            brief = {}

        if not isinstance(brief, dict):
            brief = {}

        lines = [
            f"# {brief.get('title', opp.get('title', 'Article Brief'))}",
            "",
            f"**Target Keyword:** {brief.get('target_keyword', '')}",
            f"**Search Intent:** {brief.get('search_intent', '')}",
            f"**Audience:** {brief.get('audience', '')}",
            f"**Angle:** {brief.get('angle', '')}",
            "",
            "## Outline",
            "",
        ]
        for section in brief.get("outline", []):
            lines.append(f"- {section}")
        lines.extend(["", "## Key Points", ""])
        for point in brief.get("key_points", []):
            lines.append(f"- {point}")
        lines.extend(["", "## Product Mention Section", brief.get("product_mention_section", "")])
        lines.extend(["", "## Call to Action", brief.get("cta", "")])
        lines.extend(["", "## FAQ", ""])
        for faq in brief.get("faq", []):
            if isinstance(faq, dict):
                lines.append(f"**Q:** {faq.get('question', '')}")
                lines.append(f"**A:** {faq.get('answer', '')}")
                lines.append("")
        lines.extend(["", "## Suggested Internal Links", ""])
        for link in brief.get("internal_links", []):
            lines.append(f"- {link}")
        lines.extend(
            [
                "",
                "## Meta",
                f"**Meta Title:** {brief.get('meta_title', '')}",
                f"**Meta Description:** {brief.get('meta_description', '')}",
            ]
        )

        return "\n".join(lines)


def _get_project_id_for_company(db: Client, company_id: int, config: dict[str, Any]) -> int | None:
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


def _extract_keyword_from_title(title: str) -> str:
    prefix = "Missing content for keyword: "
    if title.startswith(prefix):
        return title[len(prefix) :].strip()
    return title


def _jsonb_to_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []
