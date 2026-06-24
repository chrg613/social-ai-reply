"""Tests for the Reddit account-safety copilot.

Covers warm-up budget tiers (pure function), activity counting against the
mock Supabase client, the combined safety assessment with warnings, shadowban
detection with an injected fetch, and the 422 over-budget guard on
``POST /v1/reddit/post``.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx

from app.services.product.account_safety import (
    assess_account_safety,
    check_shadowban,
    compute_posting_budget,
    get_account_activity,
    parse_timestamp,
)

NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)


def _iso_ago(*, days: int = 0, hours: int = 0) -> str:
    return (NOW - timedelta(days=days, hours=hours)).isoformat()


def _account(**overrides) -> dict:
    base = {
        "id": 1,
        "workspace_id": 1,
        "username": "testuser",
        "karma": 0,
        "is_active": True,
    }
    base.update(overrides)
    return base


# ── compute_posting_budget ───────────────────────────────────────


class TestComputePostingBudget:
    def test_new_tier_by_age(self):
        account = _account(karma=5000, account_created_at=_iso_ago(days=10))
        budget = compute_posting_budget(account, now=NOW)
        assert budget == {"daily_cap": 1, "weekly_cap": 3, "tier": "new"}

    def test_new_tier_by_karma(self):
        account = _account(karma=50, account_created_at=_iso_ago(days=400))
        budget = compute_posting_budget(account, now=NOW)
        assert budget == {"daily_cap": 1, "weekly_cap": 3, "tier": "new"}

    def test_warming_tier_by_age(self):
        account = _account(karma=10_000, account_created_at=_iso_ago(days=60))
        budget = compute_posting_budget(account, now=NOW)
        assert budget == {"daily_cap": 3, "weekly_cap": 10, "tier": "warming"}

    def test_warming_tier_by_karma(self):
        account = _account(karma=300, account_created_at=_iso_ago(days=400))
        budget = compute_posting_budget(account, now=NOW)
        assert budget == {"daily_cap": 3, "weekly_cap": 10, "tier": "warming"}

    def test_established_tier(self):
        account = _account(karma=5000, account_created_at=_iso_ago(days=400))
        budget = compute_posting_budget(account, now=NOW)
        assert budget == {"daily_cap": 10, "weekly_cap": 40, "tier": "established"}

    def test_missing_age_uses_karma_alone(self):
        account = _account(karma=5000)
        budget = compute_posting_budget(account, now=NOW)
        assert budget["tier"] == "established"

    def test_missing_everything_is_most_conservative(self):
        budget = compute_posting_budget({"id": 1}, now=NOW)
        assert budget == {"daily_cap": 1, "weekly_cap": 3, "tier": "new"}

    def test_safety_config_overrides_caps_but_not_tier(self):
        account = _account(
            karma=50,
            account_created_at=_iso_ago(days=10),
            safety_config={"daily_cap": 2, "weekly_cap": 6},
        )
        budget = compute_posting_budget(account, now=NOW)
        assert budget == {"daily_cap": 2, "weekly_cap": 6, "tier": "new"}

    def test_invalid_safety_config_values_are_ignored(self):
        account = _account(karma=50, safety_config={"daily_cap": "nope", "weekly_cap": -1})
        budget = compute_posting_budget(account, now=NOW)
        assert budget == {"daily_cap": 1, "weekly_cap": 3, "tier": "new"}

    def test_safety_config_as_json_string(self):
        account = _account(karma=50, safety_config='{"daily_cap": 4}')
        budget = compute_posting_budget(account, now=NOW)
        assert budget["daily_cap"] == 4
        assert budget["weekly_cap"] == 3


# ── parse_timestamp ──────────────────────────────────────────────


class TestParseTimestamp:
    def test_handles_z_suffix_and_naive_and_garbage(self):
        parsed = parse_timestamp("2026-06-10T00:00:00Z")
        assert parsed is not None and parsed.tzinfo is not None
        naive = parse_timestamp("2026-06-10T00:00:00")
        assert naive is not None and naive.tzinfo is not None
        assert parse_timestamp("not-a-date") is None
        assert parse_timestamp(None) is None
        assert parse_timestamp(12345) is None


# ── get_account_activity ─────────────────────────────────────────


def _insert_post(db, account_id, *, subreddit="python", published_at, project_id=1):
    db.table("published_posts").insert(
        {
            "project_id": project_id,
            "reddit_account_id": account_id,
            "type": "comment",
            "subreddit": subreddit,
            "content": "hello",
            "permalink": "https://reddit.com/r/x/comments/abc/",
            "status": "published",
            "published_at": published_at,
        }
    ).execute()


class TestGetAccountActivity:
    def test_counts_today_week_and_per_subreddit(self, mock_supabase):
        # Two posts today, two earlier this week, one outside the window,
        # and one belonging to another account.
        _insert_post(mock_supabase, 1, published_at=_iso_ago(hours=1))
        _insert_post(mock_supabase, 1, published_at=_iso_ago(hours=3), subreddit="Python")
        _insert_post(mock_supabase, 1, published_at=_iso_ago(days=2), subreddit="startups")
        _insert_post(mock_supabase, 1, published_at=_iso_ago(days=5), subreddit="startups")
        _insert_post(mock_supabase, 1, published_at=_iso_ago(days=8))
        _insert_post(mock_supabase, 2, published_at=_iso_ago(hours=1))

        activity = get_account_activity(mock_supabase, 1, now=NOW)
        assert activity["posted_today"] == 2
        assert activity["posted_this_week"] == 4
        assert activity["per_subreddit_week"] == {"python": 2, "startups": 2}

    def test_empty_history(self, mock_supabase):
        activity = get_account_activity(mock_supabase, 1, now=NOW)
        assert activity == {"posted_today": 0, "posted_this_week": 0, "per_subreddit_week": {}}


# ── assess_account_safety ────────────────────────────────────────


class TestAssessAccountSafety:
    def test_clean_established_account_scores_100(self, mock_supabase):
        account = _account(karma=5000, account_created_at=_iso_ago(days=400))
        report = assess_account_safety(mock_supabase, account, now=NOW)
        assert report["score"] == 100
        assert report["tier"] == "established"
        assert report["warnings"] == []
        assert report["shadowban_suspected"] is False
        assert report["posted_today"] == 0

    def test_warnings_and_score_for_risky_account(self, mock_supabase):
        # New-tier account (daily cap 1, weekly cap 3) with 7 posts this week,
        # 6 of them in the same subreddit, one today, plus a suspected shadowban.
        account = _account(karma=50, shadowban_suspected=True)
        _insert_post(mock_supabase, 1, published_at=_iso_ago(hours=1), subreddit="python")
        for day in range(1, 6):
            _insert_post(mock_supabase, 1, published_at=_iso_ago(days=day), subreddit="python")
        _insert_post(mock_supabase, 1, published_at=_iso_ago(days=6), subreddit="startups")

        report = assess_account_safety(mock_supabase, account, now=NOW)
        assert report["posted_today"] == 1
        assert report["posted_this_week"] == 7
        assert report["daily_cap"] == 1
        assert report["weekly_cap"] == 3
        assert report["shadowban_suspected"] is True

        joined = " ".join(report["warnings"])
        assert "Daily cap reached" in joined
        assert "Weekly cap reached" in joined
        assert "r/python: 6 posts this week is 20% above the healthy rate (5/week)" in joined
        assert "Shadowban suspected" in joined
        # 100 - 25 (daily) - 15 (weekly) - 10 (subreddit) - 50 (shadowban), clamped
        assert report["score"] == 0

    def test_score_never_exceeds_bounds(self, mock_supabase):
        account = _account(karma=5000, account_created_at=_iso_ago(days=400))
        report = assess_account_safety(mock_supabase, account, now=NOW)
        assert 0 <= report["score"] <= 100


# ── check_shadowban ──────────────────────────────────────────────


class TestCheckShadowban:
    def test_visible_profile_returns_false(self):
        assert check_shadowban(_account(), fetch=lambda url: 200) is False

    def test_404_on_connected_account_is_suspected(self):
        calls: list[str] = []

        def fetch(url: str) -> int:
            calls.append(url)
            return 404

        assert check_shadowban(_account(), fetch=fetch) is True
        assert calls == ["https://www.reddit.com/user/testuser/about.json"]

    def test_403_on_connected_account_is_suspected(self):
        assert check_shadowban(_account(), fetch=lambda url: 403) is True

    def test_404_on_inactive_account_is_unknown(self):
        assert check_shadowban(_account(is_active=False), fetch=lambda url: 404) is None

    def test_server_error_is_unknown(self):
        assert check_shadowban(_account(), fetch=lambda url: 500) is None

    def test_network_error_is_unknown(self):
        def fetch(url: str) -> int:
            raise httpx.ConnectError("boom")

        assert check_shadowban(_account(), fetch=fetch) is None

    def test_missing_username_is_unknown_without_fetching(self):
        def fetch(url: str) -> int:  # pragma: no cover - must not be called
            raise AssertionError("fetch should not be called")

        assert check_shadowban(_account(username=""), fetch=fetch) is None


# ── Route-level behavior ─────────────────────────────────────────


def _setup_account_and_project(mock_supabase, workspace_id: int) -> tuple[str, int]:
    """Insert a Reddit account (string id, matching route str() casting) and a project."""
    mock_supabase.table("reddit_accounts").insert(
        {
            "id": "1",
            "workspace_id": workspace_id,
            "username": "testuser",
            "karma": 0,
            "is_active": True,
        }
    ).execute()
    project = (
        mock_supabase.table("projects")
        .insert({"workspace_id": workspace_id, "name": "Proj", "slug": "proj", "is_active": True})
        .execute()
        .data[0]
    )
    return "1", project["id"]


class TestPostBudgetGuard:
    def test_post_over_daily_cap_returns_422(self, authed_client, mock_supabase):
        client, user_data = authed_client
        account_id, project_id = _setup_account_and_project(mock_supabase, user_data["workspace"]["id"])
        # New-tier account (karma 0): daily cap is 1, and one post already landed today.
        _insert_post(mock_supabase, account_id, published_at=datetime.now(UTC).isoformat(), project_id=project_id)

        resp = client.post(
            "/v1/reddit/post",
            json={
                "reddit_account_id": 1,
                "project_id": project_id,
                "type": "comment",
                "subreddit": "python",
                "content": "hello there",
                "parent_post_id": "abc123",
            },
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "daily cap" in detail
        assert "override_safety" in detail

    def test_override_safety_bypasses_budget_guard(self, authed_client, mock_supabase):
        client, user_data = authed_client
        account_id, project_id = _setup_account_and_project(mock_supabase, user_data["workspace"]["id"])
        _insert_post(mock_supabase, account_id, published_at=datetime.now(UTC).isoformat(), project_id=project_id)

        resp = client.post(
            "/v1/reddit/post",
            json={
                "reddit_account_id": 1,
                "project_id": project_id,
                "type": "comment",
                "subreddit": "python",
                "content": "hello there",
                "parent_post_id": "abc123",
                "override_safety": True,
            },
        )
        # The guard was bypassed; the request reached the (not yet implemented)
        # Reddit posting client, which maps to 501 — not the 422 safety error.
        assert resp.status_code == 501

    def test_post_under_cap_is_not_blocked_by_safety(self, authed_client, mock_supabase):
        client, user_data = authed_client
        _account_id, project_id = _setup_account_and_project(mock_supabase, user_data["workspace"]["id"])

        resp = client.post(
            "/v1/reddit/post",
            json={
                "reddit_account_id": 1,
                "project_id": project_id,
                "type": "comment",
                "subreddit": "python",
                "content": "hello there",
                "parent_post_id": "abc123",
            },
        )
        assert resp.status_code == 501  # reaches posting layer, no 422


class TestSafetyEndpoint:
    def test_safety_report_with_shadowban_refresh(self, authed_client, mock_supabase):
        client, user_data = authed_client
        account_id, _project_id = _setup_account_and_project(mock_supabase, user_data["workspace"]["id"])

        with patch("app.api.v1.routes.reddit_posting.check_shadowban", return_value=True) as mock_check:
            resp = client.get(f"/v1/reddit/accounts/{account_id}/safety")

        assert resp.status_code == 200
        body = resp.json()
        mock_check.assert_called_once()
        assert body["tier"] == "new"
        assert body["daily_cap"] == 1
        assert body["weekly_cap"] == 3
        assert body["shadowban_suspected"] is True
        assert any("Shadowban suspected" in w for w in body["warnings"])

        # Results persisted to the account row.
        row = mock_supabase.table("reddit_accounts").select("*").eq("id", account_id).execute().data[0]
        assert row["shadowban_suspected"] is True
        assert row.get("last_safety_check_at")

    def test_shadowban_check_throttled_to_once_per_hour(self, authed_client, mock_supabase):
        client, user_data = authed_client
        account_id, _project_id = _setup_account_and_project(mock_supabase, user_data["workspace"]["id"])
        mock_supabase.table("reddit_accounts").update(
            {"last_safety_check_at": datetime.now(UTC).isoformat()}
        ).eq("id", account_id).execute()

        with patch("app.api.v1.routes.reddit_posting.check_shadowban") as mock_check:
            resp = client.get(f"/v1/reddit/accounts/{account_id}/safety")

        assert resp.status_code == 200
        mock_check.assert_not_called()

    def test_safety_404_for_foreign_account(self, authed_client, mock_supabase):
        client, _user_data = authed_client
        mock_supabase.table("reddit_accounts").insert(
            {"id": "99", "workspace_id": 424242, "username": "other", "is_active": True}
        ).execute()
        resp = client.get("/v1/reddit/accounts/99/safety")
        assert resp.status_code == 404
