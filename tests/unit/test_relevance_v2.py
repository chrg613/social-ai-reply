"""Tests for the strict relevance engine v2."""

from datetime import UTC, datetime

import pytest

from app.services.product.relevance_v2 import CandidatePost, RelevanceEngine


class _MockEmbeddingService:
    """Deterministic mock embedding service for reliable relevance tests."""

    def __init__(self, similarity_map=None, default_relevant=0.75, default_irrelevant=0.05):
        self._similarity_map = similarity_map or {}
        self._default_relevant = default_relevant
        self._default_irrelevant = default_irrelevant

    def similarity(self, text_a: str, text_b: str) -> float:
        key = (text_a[:60].lower(), text_b[:60].lower())
        if key in self._similarity_map:
            return self._similarity_map[key]
        # Heuristic fallback based on alphanumeric token overlap
        import re

        words_a = set(re.findall(r"[a-z0-9]+", text_a.lower()))
        words_b = set(re.findall(r"[a-z0-9]+", text_b.lower()))
        overlap = len(words_a & words_b)
        union = len(words_a | words_b)
        if union == 0:
            return self._default_irrelevant
        jaccard = overlap / union
        if jaccard > 0.10:
            return self._default_relevant
        return self._default_irrelevant


@pytest.fixture(autouse=True)
def reset_embedding_singleton():
    """Reset the EmbeddingService singleton so tests don't share state."""
    from app.services.infrastructure.embeddings.service import EmbeddingService

    EmbeddingService._instance = None
    yield
    EmbeddingService._instance = None


def _make_real_estate_company():
    return {
        "name": "RentWise",
        "description": "Rental app with verified listings and no broker fees",
        "category": "real estate",
        "target_audience": "renters, first-time home buyers",
        "pain_points": ["broker fees", "fake listings", "unverified properties", "high deposits"],
        "competitors": ["Zillow", "Apartments.com"],
        "features": ["verified listings", "no broker fees", "direct owner contact"],
    }


def _make_saas_company():
    return {
        "name": "MailFlow",
        "description": "AI-powered email automation for customer follow-ups",
        "category": "saas",
        "target_audience": "sales teams, customer success managers",
        "pain_points": ["manual follow-ups", "forgotten leads", "slow response times"],
        "competitors": ["Mailchimp", "HubSpot"],
        "features": ["AI sequences", "auto-follow-up", "personalized templates"],
    }


class TestRelevanceEngineRealEstate:
    def test_relevant_post_broker_fees(self):
        """Real estate app should match broker fee posts."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="How do I find a flat without broker fees?",
            body="Moving to a new city and tired of paying huge broker fees. Any app for verified rental listings?",
            platform="reddit",
            source_name="realestate",
        )
        company = _make_real_estate_company()
        keywords = [
            {"keyword": "rental app", "type": "core", "weight": 1.0},
            {"keyword": "broker fees", "type": "pain_point", "weight": 1.0},
            {"keyword": "verified listings", "type": "feature", "weight": 1.0},
            {"keyword": "flat without broker", "type": "problem", "weight": 1.0},
        ]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is True
        assert result.relevance_score >= 70
        assert result.semantic_similarity >= 0.45
        assert len(result.matched_keywords) >= 2
        assert result.reason_relevant is not None
        assert "broker" in result.reason_relevant.lower() or "rental" in result.reason_relevant.lower()

    def test_relevant_post_fake_listings(self):
        """Real estate app should match fake listing complaint posts."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="Fake property listings are wasting my time",
            body="Every apartment I contact is already rented. I'm tired of fake listings. Is there a verified property app you can recommend?",
            platform="reddit",
            source_name="realestate",
        )
        company = _make_real_estate_company()
        keywords = [
            {"keyword": "rental app", "type": "core", "weight": 1.0},
            {"keyword": "fake listings", "type": "pain_point", "weight": 1.0},
            {"keyword": "verified property", "type": "feature", "weight": 1.0},
        ]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is True
        assert result.relevance_score >= 60

    def test_relevant_post_verified_listings(self):
        """Should match posts asking for verified listings."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="Any app for verified rental listings?",
            body="Tired of fake listings on Craigslist. Looking for an app that verifies properties before listing them.",
            platform="reddit",
            source_name="apartments",
        )
        company = _make_real_estate_company()
        keywords = [
            {"keyword": "rental app", "type": "core", "weight": 1.0},
            {"keyword": "verified listings", "type": "feature", "weight": 1.0},
            {"keyword": "apartment scam", "type": "pain_point", "weight": 1.0},
            {"keyword": "verified rental listings", "type": "core", "weight": 1.0},
        ]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is True
        assert result.relevance_score >= 70

    def test_irrelevant_gaming_laptop(self):
        """Should NOT match gaming laptop posts."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="Best gaming laptop under 1000",
            body="Need a laptop for gaming. What's the best option?",
            platform="reddit",
            source_name="gaming",
        )
        company = _make_real_estate_company()
        keywords = [
            {"keyword": "rental app", "type": "core", "weight": 1.0},
            {"keyword": "broker fees", "type": "pain_point", "weight": 1.0},
        ]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is False
        assert result.relevance_score < 40
        assert result.rejection_reason is not None

    def test_irrelevant_cooking(self):
        """Should NOT match cooking posts."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="How to cook rice",
            body="What's the best way to cook perfect rice?",
            platform="reddit",
            source_name="cooking",
        )
        company = _make_real_estate_company()
        keywords = [{"keyword": "rental app", "type": "core", "weight": 1.0}]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is False
        assert result.relevance_score < 40

    def test_irrelevant_stock_market(self):
        """Should NOT match stock market posts."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="Stock market prediction",
            body="What do you think about the market next week?",
            platform="reddit",
            source_name="stocks",
        )
        company = _make_real_estate_company()
        keywords = [{"keyword": "rental app", "type": "core", "weight": 1.0}]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is False
        assert result.relevance_score < 40

    def test_irrelevant_job_posting(self):
        """Should NOT match job postings."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="Looking for job in marketing",
            body="Need a marketing job in NYC. 5 years experience.",
            platform="reddit",
            source_name="jobs",
        )
        company = _make_real_estate_company()
        keywords = [{"keyword": "rental app", "type": "core", "weight": 1.0}]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is False
        assert result.relevance_score < 40


class TestRelevanceEngineSaaS:
    def test_relevant_email_automation(self):
        """SaaS email tool should match email automation posts."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="Need a tool to automate customer follow-up emails",
            body="Our sales team is drowning in manual follow-ups. Looking for an AI email sequence tool.",
            platform="reddit",
            source_name="sales",
        )
        company = _make_saas_company()
        keywords = [
            {"keyword": "automate emails", "type": "core", "weight": 1.0},
            {"keyword": "follow-up emails", "type": "pain_point", "weight": 1.0},
            {"keyword": "AI sequences", "type": "feature", "weight": 1.0},
        ]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is True
        assert result.relevance_score >= 70
        assert len(result.matched_keywords) >= 2

    def test_relevant_competitor_alternative(self):
        """Should match competitor alternative posts."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.01,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="Alternative to Mailchimp for AI sequences",
            body="Mailchimp is too expensive and doesn't have good AI automation. What are the alternatives?",
            platform="reddit",
            source_name="email_marketing",
        )
        company = _make_saas_company()
        keywords = [
            {"keyword": "ai automation", "type": "core", "weight": 1.0},
            {"keyword": "alternative to mailchimp", "type": "competitor", "weight": 1.0},
            {"keyword": "AI sequences", "type": "feature", "weight": 1.0},
        ]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is True
        assert result.relevance_score >= 55

    def test_irrelevant_email_iphone(self):
        """Should NOT match iPhone email troubleshooting."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="Email not working on my iPhone",
            body="My Gmail app won't sync. Any ideas?",
            platform="reddit",
            source_name="iphone",
        )
        company = _make_saas_company()
        keywords = [{"keyword": "email automation", "type": "core", "weight": 1.0}]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is False
        assert result.relevance_score < 40

    def test_irrelevant_keyboard(self):
        """Should NOT match keyboard posts."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="Best keyboard for programming",
            body="Need a mechanical keyboard. Recommendations?",
            platform="reddit",
            source_name="programming",
        )
        company = _make_saas_company()
        keywords = [{"keyword": "email automation", "type": "core", "weight": 1.0}]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is False
        assert result.relevance_score < 40


class TestRelevanceEngineEdgeCases:
    def test_single_weak_keyword_rejected(self):
        """Only one weak generic keyword should be rejected."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="I need some help with something",
            body="Can anyone recommend a good tool?",
            platform="reddit",
            source_name="general",
        )
        company = {"name": "ToolX", "category": "productivity"}
        keywords = [{"keyword": "tool", "type": "core", "weight": 1.0}]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is False
        assert result.relevance_score < 60

    def test_spam_post_rejected(self):
        """Spam posts should be rejected."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="Click here to earn $1000 daily!!!",
            body="Limited time offer! Buy now! Click the link!",
            platform="reddit",
            source_name="spam",
        )
        company = {"name": "ToolX", "category": "productivity"}
        keywords = [{"keyword": "tool", "type": "core", "weight": 1.0}]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is False
        assert result.rejection_reason is not None
        assert "spam" in result.rejection_reason.lower()

    def test_job_posting_rejected(self):
        """Job postings should be hard rejected."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="[Hiring] Senior Developer at TechCorp",
            body="We're hiring! Apply now!",
            platform="reddit",
            source_name="jobs",
        )
        company = {"name": "DevTool", "category": "developer_tools"}
        keywords = [{"keyword": "developer tool", "type": "core", "weight": 1.0}]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is False
        assert "job" in result.rejection_reason.lower() or "recruiting" in result.rejection_reason.lower()

    def test_reason_relevant_generated(self):
        """Every kept opportunity must have a reason."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="How do I find a flat without broker fees?",
            body="Moving to a new city...",
            platform="reddit",
            source_name="realestate",
        )
        company = _make_real_estate_company()
        keywords = [{"keyword": "broker fees", "type": "pain_point", "weight": 1.0}]
        result = engine.score(candidate, company, keywords)
        if result.should_keep:
            assert result.reason_relevant is not None
            assert len(result.reason_relevant) > 20

    def test_rejection_reason_generated(self):
        """Every rejected opportunity must have a reason."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="Random unrelated post",
            body="Nothing to do with real estate.",
            platform="reddit",
            source_name="random",
        )
        company = _make_real_estate_company()
        keywords = [{"keyword": "rental app", "type": "core", "weight": 1.0}]
        result = engine.score(candidate, company, keywords)
        if not result.should_keep:
            assert result.rejection_reason is not None
            assert len(result.rejection_reason) > 10

    def test_very_old_post_rejected(self):
        """Posts older than 180 days should be rejected."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="How do I find a flat without broker fees?",
            body="Moving to a new city...",
            platform="reddit",
            source_name="realestate",
            created_at=datetime.now(UTC) - __import__("datetime").timedelta(days=200),
        )
        company = _make_real_estate_company()
        keywords = [{"keyword": "broker fees", "type": "pain_point", "weight": 1.0}]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is False
        assert "older than 180 days" in result.rejection_reason.lower()

    def test_self_promotion_rejected(self):
        """Posts with self-promotion should be rejected."""
        engine = RelevanceEngine(
            relevance_threshold=55,
            semantic_threshold=0.25,
            embedding_service=_MockEmbeddingService(),
        )
        candidate = CandidatePost(
            title="Check out my tool to solve broker fees",
            body="My new project eliminates broker fees for renters. Please take a look.",
            platform="reddit",
            source_name="realestate",
        )
        company = _make_real_estate_company()
        keywords = [{"keyword": "broker fees", "type": "pain_point", "weight": 1.0}]
        result = engine.score(candidate, company, keywords)
        assert result.should_keep is False
        assert "self-promotion" in result.rejection_reason.lower() or "promo" in result.rejection_reason.lower()
