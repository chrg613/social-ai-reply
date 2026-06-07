"""UGC Agent — generates short video briefs from brand pain points and features."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.db.tables.agent_runs import create_agent_run, update_agent_run
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


class UGCAgent:
    """UGC agent that generates short video briefs from brand data."""

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

        run = create_agent_run(
            db,
            {
                "company_id": company_id,
                "agent_name": "ugc",
                "status": "running",
                "started_at": started_at.isoformat(),
            },
        )
        run_id = run["id"]

        try:
            # 1. Get high-performing pain points from opportunities
            pain_points = self._get_pain_points(db, project_id, company)

            # 2. Get SEO/GEO target questions
            questions = self._get_seo_geo_questions(db, project_id)

            # 3. Get product features from company profile
            features = _jsonb_to_list(company.get("features"))

            # 4. Generate 5 video brief ideas
            ideas = self._generate_ideas(pain_points, questions, features, company)
            max_briefs = config.get("max_briefs", 5)
            ideas = ideas[:max_briefs]

            result.items_fetched = len(ideas)
            result.logs.append(f"Fetched {len(pain_points)} pain points, {len(questions)} questions, {len(features)} features")

            # 5. Generate complete briefs for each idea
            briefs: list[dict] = []
            for idea in ideas:
                try:
                    brief = self.generate_brief(idea, company)
                    briefs.append(brief)
                    result.logs.append(f"Generated brief: {brief.get('hook', '')[:60]}")
                except Exception as exc:
                    logger.warning("Brief generation failed: %s", exc)
                    result.logs.append(f"Brief generation failed: {exc}")

            # 6. Store as opportunities
            opportunities: list[dict] = []
            for brief in briefs:
                brief_json = json.dumps(brief, indent=2)
                hook = brief.get("hook", "Video Brief")
                opportunities.append(
                    {
                        "project_id": project_id,
                        "platform": "ugc",
                        "agent_name": "ugc",
                        "title": hook,
                        "body": brief_json[:4000],
                        "opportunity_type": "video_brief",
                        "severity": "medium",
                        "score": 90,
                        "status": "new",
                        "draft_article": brief_json,
                    }
                )

            result.items_kept = len(opportunities)
            result.logs.append(f"UGC agent: {len(briefs)} briefs generated")

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
            logger.exception("UGCAgent run failed")
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

    def _get_pain_points(self, db: Client, project_id: int, company: dict) -> list[dict]:
        """Fetch high-performing pain points from opportunities."""
        pain_points: list[dict] = []
        seen: set[str] = set()

        try:
            result = (
                db.table("opportunities")
                .select("*")
                .eq("project_id", project_id)
                .gt("score", 80)
                .in_(
                    "intent",
                    ["pain_point_discussion", "complaining_about_competitor", "looking_for_alternative"],
                )
                .execute()
            )
            for opp in result.data:
                title = opp.get("title", "")
                if title and title not in seen:
                    pain_points.append(
                        {
                            "title": title,
                            "source": opp.get("intent", "pain_point"),
                            "score": opp.get("score", 0),
                        }
                    )
                    seen.add(title)
        except Exception as exc:
            logger.warning("Failed to fetch pain points from opportunities: %s", exc)

        # Fallback to company profile pain points
        company_pain_points = _jsonb_to_list(company.get("pain_points"))
        for pp in company_pain_points:
            if pp and pp not in seen:
                pain_points.append({"title": pp, "source": "company_profile", "score": 85})
                seen.add(pp)

        return pain_points

    def _get_seo_geo_questions(self, db: Client, project_id: int) -> list[dict]:
        """Fetch SEO/GEO target questions from opportunities."""
        questions: list[dict] = []
        seen: set[str] = set()

        try:
            result = (
                db.table("opportunities")
                .select("*")
                .eq("project_id", project_id)
                .in_("platform", ["seo", "geo"])
                .execute()
            )
            for opp in result.data:
                title = opp.get("title", "")
                if title and title not in seen:
                    questions.append({"title": title, "source": opp.get("platform", "seo")})
                    seen.add(title)
        except Exception as exc:
            logger.warning("Failed to fetch SEO/GEO questions: %s", exc)

        return questions

    def _generate_ideas(
        self,
        pain_points: list[dict],
        questions: list[dict],
        features: list[str],
        company: dict,
    ) -> list[dict]:
        """Generate 5 brief ideas from pain points, questions, and features."""
        ideas: list[dict] = []
        seen: set[str] = set()

        competitors = _jsonb_to_list(company.get("competitors"))
        target_audience = company.get("target_audience", "")
        category = company.get("category", "")

        # Pain-point-based ideas
        for pp in pain_points[:2]:
            title = pp["title"]
            if title not in seen:
                ideas.append(
                    {
                        "hook": title,
                        "pain_point": title,
                        "product_angle": f"{company.get('name', 'Our product')} solves this",
                        "source": pp["source"],
                    }
                )
                seen.add(title)

        # Question-based ideas
        for q in questions[:2]:
            title = q["title"]
            if title not in seen:
                ideas.append(
                    {
                        "hook": title,
                        "pain_point": "answering a common question",
                        "product_angle": f"Demonstrate {company.get('name', 'our product')} as the answer",
                        "source": q["source"],
                    }
                )
                seen.add(title)

        # Feature-based ideas
        for feat in features[:2]:
            if feat and feat not in seen:
                ideas.append(
                    {
                        "hook": f"How {company.get('name', 'we')} {feat}",
                        "pain_point": f"Users struggle with {feat}",
                        "product_angle": f"Show {feat} in action",
                        "source": "feature",
                    }
                )
                seen.add(feat)

        # Competitor-based ideas
        for comp in competitors[:2]:
            if comp and comp not in seen:
                ideas.append(
                    {
                        "hook": f"Stop overpaying for {comp}",
                        "pain_point": f"{comp} is too expensive or limited",
                        "product_angle": f"{company.get('name', 'Our product')} is the better alternative",
                        "source": "competitor",
                    }
                )
                seen.add(comp)

        # Category-based idea
        if category and category not in seen:
            ideas.append(
                {
                    "hook": f"The only {category} tool you actually need",
                    "pain_point": f"Too many {category} tools are confusing",
                    "product_angle": f"All-in-one {category} solution",
                    "source": "category",
                }
            )
            seen.add(category)

        # Audience-based idea
        if target_audience and target_audience not in seen:
            ideas.append(
                {
                    "hook": f"If you're a {target_audience}, this is for you",
                    "pain_point": f"{target_audience} have specific unmet needs",
                    "product_angle": f"Built specifically for {target_audience}",
                    "source": "audience",
                }
            )
            seen.add(target_audience)

        return ideas[:5]

    def generate_brief(self, idea: dict, company_profile: dict) -> dict:
        system_prompt = (
            "You are an expert short-form video strategist. Generate a structured video brief in JSON format. "
            "Return ONLY valid JSON with no markdown formatting."
        )
        user_content = (
            f"Hook idea: {idea.get('hook', '')}\n"
            f"Pain point: {idea.get('pain_point', '')}\n"
            f"Product angle: {idea.get('product_angle', '')}\n"
            f"Company: {company_profile.get('name', '')}\n"
            f"Description: {company_profile.get('description', '')}\n"
            f"Category: {company_profile.get('category', '')}\n"
            f"Target audience: {company_profile.get('target_audience', '')}\n\n"
            "Generate a video brief with these fields:\n"
            "- hook: first 3 seconds, attention-grabbing line (string)\n"
            "- scene_outline: list of scenes, each with scene (number), description (string), duration (string)\n"
            "- voiceover: full script text (string)\n"
            "- captions: list of on-screen text strings, one per scene\n"
            "- shot_list: list of camera/screen directions, one per scene\n"
            "- cta: soft call to action (string)\n"
            "- target_audience: who this is for (string)\n"
            "- pain_point: what problem it addresses (string)\n"
            "- product_angle: how the product helps (string)\n"
            "- duration_estimate: estimated video length like '15 seconds' (string)\n"
            "- platform_notes: tips for TikTok vs Reels vs Shorts (string)\n"
        )

        try:
            response = self._llm.call(system_prompt, user_content, temperature=0.5)
            if isinstance(response, dict):
                brief = response
            elif isinstance(response, list) and response:
                brief = response[0]
            else:
                brief = {}
            if not isinstance(brief, dict) or not brief.get("hook"):
                brief = self._fallback_brief(idea, company_profile)
        except Exception as exc:
            logger.warning("LLM brief generation failed: %s", exc)
            brief = self._fallback_brief(idea, company_profile)

        # Ensure all required fields
        brief.setdefault("hook", idea.get("hook", "Video Brief"))
        brief.setdefault("scene_outline", _default_scene_outline())
        brief.setdefault("voiceover", "")
        brief.setdefault("captions", [brief["hook"], "", "", "Link in bio"])
        brief.setdefault("shot_list", ["Close-up shot", "Screen recording", "Product shot", "CTA selfie"])
        brief.setdefault("cta", f"Learn more about {company_profile.get('name', 'our product')}")
        brief.setdefault("target_audience", company_profile.get("target_audience", ""))
        brief.setdefault("pain_point", idea.get("pain_point", ""))
        brief.setdefault("product_angle", idea.get("product_angle", ""))
        brief.setdefault("duration_estimate", "15 seconds")
        brief.setdefault("platform_notes", "TikTok: fast cuts. Reels: use trending audio. Shorts: clear CTA.")

        return brief

    @staticmethod
    def _fallback_brief(idea: dict, company_profile: dict) -> dict:
        hook = idea.get("hook", "Video Brief")
        return {
            "hook": hook,
            "scene_outline": _default_scene_outline(),
            "voiceover": f"Tired of {idea.get('pain_point', 'this problem')}? {company_profile.get('name', 'We')} can help. {idea.get('product_angle', '')}",
            "captions": [hook, "✓", "✓", "Link in bio"],
            "shot_list": ["Close-up reaction shot", "Screen recording", "Product demo", "Selfie with CTA"],
            "cta": f"Check out {company_profile.get('name', 'our product')} — link in bio",
            "target_audience": company_profile.get("target_audience", ""),
            "pain_point": idea.get("pain_point", ""),
            "product_angle": idea.get("product_angle", ""),
            "duration_estimate": "15 seconds",
            "platform_notes": "TikTok: fast cuts. Reels: use trending audio. Shorts: clear CTA.",
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
            f"# {brief.get('hook', opp.get('title', 'Video Brief'))}",
            "",
            f"**Target Audience:** {brief.get('target_audience', '')}",
            f"**Pain Point:** {brief.get('pain_point', '')}",
            f"**Product Angle:** {brief.get('product_angle', '')}",
            f"**Duration:** {brief.get('duration_estimate', '')}",
            "",
            "## Scene Outline",
            "",
        ]
        for scene in brief.get("scene_outline", []):
            if isinstance(scene, dict):
                lines.append(f"- Scene {scene.get('scene', '')}: {scene.get('description', '')} ({scene.get('duration', '')})")
            else:
                lines.append(f"- {scene}")
        lines.extend(["", "## Voiceover", brief.get("voiceover", ""), "", "## Captions", ""])
        for cap in brief.get("captions", []):
            lines.append(f"- {cap}")
        lines.extend(["", "## Shot List", ""])
        for shot in brief.get("shot_list", []):
            lines.append(f"- {shot}")
        lines.extend(["", "## Call to Action", brief.get("cta", "")])
        lines.extend(["", "## Platform Notes", brief.get("platform_notes", "")])

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


def _jsonb_to_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []


def _default_scene_outline() -> list[dict[str, Any]]:
    return [
        {"scene": 1, "description": "Hook / attention grabber", "duration": "3s"},
        {"scene": 2, "description": "Problem setup", "duration": "4s"},
        {"scene": 3, "description": "Solution reveal", "duration": "5s"},
        {"scene": 4, "description": "CTA", "duration": "3s"},
    ]
