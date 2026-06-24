"""API tests for auto-pipeline endpoints."""

from unittest.mock import patch

from app.db.tables.analytics import create_auto_pipeline
from app.db.tables.content import create_reply_draft
from app.db.tables.discovery import (
    create_discovery_keyword,
    create_monitored_subreddit,
    create_opportunity,
    create_persona,
)
from app.db.tables.projects import create_project


def _create_project(mock_supabase, workspace_id: int) -> dict:
    return create_project(
        mock_supabase,
        {
            "workspace_id": workspace_id,
            "name": "Pipeline Project",
            "slug": "pipeline-project",
            "description": "",
            "is_active": True,
        },
    )


class TestAutoPipeline:
    def test_start_auto_pipeline_rejects_when_llm_provider_is_unavailable(self, authed_client, mock_supabase):
        client, _user_data = authed_client

        with patch(
            "app.api.v1.routes.auto_pipeline.LLMService",
            side_effect=RuntimeError("No LLM provider available - configure GEMINI_API_KEY in backend .env.local"),
        ):
            resp = client.post(
                "/v1/auto-pipeline/run",
                json={"website_url": "https://example.com"},
            )

        assert resp.status_code == 503
        assert "No LLM provider available" in resp.json()["detail"]
        assert mock_supabase.table("auto_pipelines").select("*").execute().data == []

    def test_get_auto_pipeline_returns_results_for_executed_runs(self, authed_client, mock_supabase):
        client, user_data = authed_client
        project = _create_project(mock_supabase, user_data["workspace"]["id"])

        create_persona(
            mock_supabase,
            {
                "project_id": project["id"],
                "name": "Founder",
                "role": "Buyer",
                "summary": "Needs a reliable growth engine.",
                "pain_points": ["Low lead volume"],
                "source": "generated",
                "is_active": True,
            },
        )
        create_persona(
            mock_supabase,
            {
                "project_id": project["id"],
                "name": "Operator",
                "role": "Researcher",
                "summary": "Should not leak into this run's snapshot.",
                "pain_points": ["Noise"],
                "source": "generated",
                "is_active": True,
            },
        )
        create_discovery_keyword(
            mock_supabase,
            {
                "project_id": project["id"],
                "keyword": "reddit lead generation",
                "priority_score": 92,
                "source": "generated",
            },
        )
        create_discovery_keyword(
            mock_supabase,
            {
                "project_id": project["id"],
                "keyword": "redundant keyword",
                "priority_score": 65,
                "source": "generated",
            },
        )
        create_monitored_subreddit(
            mock_supabase,
            {
                "project_id": project["id"],
                "name": "saas",
                "fit_score": 88,
                "subscribers": 120000,
                "description": "SaaS growth conversations",
            },
        )
        opportunity = create_opportunity(
            mock_supabase,
            {
                "project_id": project["id"],
                "reddit_post_id": "abc123",
                "subreddit_name": "saas",
                "author": "founder42",
                "title": "How do you find qualified SaaS leads from Reddit?",
                "permalink": "https://reddit.com/r/saas/comments/abc123/test",
                "score": 91,
                "status": "drafting",
            },
        )
        create_opportunity(
            mock_supabase,
            {
                "project_id": project["id"],
                "reddit_post_id": "extra456",
                "subreddit_name": "saas",
                "author": "founder99",
                "title": "Older project opportunity that should not show for this run",
                "permalink": "https://reddit.com/r/saas/comments/extra456/test",
                "score": 77,
                "status": "drafting",
            },
        )
        create_reply_draft(
            mock_supabase,
            {
                "project_id": project["id"],
                "opportunity_id": opportunity["id"],
                "content": "Start with high-intent problem threads and write specific replies.",
            },
        )
        create_reply_draft(
            mock_supabase,
            {
                "project_id": project["id"],
                "opportunity_id": opportunity["id"],
                "content": "Older draft that should not show for this run.",
            },
        )
        pipeline = create_auto_pipeline(
            mock_supabase,
            {
                "id": "pipe_executed_1",
                "project_id": project["id"],
                "website_url": "https://example.com",
                "status": "executed",
                "progress": 100,
                "current_step": "Complete!",
                "brand_summary": "B2B SaaS for Reddit lead generation",
                "personas_generated": 1,
                "keywords_generated": 1,
                "subreddits_found": 1,
                "opportunities_found": 1,
                "drafts_generated": 1,
            },
        )

        resp = client.get(f"/v1/auto-pipeline/{pipeline['id']}")

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["status"] == "executed"
        assert len(payload["results"]["personas"]) == 1
        assert len(payload["results"]["keywords"]) == 1
        assert len(payload["results"]["opportunities"]) == 1
        assert len(payload["results"]["drafts"]) == 1
        assert payload["results"]["opportunities"][0]["title"] == opportunity["title"]
        assert payload["results"]["drafts"][0]["opportunity_title"] == opportunity["title"]
        assert payload["results"]["drafts"][0]["content"]

    def test_get_auto_pipeline_hides_project_history_when_run_counts_are_zero(self, authed_client, mock_supabase):
        client, user_data = authed_client
        project = _create_project(mock_supabase, user_data["workspace"]["id"])

        create_persona(
            mock_supabase,
            {
                "project_id": project["id"],
                "name": "Founder",
                "role": "Buyer",
                "summary": "Historical persona",
                "pain_points": ["Noise"],
                "source": "generated",
                "is_active": True,
            },
        )
        create_discovery_keyword(
            mock_supabase,
            {
                "project_id": project["id"],
                "keyword": "historical keyword",
                "priority_score": 75,
                "source": "generated",
            },
        )
        create_monitored_subreddit(
            mock_supabase,
            {
                "project_id": project["id"],
                "name": "saas",
                "fit_score": 88,
                "subscribers": 120000,
                "description": "SaaS growth conversations",
            },
        )
        opportunity = create_opportunity(
            mock_supabase,
            {
                "project_id": project["id"],
                "reddit_post_id": "hist123",
                "subreddit_name": "saas",
                "author": "founder42",
                "title": "Historical opportunity",
                "permalink": "https://reddit.com/r/saas/comments/hist123/test",
                "score": 80,
                "status": "drafting",
            },
        )
        create_reply_draft(
            mock_supabase,
            {
                "project_id": project["id"],
                "opportunity_id": opportunity["id"],
                "content": "Historical draft",
            },
        )
        pipeline = create_auto_pipeline(
            mock_supabase,
            {
                "id": "pipe_zero_counts",
                "project_id": project["id"],
                "website_url": "https://example.com",
                "status": "ready",
                "progress": 100,
                "current_step": "Complete!",
                "brand_summary": "B2B SaaS",
                "personas_generated": 0,
                "keywords_generated": 0,
                "subreddits_found": 0,
                "opportunities_found": 0,
                "drafts_generated": 0,
            },
        )

        resp = client.get(f"/v1/auto-pipeline/{pipeline['id']}")

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["results"]["personas"] == []
        assert payload["results"]["keywords"] == []
        assert payload["results"]["subreddits"] == []
        assert payload["results"]["opportunities"] == []
        assert payload["results"]["drafts"] == []

    def test_list_auto_pipelines_includes_failure_fields(self, authed_client, mock_supabase):
        client, user_data = authed_client
        project = _create_project(mock_supabase, user_data["workspace"]["id"])

        create_auto_pipeline(
            mock_supabase,
            {
                "id": "pipe_failed_1",
                "project_id": project["id"],
                "website_url": "https://broken.example.com",
                "status": "failed",
                "progress": 35,
                "current_step": "Analyzing website content...",
                "error_message": "Could not fetch https://broken.example.com",
                "completed_at": "2026-04-15T10:00:00+00:00",
            },
        )

        resp = client.get(f"/v1/auto-pipeline?project_id={project['id']}")

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["items"][0]["status"] == "failed"
        assert payload["items"][0]["current_step"] == "Analyzing website content..."
        assert payload["items"][0]["error_message"] == "Could not fetch https://broken.example.com"
        assert payload["items"][0]["completed_at"] == "2026-04-15T10:00:00+00:00"
