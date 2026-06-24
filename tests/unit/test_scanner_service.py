from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.product.reddit import RedditPost
from app.services.product.scanner import run_scan


def test_run_scan_preserves_original_insert_error_when_opportunity_write_fails(mock_supabase):
    reddit = MagicMock()
    reddit.subreddit_rules.return_value = []
    reddit.search_posts.return_value = [
        RedditPost(
            post_id="abc123",
            subreddit="saas",
            title="How do buyers evaluate verified listings?",
            author="buyer42",
            permalink="https://reddit.com/r/saas/comments/abc123/test",
            body="Trying to avoid fake listings and compare trustworthy options.",
            created_at=datetime.now(UTC),
            num_comments=6,
            score=18,
        )
    ]
    payload = SimpleNamespace(search_window_hours=72, min_score=0, max_posts_per_subreddit=10)
    scored_post = SimpleNamespace(eligible=True, total=95, reasons=["keyword match"], keyword_hits=["buyers"], rule_risk=[])

    with (
        patch("app.services.product.scanner.RedditDiscoveryService", return_value=reddit),
        patch("app.services.product.scanner.get_brand_profile_by_project", return_value={"brand_name": "Example"}),
        patch(
            "app.db.tables.discovery.list_discovery_keywords_for_project",
            return_value=[{"keyword": "buyers", "is_active": True, "priority_score": 90}],
        ),
        patch(
            "app.db.tables.discovery.list_monitored_subreddits_for_project",
            return_value=[{"name": "saas", "is_active": True, "fit_score": 88}],
        ),
        patch("app.services.product.scanner.get_project_search_keywords", return_value=["buyers"]),
        patch("app.services.product.scanner.score_post", return_value=scored_post),
        patch("app.db.tables.discovery.batch_get_opportunities_by_reddit_posts", return_value={}),
        patch("app.services.product.scanner.create_opportunity", side_effect=RuntimeError("insert failed")),
        pytest.raises(RuntimeError, match="insert failed"),
    ):
        run_scan(mock_supabase, {"id": 1}, payload)

    scan_runs = mock_supabase.table("scan_runs").select("*").execute().data

    assert len(scan_runs) == 1
    assert scan_runs[0]["status"] == "error"
    assert "insert failed" in scan_runs[0]["error_message"]


def test_run_scan_marks_discovery_backend_failures_as_fatal(mock_supabase):
    reddit = MagicMock()
    reddit.subreddit_rules.return_value = []
    reddit.search_posts.side_effect = RuntimeError("external search backend unavailable")
    payload = SimpleNamespace(search_window_hours=72, min_score=0, max_posts_per_subreddit=10)

    with (
        patch("app.services.product.scanner.RedditDiscoveryService", return_value=reddit),
        patch("app.services.product.scanner.get_brand_profile_by_project", return_value={"brand_name": "Example"}),
        patch(
            "app.db.tables.discovery.list_discovery_keywords_for_project",
            return_value=[{"keyword": "buyers", "is_active": True, "priority_score": 90}],
        ),
        patch(
            "app.db.tables.discovery.list_monitored_subreddits_for_project",
            return_value=[
                {"name": "saas", "is_active": True, "fit_score": 88},
                {"name": "startups", "is_active": True, "fit_score": 82},
            ],
        ),
        patch("app.services.product.scanner.get_project_search_keywords", return_value=["buyers"]),
    ):
        result = run_scan(mock_supabase, {"id": 1}, payload)

    scan_runs = mock_supabase.table("scan_runs").select("*").execute().data

    assert result["fatal_error"] is True
    assert "All subreddit discovery requests failed" in result["error_message"]
    assert len(scan_runs) == 1
    assert scan_runs[0]["status"] == "completed"
    assert scan_runs[0]["posts_scanned"] == 0
    assert reddit.search_posts.call_count == 2


def test_run_scan_engine_path_persists_v2_fields(mock_supabase):
    reddit = MagicMock()
    reddit.subreddit_rules.return_value = ["No self-promotion or advertising"]
    reddit.search_posts.return_value = [
        RedditPost(
            post_id="xyz789",
            subreddit="saas",
            title="Looking for recommendations to find verified property listings",
            author="buyer42",
            permalink="https://reddit.com/r/saas/comments/xyz789/test",
            body="Can anyone recommend a tool for verified real estate listings? Trying to avoid fake listings.",
            created_at=datetime.now(UTC),
            num_comments=6,
            score=18,
        )
    ]
    payload = SimpleNamespace(search_window_hours=72, min_score=0, max_posts_per_subreddit=10)

    with (
        patch("app.services.product.scanner.RedditDiscoveryService", return_value=reddit),
        patch(
            "app.services.product.scanner.get_brand_profile_by_project",
            return_value={
                "brand_name": "ListingVerify",
                "summary": "Verified real estate listings platform",
                "product_summary": "Find and verify property listings",
                "business_domain": "real estate",
                "target_audience": "home buyers",
            },
        ),
        patch(
            "app.db.tables.discovery.list_discovery_keywords_for_project",
            return_value=[{"keyword": "verified listings", "is_active": True, "priority_score": 90}],
        ),
        patch(
            "app.db.tables.discovery.list_monitored_subreddits_for_project",
            return_value=[{"name": "saas", "is_active": True, "fit_score": 88, "rules_summary": "Be nice"}],
        ),
        patch("app.services.product.scanner.get_project_search_keywords", return_value=["verified listings"]),
        patch("app.db.tables.discovery.batch_get_opportunities_by_reddit_posts", return_value={}),
        patch("app.services.product.scanner.refine_stages_with_llm", return_value={}),
    ):
        result = run_scan(mock_supabase, {"id": 1}, payload)

    assert result["status"] == "completed"
    opportunities = mock_supabase.table("opportunities").select("*").execute().data
    assert len(opportunities) == 1
    opp = opportunities[0]
    # Fields the unified engine must persist — legacy scoring covers most
    assert opp["intent"]
    assert opp["buying_stage"]
    assert isinstance(opp["scoring_breakdown"], dict)
    assert opp.get("semantic_similarity") is not None
    assert isinstance(opp["risk_flags"], list)
    # Explicit rule penalties from the legacy engine survived the port
    assert any("promotional" in r or "rules" in r for r in opp["rule_risk"])
