"""Tests for the keyword expansion service."""

import pytest

from app.services.product.keyword_expansion import (
    KeywordExpansionService,
    _deduplicate_keywords,
    _derive_actions,
    _expand_template,
    _normalize_list,
)


@pytest.fixture
def rich_company_profile():
    return {
        "name": "RentWise",
        "description": "Rental app with verified listings and no broker fees for busy renters",
        "category": "real estate",
        "target_audience": "renters, first-time home buyers",
        "features": ["verified listings", "no broker fees", "direct owner contact"],
        "benefits": ["save money", "avoid scams", "find apartments faster"],
        "pain_points": ["broker fees", "fake listings", "unverified properties", "high deposits"],
        "competitors": ["Zillow", "Apartments.com"],
        "geography": "New York",
    }


@pytest.fixture
def minimal_company_profile():
    return {
        "name": "ToolX",
        "category": "productivity",
    }


class TestKeywordExpansion:
    def test_generates_many_keywords(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        assert len(keywords) >= 50

    def test_core_keywords_have_higher_weight(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        core_keywords = [kw for kw in keywords if kw["type"] == "core"]
        assert len(core_keywords) > 0
        for kw in core_keywords:
            assert kw["weight"] == 1.5

    def test_pain_point_phrases_generated(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        pain_keywords = [kw for kw in keywords if kw["type"] == "pain_point"]
        assert len(pain_keywords) > 0
        # Should include template-generated phrases
        phrases = {kw["keyword"] for kw in pain_keywords}
        assert any("how to solve" in ph for ph in phrases)
        assert any("tired of" in ph for ph in phrases)
        assert any("frustrated with" in ph for ph in phrases)

    def test_competitor_phrases_generated(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        comp_keywords = [kw for kw in keywords if kw["type"] == "competitor"]
        assert len(comp_keywords) > 0
        phrases = {kw["keyword"] for kw in comp_keywords}
        assert any("alternative to zillow" in ph.lower() for ph in phrases)
        assert any("better than zillow" in ph.lower() for ph in phrases)

    def test_location_phrases_when_geography_present(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        loc_keywords = [kw for kw in keywords if kw["type"] == "location"]
        assert len(loc_keywords) > 0
        phrases = {kw["keyword"] for kw in loc_keywords}
        assert any("new york" in ph.lower() for ph in phrases)

    def test_no_location_phrases_without_geography(self, rich_company_profile):
        profile = dict(rich_company_profile)
        profile.pop("geography")
        service = KeywordExpansionService()
        keywords = service.expand(profile)
        loc_keywords = [kw for kw in keywords if kw["type"] == "location"]
        assert len(loc_keywords) == 0

    def test_deduplicates_keywords(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        seen = set()
        for kw in keywords:
            key = (kw["keyword"].lower().strip(), kw["type"])
            assert key not in seen, f"Duplicate keyword: {key}"
            seen.add(key)

    def test_feature_phrases_generated(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        feat_keywords = [kw for kw in keywords if kw["type"] == "feature"]
        assert len(feat_keywords) > 0
        phrases = {kw["keyword"] for kw in feat_keywords}
        assert any("verified listings" in ph for ph in phrases)
        assert any("no broker fees" in ph for ph in phrases)

    def test_question_phrases_generated(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        q_keywords = [kw for kw in keywords if kw["type"] == "question"]
        assert len(q_keywords) > 0

    def test_buying_intent_phrases_generated(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        bi_keywords = [kw for kw in keywords if kw["type"] == "buying_intent"]
        assert len(bi_keywords) > 0
        phrases = {kw["keyword"] for kw in bi_keywords}
        assert any("looking for real estate" in ph for ph in phrases)

    def test_minimal_profile_still_generates_keywords(self, minimal_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(minimal_company_profile)
        assert len(keywords) > 0
        core_keywords = [kw for kw in keywords if kw["type"] == "core"]
        assert len(core_keywords) > 0

    def test_keyword_weights_are_positive(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        for kw in keywords:
            assert kw["weight"] > 0

    def test_sources_populated(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        for kw in keywords:
            assert kw.get("source") is not None
            assert len(kw["source"]) > 0


class TestSearchQueryGeneration:
    def test_reddit_queries(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        queries = service.generate_search_queries(keywords, platform="reddit")
        assert len(queries) > 0
        assert any("site:reddit.com" in q for q in queries)
        assert any("subreddit:" in q for q in queries)

    def test_hn_queries(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        queries = service.generate_search_queries(keywords, platform="hn")
        assert len(queries) > 0
        assert any("site:news.ycombinator.com" in q for q in queries)
        assert any("Ask HN" in q for q in queries)

    def test_seo_queries(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        queries = service.generate_search_queries(keywords, platform="seo")
        assert len(queries) > 0
        assert any("tools" in q or "best" in q or "review" in q or "alternative" in q for q in queries)

    def test_x_queries(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        queries = service.generate_search_queries(keywords, platform="x")
        assert len(queries) > 0
        assert any("-filter:retweets" in q for q in queries)

    def test_linkedin_queries(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        queries = service.generate_search_queries(keywords, platform="linkedin")
        assert len(queries) > 0
        assert any("post" in q or "insights" in q for q in queries)

    def test_all_platforms_when_none_specified(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        queries = service.generate_search_queries(keywords, platform=None)
        assert len(queries) > 0
        # Should contain queries from multiple platforms
        platforms_found = set()
        for q in queries:
            if "reddit" in q:
                platforms_found.add("reddit")
            if "ycombinator" in q:
                platforms_found.add("hn")
            if "-filter:retweets" in q:
                platforms_found.add("x")
            if "linkedin" in q:
                platforms_found.add("linkedin")
        assert len(platforms_found) >= 2

    def test_deduplicates_queries(self, rich_company_profile):
        service = KeywordExpansionService()
        keywords = service.expand(rich_company_profile)
        queries = service.generate_search_queries(keywords, platform="reddit")
        assert len(queries) == len(set(queries))


class TestHelpers:
    def test_normalize_list_from_string(self):
        assert _normalize_list("a, b, c") == ["a", "b", "c"]

    def test_normalize_list_from_list(self):
        assert _normalize_list(["a", "b", "c"]) == ["a", "b", "c"]

    def test_normalize_list_none(self):
        assert _normalize_list(None) == []

    def test_expand_template_basic(self):
        ctx = {"product_name": "RentWise", "category": "real estate"}
        assert _expand_template("{product_name} {category}", ctx) == "RentWise real estate"

    def test_expand_template_missing_key(self):
        ctx = {"product_name": "RentWise"}
        assert _expand_template("{product_name} {category}", ctx) == "RentWise {category}"

    def test_deduplicate_keywords(self):
        keywords = [
            {"keyword": "RentWise", "type": "core", "weight": 1.0},
            {"keyword": "rentwise", "type": "core", "weight": 1.5},
            {"keyword": "RentWise", "type": "competitor", "weight": 1.0},
        ]
        deduped = _deduplicate_keywords(keywords)
        assert len(deduped) == 2
        assert deduped[0]["keyword"] == "RentWise"
        assert deduped[0]["weight"] == 1.0

    def test_derive_actions(self):
        actions = _derive_actions(
            "Save time and avoid errors with automated workflows",
            ["save time", "avoid errors"],
            ["automated workflows", "real-time sync"],
        )
        assert len(actions) > 0
        assert any("save" in a for a in actions)
        assert any("avoid" in a for a in actions)

    def test_derive_actions_fallback(self):
        actions = _derive_actions("", [], [])
        assert actions == ["find", "manage", "solve", "improve"]
