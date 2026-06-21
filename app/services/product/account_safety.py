"""Reddit account-safety copilot.

Computes warm-up posting budgets for connected Reddit accounts, measures recent
posting activity from ``published_posts``, detects suspected shadowbans, and
combines everything into a 0-100 safety score with actionable warnings.

Posting on a brand-new or low-karma account at full speed is the fastest way to
get it flagged by Reddit's spam filters. The budget tiers here mirror commonly
accepted warm-up guidance:

- ``new``         (age < 30 days or karma < 100):  1 post/day,  3 posts/week
- ``warming``     (age < 90 days or karma < 500):  3 posts/day, 10 posts/week
- ``established`` (everything else):              10 posts/day, 40 posts/week

Per-account overrides live in the ``safety_config`` JSONB column
(``{"daily_cap": ..., "weekly_cap": ...}``).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

from app.core.constants.limits import (
    SAFETY_ESTABLISHED_DAILY_CAP,
    SAFETY_ESTABLISHED_WEEKLY_CAP,
    SAFETY_HEALTHY_SUBREDDIT_WEEKLY_POSTS,
    SAFETY_NEW_ACCOUNT_MAX_AGE_DAYS,
    SAFETY_NEW_ACCOUNT_MIN_KARMA,
    SAFETY_NEW_DAILY_CAP,
    SAFETY_NEW_WEEKLY_CAP,
    SAFETY_WARMING_ACCOUNT_MAX_AGE_DAYS,
    SAFETY_WARMING_ACCOUNT_MIN_KARMA,
    SAFETY_WARMING_DAILY_CAP,
    SAFETY_WARMING_WEEKLY_CAP,
)
from app.db.tables.campaigns import list_published_posts_for_reddit_account
from app.services.infrastructure.http_budget import CircuitOpenError, HttpBudget

if TYPE_CHECKING:
    from collections.abc import Callable

    from supabase import Client

logger = logging.getLogger(__name__)

SHADOWBAN_CHECK_URL_TEMPLATE = "https://www.reddit.com/user/{username}/about.json"
SHADOWBAN_CHECK_TIMEOUT_SECONDS = 10.0
_REDDIT_HOST = "www.reddit.com"
_USER_AGENT = "SignalFlow/1.0 (account-safety)"

# Module-level budget so every shadowban probe in the process shares the same
# per-host throttle/circuit breaker (same pattern as reddit_discovery.py).
_HTTP_BUDGET = HttpBudget()


# ── Timestamp helpers ────────────────────────────────────────────


def parse_timestamp(raw: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (or datetime) into an aware UTC datetime.

    Returns ``None`` when the value is missing or unparseable.
    """
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _account_age_days(account: dict[str, Any], now: datetime) -> int | None:
    created_at = parse_timestamp(account.get("account_created_at"))
    if created_at is None:
        return None
    return max((now - created_at).days, 0)


def _safety_config(account: dict[str, Any]) -> dict[str, Any]:
    raw = account.get("safety_config") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


# ── Posting budget ────────────────────────────────────────────────


def compute_posting_budget(account: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Compute the warm-up posting budget for a Reddit account.

    Pure function over the account row. Missing ``account_created_at`` means
    the age conditions are skipped and the tier is decided by karma alone;
    missing karma is treated as 0 (most conservative).

    Returns ``{"daily_cap": int, "weekly_cap": int, "tier": str}``.
    """
    now = now or datetime.now(UTC)
    karma = int(account.get("karma") or 0)
    age_days = _account_age_days(account, now)

    if (age_days is not None and age_days < SAFETY_NEW_ACCOUNT_MAX_AGE_DAYS) or karma < SAFETY_NEW_ACCOUNT_MIN_KARMA:
        tier, daily_cap, weekly_cap = "new", SAFETY_NEW_DAILY_CAP, SAFETY_NEW_WEEKLY_CAP
    elif (
        age_days is not None and age_days < SAFETY_WARMING_ACCOUNT_MAX_AGE_DAYS
    ) or karma < SAFETY_WARMING_ACCOUNT_MIN_KARMA:
        tier, daily_cap, weekly_cap = "warming", SAFETY_WARMING_DAILY_CAP, SAFETY_WARMING_WEEKLY_CAP
    else:
        tier, daily_cap, weekly_cap = "established", SAFETY_ESTABLISHED_DAILY_CAP, SAFETY_ESTABLISHED_WEEKLY_CAP

    config = _safety_config(account)
    daily_override = _positive_int(config.get("daily_cap"))
    weekly_override = _positive_int(config.get("weekly_cap"))
    if daily_override is not None:
        daily_cap = daily_override
    if weekly_override is not None:
        weekly_cap = weekly_override

    return {"daily_cap": daily_cap, "weekly_cap": weekly_cap, "tier": tier}


# ── Activity ─────────────────────────────────────────────────────


def get_account_activity(db: Client, account_id: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Count recent posting activity for an account from ``published_posts``.

    "Today" is the current UTC calendar day; "this week" is a rolling 7-day
    window. Per-subreddit counts cover the same 7-day window.
    """
    now = now or datetime.now(UTC)
    week_start = now - timedelta(days=7)

    posted_today = 0
    posted_this_week = 0
    per_subreddit_week: dict[str, int] = {}

    for post in list_published_posts_for_reddit_account(db, account_id):
        published_at = parse_timestamp(post.get("published_at") or post.get("created_at"))
        if published_at is None or published_at < week_start:
            continue
        posted_this_week += 1
        subreddit = (post.get("subreddit") or "").lower()
        per_subreddit_week[subreddit] = per_subreddit_week.get(subreddit, 0) + 1
        if published_at.date() == now.date():
            posted_today += 1

    return {
        "posted_today": posted_today,
        "posted_this_week": posted_this_week,
        "per_subreddit_week": per_subreddit_week,
    }


# ── Shadowban detection ──────────────────────────────────────────


def _default_fetch(url: str) -> int:
    """Fetch a URL unauthenticated and return the HTTP status code."""
    _HTTP_BUDGET.acquire(_REDDIT_HOST)
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=SHADOWBAN_CHECK_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
    except httpx.HTTPError:
        _HTTP_BUDGET.record_failure(_REDDIT_HOST)
        raise
    if response.status_code == 429 or response.status_code >= 500:
        _HTTP_BUDGET.record_failure(_REDDIT_HOST)
    else:
        _HTTP_BUDGET.record_success(_REDDIT_HOST)
    return response.status_code


def check_shadowban(account: dict[str, Any], fetch: Callable[[str], int] | None = None) -> bool | None:
    """Probe Reddit's public profile endpoint for shadowban signals.

    A connected (active) account whose public ``about.json`` returns 404/403 is
    very likely shadowbanned or suspended. Returns:

    - ``True``  — profile hidden while the account is connected (suspected)
    - ``False`` — profile publicly visible (200)
    - ``None``  — unknown (network error, rate limit, missing username, or the
      account is no longer active so a hidden profile proves nothing)

    ``fetch`` is injectable for tests: a callable taking the URL and returning
    the HTTP status code (it may raise on transport errors).
    """
    username = (account.get("username") or "").strip()
    if not username:
        return None

    url = SHADOWBAN_CHECK_URL_TEMPLATE.format(username=username)
    fetcher = fetch or _default_fetch
    try:
        status_code = fetcher(url)
    except CircuitOpenError as exc:
        logger.info("Shadowban check skipped for u/%s: %s", username, exc)
        return None
    except Exception as exc:
        logger.info("Shadowban check failed for u/%s: %s", username, exc)
        return None

    if status_code == 200:
        return False
    if status_code in (403, 404) and account.get("is_active", True):
        return True
    return None


# ── Combined assessment ──────────────────────────────────────────


def assess_account_safety(db: Client, account: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Combine budget, activity, and shadowban signal into a safety report.

    Returns a dict with ``score`` (0-100), ``tier``, ``daily_cap``,
    ``weekly_cap``, ``posted_today``, ``posted_this_week``, ``warnings``, and
    ``shadowban_suspected``.
    """
    now = now or datetime.now(UTC)
    budget = compute_posting_budget(account, now=now)
    activity = get_account_activity(db, account["id"], now=now)
    shadowban_suspected = bool(account.get("shadowban_suspected") or False)

    warnings: list[str] = []
    score = 100

    if activity["posted_today"] >= budget["daily_cap"]:
        warnings.append(
            f"Daily cap reached: {activity['posted_today']}/{budget['daily_cap']} posts today "
            f"for this '{budget['tier']}' account. Posting more today risks spam filters."
        )
        score -= 25

    if activity["posted_this_week"] >= budget["weekly_cap"]:
        warnings.append(
            f"Weekly cap reached: {activity['posted_this_week']}/{budget['weekly_cap']} posts "
            f"in the last 7 days for this '{budget['tier']}' account."
        )
        score -= 15

    healthy = SAFETY_HEALTHY_SUBREDDIT_WEEKLY_POSTS
    for subreddit, count in sorted(activity["per_subreddit_week"].items()):
        if count > healthy:
            pct_over = round((count - healthy) / healthy * 100)
            warnings.append(
                f"r/{subreddit}: {count} posts this week is {pct_over}% above the healthy "
                f"rate ({healthy}/week). Moderators may flag this as self-promotion."
            )
            score -= 10

    if shadowban_suspected:
        warnings.append(
            "Shadowban suspected: this account's public profile is not visible on Reddit. "
            "Posts may be silently hidden — verify in an incognito window before posting."
        )
        score -= 50

    return {
        "score": max(0, min(100, score)),
        "tier": budget["tier"],
        "daily_cap": budget["daily_cap"],
        "weekly_cap": budget["weekly_cap"],
        "posted_today": activity["posted_today"],
        "posted_this_week": activity["posted_this_week"],
        "warnings": warnings,
        "shadowban_suspected": shadowban_suspected,
    }
