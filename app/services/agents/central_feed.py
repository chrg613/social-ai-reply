"""Central Opportunity Feed service — aggregates results from all agents."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

from app.db.tables.company import get_company_by_id
from app.db.tables.content import list_reply_drafts_for_opportunity
from app.db.tables.discovery import (
    OPPORTUNITIES_TABLE,
    _normalize_opportunity_record,
    _supports_column,
)
from app.db.tables.projects import list_projects_for_workspace
from app.schemas.v1.discovery import OpportunityResponse

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)

_OPP_COLUMN_CACHE: dict[str, bool] = {}


class FeedSort(Enum):
    RELEVANCE = "relevance"
    NEWEST = "newest"
    ENGAGEMENT = "engagement"
    PRIORITY = "priority"


@dataclass
class FeedFilters:
    platform: str | None = None
    status: str | None = None
    min_score: int | None = None
    intent: str | None = None
    keyword: str | None = None
    agent_name: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


@dataclass
class FeedResult:
    opportunities: list[OpportunityResponse] = field(default_factory=list)
    total: int = 0
    filters_applied: FeedFilters = field(default_factory=FeedFilters)
    debug_info: dict[str, Any] | None = None


def _opp_supports_column(db: Client, column: str) -> bool:
    return _supports_column(db, OPPORTUNITIES_TABLE, _OPP_COLUMN_CACHE, column)


class CentralFeedService:
    """Service that aggregates opportunities from all agents into a unified feed."""

    @staticmethod
    def _get_project_ids_for_company(db: Client, company_id: int) -> list[int]:
        """Resolve company_id -> workspace_id -> project_ids."""
        company = get_company_by_id(db, company_id)
        if not company:
            return []
        workspace_id = company.get("workspace_id")
        if not workspace_id:
            return []
        projects = list_projects_for_workspace(db, workspace_id)
        return [p["id"] for p in projects]

    @staticmethod
    def _build_base_query(
        db: Client,
        project_ids: list[int],
        filters: FeedFilters | None,
    ) -> Any:
        """Build the base Supabase query with filters applied."""
        query = db.table(OPPORTUNITIES_TABLE)
        if not project_ids:
            # Force empty result
            query = query.eq("project_id", -1)
        elif len(project_ids) == 1:
            query = query.eq("project_id", project_ids[0])
        else:
            query = query.in_("project_id", project_ids)

        if not filters:
            return query

        if filters.platform:
            query = query.eq("platform", filters.platform)
        if filters.status:
            query = query.eq("status", filters.status)
        if filters.min_score is not None:
            query = query.gte("score", filters.min_score)
        if filters.intent:
            query = query.eq("intent", filters.intent)
        if filters.keyword:
            query = query.ilike("title", f"%{filters.keyword}%")
        if filters.agent_name:
            query = query.eq("agent_name", filters.agent_name)
        if filters.date_from:
            query = query.gte("created_at", filters.date_from.isoformat())
        if filters.date_to:
            query = query.lte("created_at", filters.date_to.isoformat())

        return query

    @staticmethod
    def _apply_sort(query: Any, db: Client, sort: FeedSort) -> Any:
        """Apply sorting to the query."""
        if sort == FeedSort.RELEVANCE:
            query = query.order("score", desc=True)
        elif sort == FeedSort.NEWEST:
            if _opp_supports_column(db, "post_created_at"):
                query = query.order("post_created_at", desc=True)
            else:
                query = query.order("created_at", desc=True)
        elif sort == FeedSort.ENGAGEMENT:
            if _opp_supports_column(db, "engagement_score"):
                query = query.order("engagement_score", desc=True)
            elif _opp_supports_column(db, "upvotes"):
                query = query.order("upvotes", desc=True)
            else:
                query = query.order("score", desc=True)
        elif sort == FeedSort.PRIORITY:
            query = query.order("score", desc=True)
            if _opp_supports_column(db, "upvotes"):
                query = query.order("upvotes", desc=True)
        return query

    def get_feed(
        self,
        db: Client,
        company_id: int,
        filters: FeedFilters | None = None,
        sort: FeedSort = FeedSort.RELEVANCE,
        limit: int = 50,
        offset: int = 0,
        debug: bool = False,
    ) -> FeedResult:
        """Return a paginated, filtered, sorted feed of opportunities for a company."""
        project_ids = self._get_project_ids_for_company(db, company_id)

        # Build filtered query
        query = self._build_base_query(db, project_ids, filters).select("*")
        query = self._apply_sort(query, db, sort)
        query = query.range(offset, offset + limit - 1)

        result = query.execute()
        rows = [_normalize_opportunity_record(r) for r in result.data]

        # Count total
        count_result = self._build_base_query(db, project_ids, filters).select("id", count="exact").execute()
        total = count_result.count if hasattr(count_result, "count") and count_result.count is not None else len(rows)

        opportunities = [OpportunityResponse.model_validate(r) for r in rows]

        debug_info: dict[str, Any] | None = None
        if debug:
            debug_info = {
                "project_ids": project_ids,
                "company_id": company_id,
                "sort": sort.value,
                "limit": limit,
                "offset": offset,
                "query_columns_checked": dict(_OPP_COLUMN_CACHE),
            }

        return FeedResult(
            opportunities=opportunities,
            total=total,
            filters_applied=filters or FeedFilters(),
            debug_info=debug_info,
        )

    def get_debug_info(self, db: Client, company_id: int) -> dict[str, Any]:
        """Return aggregate debug statistics for a company's opportunities."""
        project_ids = self._get_project_ids_for_company(db, company_id)
        if not project_ids:
            return {
                "total_fetched_today": 0,
                "total_kept_today": 0,
                "total_rejected_today": 0,
                "by_agent": {},
                "top_rejection_reasons": [],
                "average_relevance_score": 0.0,
            }

        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)

        # Fetch all opportunities for these projects
        if len(project_ids) == 1:
            all_opp_query = db.table(OPPORTUNITIES_TABLE).select("*").eq("project_id", project_ids[0])
        else:
            all_opp_query = db.table(OPPORTUNITIES_TABLE).select("*").in_("project_id", project_ids)

        all_opps = all_opp_query.execute().data

        fetched_today = 0
        kept_today = 0
        rejected_today = 0
        by_agent: dict[str, dict[str, int]] = {}
        rejection_reasons: dict[str, int] = {}
        total_score = 0
        scored_count = 0

        for opp in all_opps:
            created_at = opp.get("created_at")
            updated_at = opp.get("updated_at")
            status = opp.get("status", "new")
            agent = opp.get("agent_name") or "unknown"
            score = opp.get("score")
            rejection_reason = opp.get("rejection_reason")

            if agent not in by_agent:
                by_agent[agent] = {"fetched": 0, "kept": 0, "rejected": 0}

            by_agent[agent]["fetched"] += 1

            if created_at:
                try:
                    if isinstance(created_at, str):
                        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if today <= created_at < tomorrow:
                        fetched_today += 1
                except (ValueError, TypeError):
                    pass

            if updated_at:
                try:
                    if isinstance(updated_at, str):
                        updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    if today <= updated_at < tomorrow:
                        if status in ("approved", "copied", "posted"):
                            kept_today += 1
                            by_agent[agent]["kept"] += 1
                        if status == "rejected" or rejection_reason:
                            rejected_today += 1
                            by_agent[agent]["rejected"] += 1
                except (ValueError, TypeError):
                    pass

            if rejection_reason:
                rejection_reasons[rejection_reason] = rejection_reasons.get(rejection_reason, 0) + 1

            if score is not None:
                total_score += score
                scored_count += 1

        top_rejection_reasons = sorted(rejection_reasons.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_fetched_today": fetched_today,
            "total_kept_today": kept_today,
            "total_rejected_today": rejected_today,
            "by_agent": by_agent,
            "top_rejection_reasons": top_rejection_reasons,
            "average_relevance_score": round(total_score / scored_count, 2) if scored_count else 0.0,
        }

    def get_opportunity_detail(self, db: Client, opportunity_id: int) -> dict[str, Any]:
        """Return full opportunity details including drafts, feedback, and scoring breakdown."""
        from app.db.tables.discovery import get_opportunity_by_id

        opportunity = get_opportunity_by_id(db, opportunity_id)
        if not opportunity:
            return {"opportunity": None}

        # Drafts
        drafts = list_reply_drafts_for_opportunity(db, opportunity_id)

        # Feedback history
        feedback_result = (
            db.table("feedback")
            .select("*")
            .eq("opportunity_id", opportunity_id)
            .order("created_at", desc=True)
            .execute()
        )
        feedback_history = list(feedback_result.data)

        # Scoring breakdown
        scoring = {
            "score": opportunity.get("score"),
            "score_reasons": opportunity.get("score_reasons", []),
            "semantic_similarity": opportunity.get("semantic_similarity"),
            "engagement_score": opportunity.get("engagement_score"),
            "risk_flags": opportunity.get("risk_flags", []),
            "matched_keywords": opportunity.get("matched_keywords", []),
            "intent": opportunity.get("intent"),
            "rejection_reason": opportunity.get("rejection_reason"),
        }

        return {
            "opportunity": OpportunityResponse.model_validate(opportunity).model_dump(),
            "drafts": drafts,
            "feedback_history": feedback_history,
            "scoring_breakdown": scoring,
        }
