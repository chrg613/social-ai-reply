"""Agent runs table operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client

AGENT_RUNS_TABLE = "agent_runs"


def get_agent_run_by_id(db: Client, run_id: int) -> dict[str, Any] | None:
    """Get an agent run by ID."""
    result = db.table(AGENT_RUNS_TABLE).select("*").eq("id", run_id).execute()
    return result.data[0] if result.data else None


def list_agent_runs_for_company(
    db: Client,
    company_id: int,
    agent_name: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List agent runs for a company with optional agent filter."""
    query = db.table(AGENT_RUNS_TABLE).select("*").eq("company_id", company_id)
    if agent_name:
        query = query.eq("agent_name", agent_name)
    result = query.order("created_at", desc=True).limit(limit).execute()
    return list(result.data)


def create_agent_run(db: Client, data: dict[str, Any]) -> dict[str, Any]:
    """Create a new agent run."""
    result = db.table(AGENT_RUNS_TABLE).insert(data).execute()
    return result.data[0]


def update_agent_run(db: Client, run_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    """Update an agent run."""
    result = db.table(AGENT_RUNS_TABLE).update(data).eq("id", run_id).execute()
    return result.data[0] if result.data else None


def get_last_agent_run(db: Client, company_id: int, agent_name: str) -> dict[str, Any] | None:
    """Get the most recent agent run for a company and agent."""
    result = (
        db.table(AGENT_RUNS_TABLE)
        .select("*")
        .eq("company_id", company_id)
        .eq("agent_name", agent_name)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None
