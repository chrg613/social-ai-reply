from datetime import UTC, datetime

import pytest

from app.core.exceptions import BusinessRuleError
from app.services.product.reddit import RedditPost
from app.services.product.reddit_discovery import RedditDiscoveryService, SearchResult


def test_search_posts_combines_rss_search_and_subreddit_feed(monkeypatch):
    service = RedditDiscoveryService()

    monkeypatch.setattr(
        service,
        "_search_posts_via_external_search",
        lambda keywords, allowed_subreddits=None, limit=20: [
            RedditPost(
                post_id="ext123",
                subreddit="RealEstate",
                title="How do you verify property details before buying?",
                author="buyer42",
                permalink="https://www.reddit.com/r/RealEstate/comments/ext123/thread",
                body="",
                created_at=datetime.now(UTC),
                num_comments=0,
                score=0,
            )
        ],
    )
    monkeypatch.setattr(
        service,
        "_search_posts_in_subreddit_feed",
        lambda subreddit, keywords, limit=20: [
            RedditPost(
                post_id="feed456",
                subreddit=subreddit,
                title="Any checklist for validating apartment listings?",
                author="buyer77",
                permalink=f"https://www.reddit.com/r/{subreddit}/comments/feed456/thread",
                body="",
                created_at=datetime.now(UTC),
                num_comments=0,
                score=0,
            )
        ],
    )

    posts = service.search_posts(
        ["verified property details"],
        subreddits=["RealEstate"],
        limit=5,
    )

    assert [post.post_id for post in posts] == ["ext123", "feed456"]
    assert posts[0].permalink.startswith("https://www.reddit.com/r/RealEstate/comments/")


def test_search_posts_filters_rss_results_to_allowed_subreddits(monkeypatch):
    service = RedditDiscoveryService()

    monkeypatch.setattr(
        service,
        "_search_posts_via_external_search",
        lambda keywords, allowed_subreddits=None, limit=20: [
            RedditPost(
                post_id="good123",
                subreddit="RealEstate",
                title="How do home buyers verify listings?",
                author="user1",
                permalink="https://www.reddit.com/r/RealEstate/comments/good123/thread",
                body="",
                created_at=datetime.now(UTC),
                num_comments=0,
                score=0,
            ),
            RedditPost(
                post_id="bad123",
                subreddit="HBO",
                title="Best HBO episode?",
                author="user1",
                permalink="https://www.reddit.com/r/HBO/comments/bad123/thread",
                body="",
                created_at=datetime.now(UTC),
                num_comments=0,
                score=0,
            ),
        ],
    )
    monkeypatch.setattr(service, "_search_posts_in_subreddit_feed", lambda subreddit, keywords, limit=20: [])

    posts = service.search_posts(["home buyers"], subreddits=["RealEstate"], limit=5)

    assert [post.post_id for post in posts] == ["good123"]


def test_search_subreddits_derives_candidates_from_external_results(monkeypatch):
    service = RedditDiscoveryService()

    # No longer needed to mock _search_subreddits_rss as it does not exist
    # monkeypatch.setattr(
    #     service,
    #     "_search_subreddits_rss",
    #     lambda keyword, limit: [],
    # )
    monkeypatch.setattr(
        service,
        "_search_web",
        lambda query, limit=10: [
            SearchResult(url="https://www.reddit.com/r/saas/comments/abc123/thread", title="SaaS growth", snippet=""),
            SearchResult(url="https://www.reddit.com/r/saas/comments/def456/thread", title="SaaS founders", snippet=""),
            SearchResult(url="https://www.reddit.com/r/AskReddit/comments/ghi789/thread", title="AskReddit", snippet=""),
        ],
    )
    monkeypatch.setattr(
        service,
        "subreddit_about",
        lambda subreddit: {
            "display_name": subreddit,
            "title": "SaaS" if subreddit.lower() == "saas" else "AskReddit",
            "public_description": "Software founders discussing growth" if subreddit.lower() == "saas" else "General prompts",
            "subscribers": 120000 if subreddit.lower() == "saas" else 1000,
        },
    )

    matches = service.search_subreddits("saas growth", limit=2)

    assert [match.name for match in matches] == ["saas", "AskReddit"]


def test_search_posts_returns_empty_when_every_discovery_mode_fails(monkeypatch):
    service = RedditDiscoveryService()

    def raise_rss(keywords, allowed_subreddits=None, limit=20):
        raise BusinessRuleError("RSS search unavailable")

    def raise_feed(subreddit, keywords, limit=20):
        raise BusinessRuleError("subreddit feed unavailable")

    monkeypatch.setattr(service, "_search_posts_via_external_search", raise_rss)
    monkeypatch.setattr(service, "_search_posts_in_subreddit_feed", raise_feed)

    with pytest.raises(BusinessRuleError):
        service.search_posts(["home buyers"], subreddits=["RealEstate"], limit=5)
