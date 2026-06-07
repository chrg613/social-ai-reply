"""Strict relevance engine (v2) — the core gatekeeper of the platform.

Rejects unrelated posts via a weighted scoring formula and hard-reject rules.
Uses heuristic intent classification and optional semantic embeddings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import get_settings
from app.services.infrastructure.embeddings import EmbeddingService
from app.services.product.intent_classifier import IntentResult, classify_intent
from app.services.product.relevance import (
    find_self_promo_signals,
    normalize_phrase,
    tokenize,
)

logger = logging.getLogger(__name__)

# ── Keyword-type weight map ──────────────────────────────────────────
_KEYWORD_TYPE_WEIGHTS = {
    "core": 3.0,
    "pain_point": 2.5,
    "problem": 2.5,
    "buying_intent": 2.0,
    "competitor": 1.5,
    "alternative": 1.5,
    "audience": 1.0,
    "location": 1.0,
    "feature": 1.0,
}

_INTENT_SCORE_MAP = {
    "looking_for_recommendation": 100,
    "asking_for_help": 90,
    "complaining_about_competitor": 95,
    "looking_for_alternative": 95,
    "buyer_research": 85,
    "comparison": 80,
    "pain_point_discussion": 85,
    "asking_how_to": 70,
    "launch_opportunity": 60,
    "seo_content_gap": 50,
    "geo_visibility_gap": 50,
    "irrelevant": 20,
    "spam": 0,
    "unsafe": 0,
}

_JOB_POST_TERMS = {
    "hiring", "we are hiring", "join our team", "open position",
    "job opening", "career opportunity", "full-time", "part-time",
    "contract role", "remote job", "on-site", "salary",
    "apply now", "send your resume", "job description",
}

_NEWS_ONLY_TERMS = {
    "breaking", "just announced", "report says", "according to",
    "official statement", "press release", "news article",
}

_ADULT_ILLEGAL_TERMS = {
    "nsfw", "onlyfans", "escort", "prostitut",
    "drug deal", "buy drugs", "sell drugs", "counterfeit",
    "fake passport", "stolen credit card",
}


@dataclass
class CandidatePost:
    title: str
    body: str
    platform: str  # reddit, hackernews, x, linkedin, etc.
    source_name: str  # subreddit name, HN, etc.
    upvotes: int = 0
    comments_count: int = 0
    created_at: datetime | None = None
    author: str = ""
    post_url: str = ""


@dataclass
class RelevanceResult:
    relevance_score: int  # 0-100
    semantic_similarity: float  # 0.0-1.0
    matched_keywords: list[str]
    intent: str
    reason_relevant: str
    risk_flags: list[str]
    should_keep: bool
    rejection_reason: str | None
    scoring_breakdown: dict[str, float] = field(default_factory=dict)


class RelevanceEngine:
    """Core relevance engine that scores and gates candidate posts."""

    def __init__(
        self,
        relevance_threshold: int | None = None,
        semantic_threshold: float | None = None,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        settings = get_settings()
        self.relevance_threshold = relevance_threshold if relevance_threshold is not None else settings.relevance_threshold
        self.semantic_threshold = semantic_threshold if semantic_threshold is not None else settings.semantic_threshold
        self._embedding = embedding_service or EmbeddingService(model_name=settings.embedding_model)

    # ── Public API ─────────────────────────────────────────────────────

    def score(
        self,
        candidate: CandidatePost,
        brand_profile: dict[str, Any],
        keywords: list[dict[str, Any]],
    ) -> RelevanceResult:
        """Score a candidate post and decide whether it should be kept.

        Args:
            candidate: The post to evaluate.
            brand_profile: Dict with keys like ``name``, ``description``,
                ``pain_points`` (list), ``category``, ``target_audience``,
                ``competitors`` (list).
            keywords: List of keyword dicts with ``keyword``, ``type``,
                and optionally ``weight`` keys.

        Returns:
            RelevanceResult with full scoring breakdown.
        """
        full_text = normalize_phrase(f"{candidate.title} {candidate.body}")
        intent_result = classify_intent(full_text, brand_profile=brand_profile)

        # ── Component scores ──────────────────────────────────────────
        keyword_score, matched_keywords = self._keyword_score(full_text, keywords)
        semantic_sim = self._semantic_similarity(candidate, brand_profile)
        semantic_score = semantic_sim * 100
        intent_score = _INTENT_SCORE_MAP.get(intent_result.intent, 20)
        pain_point_score = self._pain_point_score(full_text, brand_profile)
        source_fit_score = self._source_fit_score(candidate)
        freshness_score = self._freshness_score(candidate.created_at)

        # ── Penalties ─────────────────────────────────────────────────
        spam_risk_penalty = self._spam_risk_penalty(full_text, intent_result)
        competitor_irrelevant_penalty = self._competitor_irrelevant_penalty(
            full_text, intent_result, brand_profile,
        )
        generic_content_penalty = self._generic_content_penalty(full_text, matched_keywords)
        low_confidence_penalty = self._low_confidence_penalty(intent_result)
        negative_community_rule_penalty = self._negative_community_rule_penalty(candidate)

        penalties = (
            spam_risk_penalty
            + competitor_irrelevant_penalty
            + generic_content_penalty
            + low_confidence_penalty
            + negative_community_rule_penalty
        )

        base_score = (
            keyword_score * 0.25
            + semantic_score * 0.30
            + intent_score * 0.20
            + pain_point_score * 0.10
            + source_fit_score * 0.10
            + freshness_score * 0.05
        )

        final_score = max(0, min(100, int(round(base_score - penalties))))

        # ── Risk flags ────────────────────────────────────────────────
        risk_flags: list[str] = []
        if spam_risk_penalty > 0:
            risk_flags.append("spam_risk")
        if competitor_irrelevant_penalty > 0:
            risk_flags.append("competitor_mention_without_context")
        if generic_content_penalty > 0:
            risk_flags.append("generic_content")
        if low_confidence_penalty > 0:
            risk_flags.append("low_intent_confidence")
        if negative_community_rule_penalty > 0:
            risk_flags.append("restrictive_community_rules")
        if intent_result.intent in ("spam", "unsafe"):
            risk_flags.append(f"intent_{intent_result.intent}")

        # ── Hard reject evaluation ────────────────────────────────────
        should_keep, rejection_reason = self._evaluate_hard_rejects(
            candidate=candidate,
            final_score=final_score,
            semantic_sim=semantic_sim,
            matched_keywords=matched_keywords,
            keyword_score=keyword_score,
            semantic_score=semantic_score,
            intent_result=intent_result,
            full_text=full_text,
            brand_profile=brand_profile,
        )

        # ── Reason generation ───────────────────────────────────────
        reason_relevant = ""
        if should_keep:
            pain_points = brand_profile.get("pain_points", [])
            top_pain = pain_points[0] if pain_points else "this need"
            intent_desc = self._intent_description(intent_result.intent)
            reason_relevant = (
                f"This is relevant because the user is {intent_desc}, "
                f"your product solves {top_pain}, matched keywords are "
                f"{', '.join(matched_keywords[:5])}, and the post is in a relevant community {candidate.source_name}."
            )

        breakdown = {
            "keyword_score": round(keyword_score, 2),
            "semantic_score": round(semantic_score, 2),
            "intent_score": round(intent_score, 2),
            "pain_point_score": round(pain_point_score, 2),
            "source_fit_score": round(source_fit_score, 2),
            "freshness_score": round(freshness_score, 2),
            "base_score": round(base_score, 2),
            "spam_risk_penalty": spam_risk_penalty,
            "competitor_irrelevant_penalty": competitor_irrelevant_penalty,
            "generic_content_penalty": generic_content_penalty,
            "low_confidence_penalty": low_confidence_penalty,
            "negative_community_rule_penalty": negative_community_rule_penalty,
            "total_penalties": penalties,
            "final_score": final_score,
        }

        return RelevanceResult(
            relevance_score=final_score,
            semantic_similarity=round(semantic_sim, 3),
            matched_keywords=matched_keywords,
            intent=intent_result.intent,
            reason_relevant=reason_relevant,
            risk_flags=risk_flags,
            should_keep=should_keep,
            rejection_reason=rejection_reason,
            scoring_breakdown=breakdown,
        )

    # ── Scoring components ───────────────────────────────────────────

    def _keyword_score(
        self,
        full_text: str,
        keywords: list[dict[str, Any]],
    ) -> tuple[float, list[str]]:
        """Score 0-100 based on weighted keyword matches."""
        if not keywords:
            return 0.0, []

        matched: list[str] = []
        total_weight = 0.0
        earned_weight = 0.0

        for kw in keywords:
            keyword_str = normalize_phrase(str(kw.get("keyword", "")))
            kw_type = str(kw.get("type", "")).lower().strip()
            weight = float(kw.get("weight", 1.0)) * _KEYWORD_TYPE_WEIGHTS.get(kw_type, 1.0)

            if not keyword_str or weight <= 0:
                continue

            total_weight += weight

            if keyword_str in full_text:
                matched.append(keyword_str)
                earned_weight += weight
                continue

            # Partial match for multi-word keywords
            kw_tokens = keyword_str.split()
            if len(kw_tokens) > 1:
                text_tokens = set(tokenize(full_text))
                non_generic = [
                    t for t in kw_tokens
                    if t not in {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with"}
                ]
                if non_generic and all(t in text_tokens for t in non_generic):
                    matched.append(keyword_str)
                    earned_weight += weight * 0.7  # partial match gets 70%

        if total_weight == 0:
            return 0.0, []

        score = (earned_weight / total_weight) * 100
        return min(score, 100.0), list(dict.fromkeys(matched))  # dedupe preserving order

    def _semantic_similarity(
        self,
        candidate: CandidatePost,
        brand_profile: dict[str, Any],
    ) -> float:
        """Compute cosine similarity between brand description and post text."""
        brand_text = " ".join(filter(None, [
            brand_profile.get("name", ""),
            brand_profile.get("description", ""),
            " ".join(brand_profile.get("pain_points", [])),
            brand_profile.get("key_benefits", ""),
        ]))
        brand_text = brand_text.strip()
        post_text = f"{candidate.title} {candidate.body}".strip()

        if not brand_text or not post_text:
            return 0.0

        try:
            return self._embedding.similarity(brand_text, post_text)
        except Exception as exc:
            logger.warning("Embedding similarity failed (%s); falling back to keyword overlap.", exc)
            return self._keyword_overlap_proxy(brand_text, post_text)

    @staticmethod
    def _keyword_overlap_proxy(text_a: str, text_b: str) -> float:
        """Fallback cosine proxy using Jaccard-ish token overlap."""
        tokens_a = set(tokenize(text_a))
        tokens_b = set(tokenize(text_b))
        if not tokens_a or not tokens_b:
            return 0.0
        overlap = len(tokens_a & tokens_b)
        union = len(tokens_a | tokens_b)
        if union == 0:
            return 0.0
        # Scale to roughly semantic similarity range (0.2-0.8 typical)
        jaccard = overlap / union
        return min(jaccard * 3.0, 1.0)

    @staticmethod
    def _pain_point_score(full_text: str, brand_profile: dict[str, Any]) -> float:
        """Score 0-100 based on overlap with brand pain points."""
        pain_points = brand_profile.get("pain_points", [])
        if not pain_points:
            return 50.0  # neutral when none defined

        matched = 0
        for pp in pain_points:
            normalized_pp = normalize_phrase(str(pp))
            if not normalized_pp:
                continue
            if normalized_pp in full_text:
                matched += 1
                continue
            # Fuzzy: all non-trivial tokens present
            pp_tokens = [t for t in tokenize(normalized_pp) if len(t) >= 3]
            text_tokens = set(tokenize(full_text))
            if pp_tokens and all(t in text_tokens for t in pp_tokens):
                matched += 1

        return min((matched / len(pain_points)) * 100, 100.0)

    @staticmethod
    def _source_fit_score(candidate: CandidatePost) -> float:
        """Score 0-100 based on platform/source fit."""
        platform = candidate.platform.lower().strip()
        source = candidate.source_name.lower().strip()

        if platform == "reddit":
            # If subreddit is known off-topic, penalise
            if source in {"askreddit", "funny", "memes", "gaming", "movies"}:
                return 20.0
            return 70.0
        if platform in {"hackernews", "hn", "hacker news"}:
            return 80.0
        if platform in {"x", "twitter", "linkedin"}:
            return 45.0
        return 50.0

    @staticmethod
    def _freshness_score(created_at: datetime | None) -> float:
        """Score 0-100 based on post age."""
        if created_at is None:
            return 50.0
        now = datetime.now(UTC)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        age = now - created_at
        if age <= timedelta(days=1):
            return 100.0
        if age <= timedelta(days=7):
            return 80.0
        if age <= timedelta(days=30):
            return 60.0
        if age <= timedelta(days=90):
            return 40.0
        return 20.0

    # ── Penalties ──────────────────────────────────────────────────────

    @staticmethod
    def _spam_risk_penalty(full_text: str, intent_result: IntentResult) -> float:
        if intent_result.intent == "spam":
            return 15.0
        spam_signals = 0
        for term in ["click here", "buy now", "limited time", "free money", "earn $"]:
            if term in full_text:
                spam_signals += 1
        return min(spam_signals * 5, 10.0)

    def _competitor_irrelevant_penalty(
        self,
        full_text: str,
        intent_result: IntentResult,
        brand_profile: dict[str, Any],
    ) -> float:
        competitors = brand_profile.get("competitors", [])
        if not competitors:
            return 0.0
        comp_mentions = sum(
            1 for c in competitors
            if normalize_phrase(c) in full_text
        )
        if comp_mentions == 0:
            return 0.0
        # If intent is already alternative/complaint, no penalty
        if intent_result.intent in ("looking_for_alternative", "complaining_about_competitor"):
            return 0.0
        return min(comp_mentions * 5, 10.0)

    @staticmethod
    def _generic_content_penalty(full_text: str, matched_keywords: list[str]) -> float:
        tokens = tokenize(full_text)
        if len(tokens) < 5:
            return 8.0
        if len(matched_keywords) == 1:
            kw = matched_keywords[0]
            if len(kw.split()) == 1 and kw.lower() in {
                "help", "tool", "app", "best", "good", "great",
            }:
                return 6.0
        return 0.0

    @staticmethod
    def _low_confidence_penalty(intent_result: IntentResult) -> float:
        if intent_result.intent in ("spam", "unsafe"):
            return 10.0
        if intent_result.intent == "irrelevant" and intent_result.confidence > 0.5:
            return 8.0
        if intent_result.confidence < 0.3:
            return 5.0
        return 0.0

    @staticmethod
    def _negative_community_rule_penalty(candidate: CandidatePost) -> float:
        # Simple heuristic based on platform norms
        if candidate.platform.lower() in {"hackernews", "hn"}:
            # HN is strict but product recommendations are welcome
            return 0.0
        if candidate.source_name.lower() in {
            "startups", "entrepreneur", "saas", "marketing",
        }:
            return 0.0
        if candidate.source_name.lower() in {
            "personalfinance", "lifeprotips", "askreddit",
        }:
            return 3.0
        return 0.0

    # ── Hard reject rules ──────────────────────────────────────────────

    def _evaluate_hard_rejects(
        self,
        *,
        candidate: CandidatePost,
        final_score: int,
        semantic_sim: float,
        matched_keywords: list[str],
        keyword_score: float,
        semantic_score: float,
        intent_result: IntentResult,
        full_text: str,
        brand_profile: dict[str, Any],
    ) -> tuple[bool, str | None]:
        reasons: list[str] = []

        if final_score < self.relevance_threshold:
            reasons.append(
                f"final score {final_score} below threshold {self.relevance_threshold}"
            )

        if semantic_sim < self.semantic_threshold:
            reasons.append(
                f"semantic similarity {semantic_sim:.2f} below threshold {self.semantic_threshold}"
            )

        # Only 1 weak generic keyword AND semantic < 0.3
        if len(matched_keywords) == 1 and semantic_sim < 0.3:
            kw = matched_keywords[0]
            if len(kw.split()) == 1 and kw.lower() in {
                "help", "tool", "app", "best", "good", "great",
            }:
                reasons.append("only one weak generic keyword with low semantic match")

        if intent_result.intent == "irrelevant" and intent_result.confidence > 0.6:
            reasons.append(f"intent is irrelevant with high confidence ({intent_result.confidence})")

        if intent_result.intent == "spam":
            reasons.append("intent classified as spam")
        if intent_result.intent == "unsafe":
            reasons.append("intent classified as unsafe")

        # Purely news with no engagement opportunity
        news_signals = sum(1 for term in _NEWS_ONLY_TERMS if term in full_text)
        if news_signals >= 2 and candidate.comments_count < 3:
            reasons.append("purely news with no engagement opportunity")

        # Job posting (unless recruiting-related)
        job_signals = sum(1 for term in _JOB_POST_TERMS if term in full_text)
        if job_signals >= 2:
            category = str(brand_profile.get("category", "")).lower()
            if "recruit" not in category and "hr" not in category and "job" not in category:
                reasons.append("job posting and product is not recruiting-related")

        # Adult / illegal / hate
        adult_illegal = sum(1 for term in _ADULT_ILLEGAL_TERMS if term in full_text)
        if adult_illegal >= 1:
            reasons.append("adult, illegal, or unsafe content detected")

        # Too old (>180 days)
        if candidate.created_at is not None:
            now = datetime.now(UTC)
            created = candidate.created_at if candidate.created_at.tzinfo else candidate.created_at.replace(tzinfo=UTC)
            if (now - created).days > 180:
                reasons.append("post is older than 180 days")

        # Self-promotion (not an opportunity)
        promo_signals = find_self_promo_signals(f"{candidate.title} {candidate.body}")
        if promo_signals and intent_result.intent != "launch_opportunity":
            reasons.append(f"self-promotion detected ({promo_signals[0]})")

        if reasons:
            rejection = (
                f"Rejected because: {'; '.join(reasons)}. "
                f"Score breakdown: keyword={keyword_score:.1f}, semantic={semantic_score:.1f}, intent={_INTENT_SCORE_MAP.get(intent_result.intent, 0):.1f}."
            )
            return False, rejection

        return True, None

    @staticmethod
    def _intent_description(intent: str) -> str:
        descriptions = {
            "looking_for_recommendation": "looking for a recommendation",
            "asking_for_help": "asking for help",
            "complaining_about_competitor": "complaining about a competitor",
            "looking_for_alternative": "looking for an alternative",
            "asking_how_to": "asking how to do something",
            "buyer_research": "doing buyer research",
            "comparison": "making a comparison",
            "pain_point_discussion": "discussing a pain point",
            "launch_opportunity": "showcasing a launch",
            "seo_content_gap": "raising an SEO content gap",
            "geo_visibility_gap": "raising a geo visibility gap",
        }
        return descriptions.get(intent, "discussing a related topic")
