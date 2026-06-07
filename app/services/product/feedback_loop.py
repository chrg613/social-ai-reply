"""Feedback Loop — adjusts keyword weights and source priorities based on user feedback."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.db.tables.brand_keywords import (
    disable_brand_keyword,
    list_brand_keywords_for_company,
    update_brand_keyword,
)
from app.db.tables.discovery import get_opportunity_by_id
from app.db.tables.feedback import list_feedback_for_company

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)

# Weight adjustment factors
_REJECT_WEIGHT_DECAY = 0.95
_APPROVE_WEIGHT_BOOST = 1.05
_MAX_WEIGHT = 2.0

# Thresholds
_NOISY_KEYWORD_THRESHOLD = 0.3
_AUTO_DISABLE_THRESHOLD = 0.2
_AUTO_BOOST_THRESHOLD = 0.8


class FeedbackLoop:
    """Processes user feedback to tune keyword weights and source priorities."""

    @staticmethod
    def process_feedback(feedback: dict[str, Any], db: Client) -> dict[str, Any]:
        """Process a single feedback record and adjust weights/priorities.

        Expected feedback keys:
        - opportunity_id: int
        - action: str (approved|rejected|copied|marked_irrelevant|regenerated)
        - reason: str | None
        - company_id: int
        """
        opportunity_id = feedback.get("opportunity_id")
        action = feedback.get("action", "").lower()
        reason = feedback.get("reason", "")
        company_id = feedback.get("company_id")

        adjustments: list[dict[str, Any]] = []
        logs: list[str] = []

        # Get opportunity
        opp = get_opportunity_by_id(db, opportunity_id) if opportunity_id else None
        if not opp:
            logs.append(f"Opportunity {opportunity_id} not found — skipping weight adjustment")
            return {"opportunity_id": opportunity_id, "action": action, "adjustments": adjustments, "logs": logs}

        # Extract matched keywords
        matched_keywords = opp.get("matched_keywords", []) or []
        if isinstance(matched_keywords, str):
            matched_keywords = [k.strip() for k in matched_keywords.split(",") if k.strip()]
        elif not isinstance(matched_keywords, list):
            matched_keywords = []

        # Normalize matched keywords to strings
        keyword_names = [str(kw).strip().lower() for kw in matched_keywords if str(kw).strip()]

        # Load brand keywords for this company
        brand_keywords = []
        if company_id:
            brand_keywords = list_brand_keywords_for_company(db, company_id, enabled_only=False)

        # Map keyword name -> brand keyword record
        kw_map: dict[str, dict[str, Any]] = {}
        for kw in brand_keywords:
            name = str(kw.get("keyword", "")).strip().lower()
            if name:
                kw_map[name] = kw

        if action in ("marked_irrelevant", "rejected"):
            for kw_name in keyword_names:
                kw = kw_map.get(kw_name)
                if kw:
                    new_weight = float(kw.get("weight", 1.0)) * _REJECT_WEIGHT_DECAY
                    update_brand_keyword(db, kw["id"], {"weight": new_weight})
                    adjustments.append({"keyword": kw_name, "adjustment": "decrement", "new_weight": round(new_weight, 4)})
            logs.append(
                f"User {action} opportunity #{opportunity_id} due to {reason}. "
                f"Reduced weight for keywords: {keyword_names}"
            )
        elif action in ("approved", "copied"):
            for kw_name in keyword_names:
                kw = kw_map.get(kw_name)
                if kw:
                    new_weight = min(float(kw.get("weight", 1.0)) * _APPROVE_WEIGHT_BOOST, _MAX_WEIGHT)
                    times_approved = int(kw.get("times_approved", 0)) + 1
                    update_brand_keyword(db, kw["id"], {"weight": new_weight, "times_approved": times_approved})
                    adjustments.append({"keyword": kw_name, "adjustment": "increment", "new_weight": round(new_weight, 4)})
            logs.append(
                f"User approved opportunity #{opportunity_id}. "
                f"Increased weight for keywords: {keyword_names}"
            )
        elif action == "regenerated":
            logs.append(f"User regenerated draft for opportunity #{opportunity_id}")
        else:
            logs.append(f"Unhandled feedback action: {action} for opportunity #{opportunity_id}")

        return {
            "opportunity_id": opportunity_id,
            "action": action,
            "adjustments": adjustments,
            "logs": logs,
        }

    @staticmethod
    def get_noisy_keywords(company_id: int, db: Client, threshold: float = _NOISY_KEYWORD_THRESHOLD) -> list[dict[str, Any]]:
        """Return keywords with low approval rates that may be causing noise."""
        keywords = list_brand_keywords_for_company(db, company_id, enabled_only=False)
        noisy: list[dict[str, Any]] = []
        for kw in keywords:
            approved = int(kw.get("times_approved", 0))
            rejected = int(kw.get("times_rejected", 0))
            total = approved + rejected + 1
            approval_rate = approved / total
            if approval_rate < threshold or rejected > approved * 2:
                noisy.append({
                    "id": kw["id"],
                    "keyword": kw["keyword"],
                    "approval_rate": round(approval_rate, 3),
                    "times_approved": approved,
                    "times_rejected": rejected,
                    "weight": kw.get("weight", 1.0),
                    "is_enabled": kw.get("is_enabled", True),
                    "suggestion": "disable" if approval_rate < _AUTO_DISABLE_THRESHOLD else "review",
                })
        return noisy

    @staticmethod
    def get_noisy_sources(company_id: int, db: Client) -> list[dict[str, Any]]:
        """Return platforms with high rejection rates (>0.7)."""
        feedback_rows = list_feedback_for_company(db, company_id)
        if not feedback_rows:
            return []

        # Collect opportunity IDs
        opp_ids = [f["opportunity_id"] for f in feedback_rows if f.get("opportunity_id")]
        # Batch fetch opportunities to map platform
        opp_platforms: dict[int, str] = {}
        if opp_ids:
            # Query in chunks of 100 to avoid URL length issues
            chunk_size = 100
            for i in range(0, len(opp_ids), chunk_size):
                chunk = opp_ids[i:i + chunk_size]
                result = db.table("opportunities").select("id,platform").in_("id", chunk).execute()
                for row in result.data:
                    opp_platforms[row["id"]] = row.get("platform", "unknown")

        platform_stats: dict[str, dict[str, int]] = {}
        for f in feedback_rows:
            action = f.get("action", "unknown")
            platform = opp_platforms.get(f.get("opportunity_id"), "unknown")
            if platform not in platform_stats:
                platform_stats[platform] = {"total": 0, "rejected": 0, "approved": 0}
            platform_stats[platform]["total"] += 1
            if action in ("rejected", "marked_irrelevant"):
                platform_stats[platform]["rejected"] += 1
            elif action in ("approved", "copied"):
                platform_stats[platform]["approved"] += 1

        noisy: list[dict[str, Any]] = []
        for platform, stats in platform_stats.items():
            if stats["total"] == 0:
                continue
            rejection_rate = stats["rejected"] / stats["total"]
            if rejection_rate > 0.7:
                noisy.append({
                    "platform": platform,
                    "total_feedback": stats["total"],
                    "rejected": stats["rejected"],
                    "approved": stats["approved"],
                    "rejection_rate": round(rejection_rate, 3),
                    "suggestion": "reduce_priority_or_disable",
                })
        return noisy

    @staticmethod
    def tune_keywords(company_id: int, db: Client) -> list[dict[str, Any]]:
        """Auto-tune keywords: disable very low approval, boost high approval."""
        keywords = list_brand_keywords_for_company(db, company_id, enabled_only=False)
        changes: list[dict[str, Any]] = []
        for kw in keywords:
            approved = int(kw.get("times_approved", 0))
            rejected = int(kw.get("times_rejected", 0))
            total = approved + rejected + 1
            approval_rate = approved / total
            kw_id = kw["id"]
            keyword_name = kw["keyword"]
            weight = float(kw.get("weight", 1.0))
            is_enabled = kw.get("is_enabled", True)

            if approval_rate < _AUTO_DISABLE_THRESHOLD and is_enabled:
                disable_brand_keyword(db, kw_id)
                changes.append({
                    "keyword": keyword_name,
                    "action": "disabled",
                    "reason": f"approval_rate {round(approval_rate, 3)} < {_AUTO_DISABLE_THRESHOLD}",
                })
            elif approval_rate > _AUTO_BOOST_THRESHOLD and is_enabled:
                new_weight = min(weight * _APPROVE_WEIGHT_BOOST, _MAX_WEIGHT)
                update_brand_keyword(db, kw_id, {"weight": new_weight})
                changes.append({
                    "keyword": keyword_name,
                    "action": "boosted",
                    "reason": f"approval_rate {round(approval_rate, 3)} > {_AUTO_BOOST_THRESHOLD}",
                    "new_weight": round(new_weight, 4),
                })
        return changes
