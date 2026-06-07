"""Scheduler Service — orchestrates multi-agent runs with enablement checks and rate limiting."""

from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.db.tables.agent_runs import (
    list_agent_runs_for_company,
    update_agent_run,
)
from app.db.tables.company import get_company_by_id
from app.db.tables.projects import list_projects_for_workspace
from app.db.tables.sources import list_sources_for_company

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)

_AGENT_RATE_LIMIT_SECONDS = 5.0


@dataclass
class AgentRunResult:
    items_fetched: int = 0
    items_kept: int = 0
    items_rejected: int = 0
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


class SchedulerService:
    """Orchestrates running agents for a company with enablement and concurrency guards."""

    def __init__(self) -> None:
        self._registry: dict[str, type] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        """Load agent classes lazily to avoid circular imports."""
        agents_to_load = [
            ("reddit", "app.services.agents.reddit_agent", "RedditAgent"),
            ("hackernews", "app.services.agents.hackernews_agent", "HackerNewsAgent"),
            ("seo", "app.services.agents.seo_agent", "SEOAgent"),
            ("geo", "app.services.agents.geo_agent", "GEOAgent"),
            ("articles", "app.services.agents.articles_agent", "ArticlesAgent"),
            ("x_manual", "app.services.agents.x_agent", "XAgent"),
            ("linkedin_manual", "app.services.agents.linkedin_agent", "LinkedInAgent"),
            ("ugc", "app.services.agents.ugc_agent", "UGCAgent"),
            ("technical_seo", "app.services.agents.technical_seo_agent", "TechnicalSEOAgent"),
        ]

        for name, module_path, class_name in agents_to_load:
            try:
                import importlib

                module = importlib.import_module(module_path)
                agent_class = getattr(module, class_name)
                self._registry[name] = agent_class
            except Exception as exc:
                logger.warning("Failed to load agent %s from %s: %s", name, module_path, exc)

    def get_agent_registry(self) -> dict[str, type]:
        """Return mapping of agent_name -> agent_class."""
        return dict(self._registry)

    def get_enabled_agents(self, company_id: int, db: Client) -> list[str]:
        """Query sources table for active sources and map platform to agent name.

        If no sources are configured, return ALL registered agents as a default.
        """
        sources = list_sources_for_company(db, company_id, status="active")
        if not sources:
            # Default: all agents are enabled if user hasn't configured sources
            logger.info("No sources configured for company %s — defaulting to all agents", company_id)
            return list(self._registry.keys())

        enabled: set[str] = set()
        platform_to_agent: dict[str, str] = {
            "reddit": "reddit",
            "hackernews": "hackernews",
            "hn": "hackernews",
            "seo": "seo",
            "geo": "geo",
            "article": "articles",
            "articles": "articles",
            "x": "x_manual",
            "twitter": "x_manual",
            "linkedin": "linkedin_manual",
            "ugc": "ugc",
            "technical_seo": "technical_seo",
        }
        for source in sources:
            platform = str(source.get("platform", "")).lower().strip()
            if platform in platform_to_agent:
                enabled.add(platform_to_agent[platform])
        return list(enabled)

    def get_agent_status(self, company_id: int, agent_name: str, db: Client) -> dict[str, Any]:
        """Return is_running, last_run, and next_run_time for an agent."""
        runs = list_agent_runs_for_company(db, company_id, agent_name=agent_name, limit=1)
        is_running = any(r.get("status") == "running" for r in runs)
        last_run = runs[0] if runs else None
        next_run_time: datetime | None = None
        if last_run and not is_running:
            # Suggest next run in 1 hour after last completed run
            finished = last_run.get("finished_at") or last_run.get("created_at")
            if finished:
                try:
                    finished_dt = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                    next_run_time = finished_dt + timedelta(hours=1)
                except (ValueError, TypeError):
                    pass
        return {
            "is_running": is_running,
            "last_run": last_run,
            "next_run_time": next_run_time,
        }

    def run_agent(self, agent_name: str, company_id: int, db: Client, run_id: str | None = None) -> AgentRunResult:
        """Run a single agent by name.

        Args:
            agent_name: Name of the agent to run.
            company_id: ID of the company to run for.
            db: Supabase client.
            run_id: Optional existing agent_run ID. If provided, updates that record.
                    If None, creates a new one.
        """
        if agent_name not in self._registry:
            logger.error("Agent %s not found in registry", agent_name)
            result = AgentRunResult(
                logs=[f"Agent {agent_name} not found in registry"],
            )
            if run_id:
                update_agent_run(db, run_id, {"status": "failed", "error_message": f"Agent {agent_name} not found"})
            return result

        # Check if enabled
        enabled = self.get_enabled_agents(company_id, db)
        if agent_name not in enabled:
            msg = f"Agent {agent_name} is not enabled for company {company_id}"
            logger.info(msg)
            result = AgentRunResult(logs=[msg])
            if run_id:
                update_agent_run(db, run_id, {"status": "failed", "error_message": msg})
            return result

        # Check if another instance is already running (exclude current run_id)
        runs = list_agent_runs_for_company(db, company_id, agent_name=agent_name)
        other_running = any(
            r.get("status") == "running" and r.get("id") != run_id
            for r in runs
        )
        if other_running:
            msg = f"Agent {agent_name} is already running for company {company_id}"
            logger.info(msg)
            result = AgentRunResult(logs=[msg])
            if run_id:
                update_agent_run(db, run_id, {"status": "failed", "error_message": msg})
            return result

        # Create or reuse agent_run record
        if not run_id:
            from app.db.tables.agent_runs import create_agent_run
            started_at = datetime.now(UTC)
            run = create_agent_run(db, {
                "company_id": company_id,
                "agent_name": agent_name,
                "status": "running",
                "started_at": started_at.isoformat(),
            })
            run_id = run["id"]

        result = AgentRunResult()
        try:
            agent_class = self._registry[agent_name]
            agent = agent_class()

            # Build minimal config
            config: dict[str, Any] = {"project_id": self._get_project_id_for_company(db, company_id)}

            # Detect run signature and invoke accordingly
            sig = inspect.signature(agent.run)
            params = list(sig.parameters.keys())
            if "project_id" in params:
                project_id = config.get("project_id")
                if project_id:
                    result = agent.run(company_id, project_id, db, config)
                else:
                    result = agent.run(company_id, db, config)
            else:
                result = agent.run(company_id, db, config)

            # Update agent_run with completed status
            update_agent_run(db, run_id, {
                "status": "completed",
                "items_fetched": result.items_fetched,
                "items_kept": result.items_kept,
                "items_rejected": result.items_rejected,
                "finished_at": datetime.now(UTC).isoformat(),
                "logs_json": result.logs,
            })
            logger.info("Agent %s completed for company %s: fetched=%s kept=%s rejected=%s", agent_name, company_id, result.items_fetched, result.items_kept, result.items_rejected)
        except Exception as exc:
            logger.exception("Agent %s run failed for company %s", agent_name, company_id)
            result.logs.append(f"FATAL ERROR: {type(exc).__name__}: {exc}")
            update_agent_run(db, run_id, {
                "status": "failed",
                "error_message": str(exc)[:500],
                "finished_at": datetime.now(UTC).isoformat(),
                "logs_json": result.logs,
            })

        return result

    def run_all(self, company_id: int, db: Client) -> list[AgentRunResult]:
        """Run all enabled agents for a company."""
        results: list[AgentRunResult] = []
        enabled = self.get_enabled_agents(company_id, db)
        logger.info("Running all agents for company %s. Enabled: %s", company_id, enabled)

        for agent_name in self._registry:
            if agent_name not in enabled:
                logger.info("Skipping disabled agent %s", agent_name)
                continue

            result = self.run_agent(agent_name, company_id, db)
            results.append(result)

            # Rate limit: sleep between agents
            time.sleep(_AGENT_RATE_LIMIT_SECONDS)

        return results

    @staticmethod
    def _get_project_id_for_company(db: Client, company_id: int) -> int | None:
        """Resolve a project_id for a company (used for agents that require it)."""
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
