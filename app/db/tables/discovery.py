"""Discovery table operations: personas, keywords, monitored subreddits, opportunities, scan runs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from postgrest.exceptions import APIError

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)

PERSONAS_TABLE = "personas_v1"
DISCOVERY_KEYWORDS_TABLE = "discovery_keywords"
MONITORED_SUBREDDITS_TABLE = "monitored_subreddits"
SCAN_RUNS_TABLE = "scan_runs"
OPPORTUNITIES_TABLE = "opportunities"
SUBREDDITS_ANALYSES_TABLE = "subreddits_analyses"  # note: plural "subreddits_", DB name is authoritative
_SCAN_RUN_COLUMN_CACHE: dict[str, bool] = {}
_OPPORTUNITY_COLUMN_CACHE: dict[str, bool] = {}


def _is_missing_column_error(exc: APIError, column: str) -> bool:
    code = (exc.code or "").upper()
    if code == "PGRST204":
        return True
    context = " ".join(part for part in [exc.message, exc.details, exc.hint] if part).lower()
    return "does not exist" in context and column.lower() in context


def _supports_column(db: Client, table_name: str, cache: dict[str, bool], column: str) -> bool:
    cached = cache.get(column)
    if cached is not None:
        return cached

    try:
        db.table(table_name).select(column).limit(1).execute()
    except APIError as exc:
        if not _is_missing_column_error(exc, column):
            raise
        cache[column] = False
        return False

    cache[column] = True
    return True


# Persona operations
def get_persona_by_id(db: Client, persona_id: int) -> dict[str, Any] | None:
    """Get a persona by ID."""
    result = db.table(PERSONAS_TABLE).select("*").eq("id", persona_id).execute()
    return result.data[0] if result.data else None


def create_persona(db: Client, persona_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new persona."""
    result = db.table(PERSONAS_TABLE).insert(persona_data).execute()
    return result.data[0]


def update_persona(db: Client, persona_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a persona."""
    result = db.table(PERSONAS_TABLE).update(update_data).eq("id", persona_id).execute()
    return result.data[0] if result.data else None


def delete_persona(db: Client, persona_id: int) -> None:
    """Delete a persona."""
    db.table(PERSONAS_TABLE).delete().eq("id", persona_id).execute()


# Discovery keyword operations
def get_discovery_keyword_by_id(db: Client, keyword_id: int) -> dict[str, Any] | None:
    """Get a discovery keyword by ID."""
    result = db.table(DISCOVERY_KEYWORDS_TABLE).select("*").eq("id", keyword_id).execute()
    return result.data[0] if result.data else None


def list_keywords_for_project(db: Client, project_id: int) -> list[dict[str, Any]]:
    """List all discovery keywords for a project, ordered by priority."""
    result = (
        db.table(DISCOVERY_KEYWORDS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .order("priority_score", desc=True)
        .execute()
    )
    return list(result.data)


def create_discovery_keyword(db: Client, keyword_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new discovery keyword, silently dropping columns the DB doesn't have."""
    try:
        result = db.table(DISCOVERY_KEYWORDS_TABLE).insert(keyword_data).execute()
        return result.data[0]
    except Exception as exc:
        # If a column doesn't exist (e.g. 'category'), strip it and retry
        err_msg = str(exc)
        if "schema cache" in err_msg or "column" in err_msg.lower():
            # Find which columns the table supports
            safe_data = {}
            for key, value in keyword_data.items():
                if _supports_column(db, DISCOVERY_KEYWORDS_TABLE, _DISCOVERY_KEYWORD_COLUMN_CACHE, key):
                    safe_data[key] = value
            result = db.table(DISCOVERY_KEYWORDS_TABLE).insert(safe_data).execute()
            return result.data[0]
        raise


_DISCOVERY_KEYWORD_COLUMN_CACHE: dict[str, bool] = {}


def update_discovery_keyword(db: Client, keyword_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a discovery keyword."""
    result = db.table(DISCOVERY_KEYWORDS_TABLE).update(update_data).eq("id", keyword_id).execute()
    return result.data[0] if result.data else None


def delete_discovery_keyword(db: Client, keyword_id: int) -> None:
    """Delete a discovery keyword."""
    db.table(DISCOVERY_KEYWORDS_TABLE).delete().eq("id", keyword_id).execute()


def get_keyword_by_project_and_keyword(db: Client, project_id: int, keyword: str) -> dict[str, Any] | None:
    """Get a discovery keyword by project ID and keyword string."""
    result = (
        db.table(DISCOVERY_KEYWORDS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .eq("keyword", keyword)
        .execute()
    )
    return result.data[0] if result.data else None


# Monitored subreddit operations
def get_monitored_subreddit_by_id(db: Client, subreddit_id: int) -> dict[str, Any] | None:
    """Get a monitored subreddit by ID."""
    result = db.table(MONITORED_SUBREDDITS_TABLE).select("*").eq("id", subreddit_id).execute()
    return result.data[0] if result.data else None


def list_subreddits_for_project(db: Client, project_id: int) -> list[dict[str, Any]]:
    """List all monitored subreddits for a project."""
    result = (
        db.table(MONITORED_SUBREDDITS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .order("fit_score", desc=True)
        .execute()
    )
    return list(result.data)


def create_monitored_subreddit(db: Client, subreddit_data: dict[str, Any]) -> dict[str, Any] | None:
    """Create a new monitored subreddit."""
    try:
        result = db.table(MONITORED_SUBREDDITS_TABLE).insert(subreddit_data).execute()
        return result.data[0]
    except APIError:
        logger.warning("Failed to insert into monitored_subreddits")
        return None


def update_monitored_subreddit(db: Client, subreddit_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a monitored subreddit."""
    try:
        result = db.table(MONITORED_SUBREDDITS_TABLE).update(update_data).eq("id", subreddit_id).execute()
        return result.data[0] if result.data else None
    except APIError:
        logger.warning("Failed to update monitored_subreddit %s", subreddit_id)
        return None


def delete_monitored_subreddit(db: Client, subreddit_id: int) -> None:
    """Delete a monitored subreddit."""
    try:
        db.table(MONITORED_SUBREDDITS_TABLE).delete().eq("id", subreddit_id).execute()
    except APIError:
        logger.warning("Failed to delete monitored_subreddit %s", subreddit_id)


def get_subreddit_by_project_and_name(db: Client, project_id: int, name: str) -> dict[str, Any] | None:
    """Get a monitored subreddit by project ID and subreddit name."""
    try:
        result = (
            db.table(MONITORED_SUBREDDITS_TABLE)
            .select("*")
            .eq("project_id", project_id)
            .eq("name", name)
            .execute()
        )
        return result.data[0] if result.data else None
    except APIError:
        logger.warning("Failed to query monitored_subreddits")
        return None


def create_subreddit_analysis(db: Client, analysis_data: dict[str, Any]) -> dict[str, Any] | None:
    """Create a new subreddit analysis record."""
    try:
        result = db.table(SUBREDDITS_ANALYSES_TABLE).insert(analysis_data).execute()
        return result.data[0]
    except APIError:
        logger.warning("subreddits_analyses table not found — skipping")
        return None


# Scan run operations
def get_scan_run_by_id(db: Client, scan_run_id: str) -> dict[str, Any] | None:
    """Get a scan run by ID."""
    result = db.table(SCAN_RUNS_TABLE).select("*").eq("id", scan_run_id).execute()
    return _normalize_scan_run_record(result.data[0]) if result.data else None


def list_scan_runs_for_project(db: Client, project_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """List scan runs for a project."""
    result = (
        db.table(SCAN_RUNS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [_normalize_scan_run_record(row) for row in result.data]


def create_scan_run(db: Client, scan_run_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new scan run."""
    payload = _prepare_scan_run_payload(db, scan_run_data)
    result = db.table(SCAN_RUNS_TABLE).insert(payload).execute()
    return _normalize_scan_run_record(result.data[0])


def update_scan_run(db: Client, scan_run_id: str, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a scan run."""
    payload = _prepare_scan_run_payload(db, update_data)
    if not payload:
        return get_scan_run_by_id(db, scan_run_id)
    result = db.table(SCAN_RUNS_TABLE).update(payload).eq("id", scan_run_id).execute()
    return _normalize_scan_run_record(result.data[0]) if result.data else None


def delete_scan_run(db: Client, scan_run_id: str) -> None:
    """Delete a scan run."""
    db.table(SCAN_RUNS_TABLE).delete().eq("id", scan_run_id).execute()


# Opportunity operations
def get_opportunity_by_id(db: Client, opportunity_id: int) -> dict[str, Any] | None:
    """Get an opportunity by ID."""
    result = db.table(OPPORTUNITIES_TABLE).select("*").eq("id", opportunity_id).execute()
    return _normalize_opportunity_record(result.data[0]) if result.data else None


def get_opportunity_by_project_and_reddit_post(
    db: Client,
    project_id: int,
    reddit_post_id: str,
) -> dict[str, Any] | None:
    """Get an opportunity by project ID and Reddit post ID."""
    result = (
        db.table(OPPORTUNITIES_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .eq("reddit_post_id", reddit_post_id)
        .execute()
    )
    return _normalize_opportunity_record(result.data[0]) if result.data else None


def batch_get_opportunities_by_reddit_posts(
    db: Client,
    project_id: int,
    reddit_post_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Batch-fetch opportunities for multiple Reddit post IDs in one query.

    Returns a dict mapping reddit_post_id -> opportunity record (or missing
    if that post has no opportunity yet).
    """
    if not reddit_post_ids:
        return {}
    result = (
        db.table(OPPORTUNITIES_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .in_("reddit_post_id", reddit_post_ids)
        .execute()
    )
    return {
        row["reddit_post_id"]: _normalize_opportunity_record(row)
        for row in result.data
    }


def list_opportunities_for_project(
    db: Client,
    project_id: int,
    status: str | None = None,
    platform: str | None = None,
    agent_name: str | None = None,
    intent: str | None = None,
    buying_stage: str | None = None,
    min_score: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List opportunities for a project with optional filters."""
    query = db.table(OPPORTUNITIES_TABLE).select("*").eq("project_id", project_id)
    if status:
        query = query.eq("status", status)
    if platform:
        query = query.eq("platform", platform)
    if agent_name:
        query = query.eq("agent_name", agent_name)
    if intent:
        query = query.eq("intent", intent)
    if buying_stage:
        query = query.eq("buying_stage", buying_stage)
    if min_score is not None:
        query = query.gte("score", min_score)
    result = query.order("score", desc=True).range(offset, offset + limit - 1).execute()
    return [_normalize_opportunity_record(row) for row in result.data]


def create_opportunity(db: Client, opportunity_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new opportunity."""
    payload = _prepare_opportunity_payload(db, opportunity_data)
    result = db.table(OPPORTUNITIES_TABLE).insert(payload).execute()
    return _normalize_opportunity_record(result.data[0])


def update_opportunity(db: Client, opportunity_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update an opportunity."""
    payload = _prepare_opportunity_payload(db, update_data)
    result = db.table(OPPORTUNITIES_TABLE).update(payload).eq("id", opportunity_id).execute()
    return _normalize_opportunity_record(result.data[0]) if result.data else None


def delete_opportunity(db: Client, opportunity_id: int) -> None:
    """Delete an opportunity."""
    db.table(OPPORTUNITIES_TABLE).delete().eq("id", opportunity_id).execute()


def bulk_create_opportunities(db: Client, opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bulk create multiple opportunities."""
    if not opportunities:
        return []
    payload = [_prepare_opportunity_payload(db, opportunity) for opportunity in opportunities]
    result = db.table(OPPORTUNITIES_TABLE).insert(payload).execute()
    return [_normalize_opportunity_record(row) for row in result.data]


def count_opportunities_for_project(db: Client, project_id: int, status: str | None = None) -> int:
    """Count opportunities for a project."""
    query = db.table(OPPORTUNITIES_TABLE).select("id", count="exact").eq("project_id", project_id)
    if status:
        query = query.eq("status", status)
    result = query.execute()
    return result.count if hasattr(result, "count") and result.count is not None else 0


def list_personas_for_project(db: Client, project_id: int, source: str | None = None, limit: int = 100, include_inactive: bool = False) -> list[dict[str, Any]]:
    """List personas for a project with optional source filter."""
    query = db.table(PERSONAS_TABLE).select("*").eq("project_id", project_id)
    if source:
        query = query.eq("source", source)
    if not include_inactive:
        query = query.eq("is_active", True)
    result = query.order("created_at", desc=True).limit(limit).execute()
    return list(result.data)


def list_discovery_keywords_for_project(db: Client, project_id: int, source: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """List discovery keywords for a project."""
    query = db.table(DISCOVERY_KEYWORDS_TABLE).select("*").eq("project_id", project_id)
    if source:
        query = query.eq("source", source)
    query = query.eq("is_active", True)
    result = query.order("priority_score", desc=True).limit(limit).execute()
    return list(result.data)


def list_monitored_subreddits_for_project(db: Client, project_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """List monitored subreddits for a project."""
    result = (
        db.table(MONITORED_SUBREDDITS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .order("fit_score", desc=True)
        .limit(limit)
        .execute()
    )
    return list(result.data)


def _scan_run_supports_column(db: Client, column: str) -> bool:
    return _supports_column(db, SCAN_RUNS_TABLE, _SCAN_RUN_COLUMN_CACHE, column)


def _prepare_scan_run_payload(db: Client, payload: dict[str, Any]) -> dict[str, Any]:
    prepared: dict[str, Any] = {}
    for key, value in payload.items():
        target_key = key
        if (
            key == "completed_at"
            and not _scan_run_supports_column(db, "completed_at")
            and _scan_run_supports_column(db, "finished_at")
        ):
            target_key = "finished_at"
        if not _scan_run_supports_column(db, target_key):
            continue
        prepared[target_key] = value
    return prepared


def _normalize_scan_run_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    if "completed_at" not in normalized and normalized.get("finished_at") is not None:
        normalized["completed_at"] = normalized.get("finished_at")
    normalized.setdefault("search_window_hours", 0)
    normalized.setdefault("posts_scanned", 0)
    normalized.setdefault("opportunities_found", 0)
    return normalized


def _opportunity_supports_column(db: Client, column: str) -> bool:
    return _supports_column(db, OPPORTUNITIES_TABLE, _OPPORTUNITY_COLUMN_CACHE, column)


def _prepare_opportunity_payload(db: Client, payload: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(payload)
    subreddit_value = prepared.get("subreddit") or prepared.get("subreddit_name")
    if subreddit_value is not None:
        if _opportunity_supports_column(db, "subreddit"):
            prepared["subreddit"] = subreddit_value
        if _opportunity_supports_column(db, "subreddit_name"):
            prepared["subreddit_name"] = subreddit_value

    # Ensure reddit_post_id is set for non-Reddit agents to avoid NOT NULL violations
    if "reddit_post_id" not in prepared or prepared["reddit_post_id"] is None:
        prepared.setdefault("reddit_post_id", None)

    return {
        key: value
        for key, value in prepared.items()
        if _opportunity_supports_column(db, key)
    }


def _normalize_opportunity_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    subreddit_value = normalized.get("subreddit_name") or normalized.get("subreddit")
    if subreddit_value is not None:
        normalized.setdefault("subreddit_name", subreddit_value)
        normalized.setdefault("subreddit", subreddit_value)
    return normalized


SCORE_FEEDBACK_TABLE = "score_feedback"


def create_score_feedback(db: Client, feedback_data: dict[str, Any]) -> dict[str, Any]:
    """Record a user action on an opportunity for score calibration."""
    try:
        result = db.table(SCORE_FEEDBACK_TABLE).insert(feedback_data).execute()
        return result.data[0]
    except Exception as exc:
        logger.warning("score_feedback insert failed (table may not exist): %s", exc)
        return {}


def list_score_feedback_for_workspace(
    db: Client,
    workspace_id: int,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List recent score feedback records for a workspace.

    Used by the calibration function to compute score adjustments.
    Note: score_feedback table links through opportunity_id, not workspace_id.
    We fetch the latest feedback globally; the caller filters by relevance.
    """
    result = (
        db.table(SCORE_FEEDBACK_TABLE)
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(result.data)
