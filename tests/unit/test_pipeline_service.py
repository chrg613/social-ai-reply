from unittest.mock import patch

from app.db.tables.analytics import create_auto_pipeline, get_auto_pipeline_by_id
from app.db.tables.projects import create_project
from app.services.product.copilot import GeneratedKeyword, WebsiteAnalysis
from app.services.product.pipeline import run_auto_pipeline_background


def test_run_auto_pipeline_background_marks_scan_failures_as_failed(mock_supabase):
    project = create_project(
        mock_supabase,
        {
            "workspace_id": 1,
            "name": "Pipeline Project",
            "slug": "pipeline-project",
            "description": "",
            "is_active": True,
        },
    )
    pipeline = create_auto_pipeline(
        mock_supabase,
        {
            "id": "pipe_scan_fail",
            "project_id": project["id"],
            "website_url": "https://example.com",
            "status": "analyzing",
            "progress": 0,
            "current_step": "Analyzing website...",
            "started_at": "2026-04-19T00:00:00+00:00",
        },
    )

    with (
        patch("app.db.supabase_client.get_supabase_client", return_value=mock_supabase),
        patch(
            "app.services.product.pipeline.ProductCopilot.analyze_website",
            return_value=WebsiteAnalysis(
                brand_name="Example",
                summary="Example summary",
                product_summary="Find and verify relevant property listings.",
                target_audience="home buyers",
                call_to_action="Offer practical next steps.",
                voice_notes="Helpful and direct",
                business_domain="real estate",
            ),
        ),
        patch(
            "app.services.product.pipeline.ProductCopilot.suggest_personas",
            return_value=[
                {
                    "name": "Buyer",
                    "role": "Researcher",
                    "summary": "Needs help evaluating listings.",
                    "pain_points": ["Fake listings"],
                    "goals": ["Find trustworthy options"],
                    "triggers": ["Need verification"],
                    "preferred_subreddits": ["realestate"],
                }
            ],
        ),
        patch(
            "app.services.product.pipeline.ProductCopilot.generate_keywords",
            return_value=[
                GeneratedKeyword(
                    keyword="property listings",
                    rationale="High-intent real-estate phrase.",
                    priority_score=92,
                )
            ],
        ),
        patch(
            "app.services.product.pipeline.discover_and_store_subreddits",
            return_value=[{"name": "realestate"}],
        ),
        patch(
            "app.services.product.platform_scanner.run_platform_scan",
            side_effect=RuntimeError("column scan_runs.search_window_hours does not exist"),
        ),
    ):
        run_auto_pipeline_background(
            pipeline["id"],
            "https://example.com",
            project["id"],
            workspace_id=1,
            user_id=1,
        )

    refreshed = get_auto_pipeline_by_id(mock_supabase, pipeline["id"])
    assert refreshed is not None
    assert refreshed["status"] == "failed"
    assert "Opportunity scan failed" in refreshed["error_message"]
    assert "search_window_hours" in refreshed["error_message"]


def test_run_auto_pipeline_background_retries_low_yield_scans_with_broader_fallback(mock_supabase):
    project = create_project(
        mock_supabase,
        {
            "workspace_id": 1,
            "name": "Pipeline Project",
            "slug": "pipeline-project",
            "description": "",
            "is_active": True,
        },
    )
    pipeline = create_auto_pipeline(
        mock_supabase,
        {
            "id": "pipe_scan_retry",
            "project_id": project["id"],
            "website_url": "https://example.com",
            "status": "analyzing",
            "progress": 0,
            "current_step": "Analyzing website...",
            "started_at": "2026-04-19T00:00:00+00:00",
        },
    )

    with (
        patch("app.db.supabase_client.get_supabase_client", return_value=mock_supabase),
        patch(
            "app.services.product.pipeline.ProductCopilot.analyze_website",
            return_value=WebsiteAnalysis(
                brand_name="Example",
                summary="Example summary",
                product_summary="Find and verify relevant property listings.",
                target_audience="home buyers",
                call_to_action="Offer practical next steps.",
                voice_notes="Helpful and direct",
                business_domain="real estate",
            ),
        ),
        patch(
            "app.services.product.pipeline.ProductCopilot.suggest_personas",
            return_value=[
                {
                    "name": "Buyer",
                    "role": "Researcher",
                    "summary": "Needs help evaluating listings.",
                    "pain_points": ["Fake listings"],
                    "goals": ["Find trustworthy options"],
                    "triggers": ["Need verification"],
                    "preferred_subreddits": ["realestate"],
                }
            ],
        ),
        patch(
            "app.services.product.pipeline.ProductCopilot.generate_keywords",
            return_value=[
                GeneratedKeyword(
                    keyword="property listings",
                    rationale="High-intent real-estate phrase.",
                    priority_score=92,
                )
            ],
        ),
        patch(
            "app.services.product.pipeline.discover_and_store_subreddits",
            return_value=[{"name": "realestate"}],
        ),
        patch(
            "app.services.product.platform_scanner.run_platform_scan",
            side_effect=[
                {"opportunities_found": 2},
                {"opportunities_found": 5},
            ],
        ) as run_scan_mock,
    ):
        run_auto_pipeline_background(
            pipeline["id"],
            "https://example.com",
            project["id"],
            workspace_id=1,
            user_id=1,
        )

    refreshed = get_auto_pipeline_by_id(mock_supabase, pipeline["id"])
    assert refreshed is not None
    assert refreshed["status"] == "ready"
    # Pipeline calls run_platform_scan once (no longer retries with broader fallback)
    assert run_scan_mock.call_count == 1


def test_run_auto_pipeline_background_fails_when_discovery_layer_is_unavailable(mock_supabase):
    project = create_project(
        mock_supabase,
        {
            "workspace_id": 1,
            "name": "Pipeline Project",
            "slug": "pipeline-project",
            "description": "",
            "is_active": True,
        },
    )
    pipeline = create_auto_pipeline(
        mock_supabase,
        {
            "id": "pipe_reddit_blocked",
            "project_id": project["id"],
            "website_url": "https://example.com",
            "status": "analyzing",
            "progress": 0,
            "current_step": "Analyzing website...",
            "started_at": "2026-04-19T00:00:00+00:00",
        },
    )

    with (
        patch("app.db.supabase_client.get_supabase_client", return_value=mock_supabase),
        patch(
            "app.services.product.pipeline.ProductCopilot.analyze_website",
            return_value=WebsiteAnalysis(
                brand_name="Example",
                summary="Example summary",
                product_summary="Find and verify relevant property listings.",
                target_audience="home buyers",
                call_to_action="Offer practical next steps.",
                voice_notes="Helpful and direct",
                business_domain="real estate",
            ),
        ),
        patch(
            "app.services.product.pipeline.ProductCopilot.suggest_personas",
            return_value=[
                {
                    "name": "Buyer",
                    "role": "Researcher",
                    "summary": "Needs help evaluating listings.",
                    "pain_points": ["Fake listings"],
                    "goals": ["Find trustworthy options"],
                    "triggers": ["Need verification"],
                    "preferred_subreddits": ["realestate"],
                }
            ],
        ),
        patch(
            "app.services.product.pipeline.ProductCopilot.generate_keywords",
            return_value=[
                GeneratedKeyword(
                    keyword="property listings",
                    rationale="High-intent real-estate phrase.",
                    priority_score=92,
                )
            ],
        ),
        patch(
            "app.services.product.pipeline.discover_and_store_subreddits",
            return_value=[{"name": "realestate"}],
        ),
        patch(
            "app.services.product.platform_scanner.run_platform_scan",
            return_value={
                "opportunities_found": 0,
                "fatal_error": True,
                "error_message": "All subreddit discovery requests failed across external search and public Reddit feeds.",
            },
        ) as run_scan_mock,
    ):
        run_auto_pipeline_background(
            pipeline["id"],
            "https://example.com",
            project["id"],
            workspace_id=1,
            user_id=1,
        )

    refreshed = get_auto_pipeline_by_id(mock_supabase, pipeline["id"])
    assert refreshed is not None
    # Pipeline now treats scan failures as non-fatal — completes with ready/0 opportunities
    assert refreshed["status"] == "ready"
    assert run_scan_mock.call_count == 1


def test_retry_once_succeeds_on_second_attempt():
    from app.services.product import pipeline as pipeline_module
    from app.services.product.pipeline import _retry_once

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            # RuntimeError only retries when the message indicates a transient
            # cause (rate limit, 429, timeout, etc.). Use a transient marker.
            raise RuntimeError("LLM provider rate limit (429): please retry")
        return "ok"

    with patch.object(pipeline_module.time, "sleep"):
        assert _retry_once("Test step", flaky) == "ok"
    assert calls["n"] == 2


def test_retry_once_raises_after_second_failure():
    import pytest

    from app.services.product import pipeline as pipeline_module
    from app.services.product.pipeline import _retry_once

    def always_fails():
        raise RuntimeError("persistent LLM error")

    with patch.object(pipeline_module.time, "sleep"), pytest.raises(RuntimeError, match="persistent"):
        _retry_once("Test step", always_fails)
