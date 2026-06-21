"""Discovery service for keywords and subreddits.

This module handles subreddit discovery and analysis using the Supabase client.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supabase import Client

from app.db.tables.discovery import (
    create_monitored_subreddit,
    list_keywords_for_project,
)
from app.services.product.reddit import RedditClient, RedditPost, RedditSubredditMatch
from app.services.product.relevance import (
    OFFTOPIC_COMMUNITY_NAMES,
    assess_domain_match,
    build_domain_context,
    canonicalize_keyword_phrase,
    check_domain_vocabulary_match,
    extract_geo_terms,
    find_intent_hits,
    find_offtopic_signals,
    has_meaningful_phrase_overlap,
    is_low_signal_keyword,
    keyword_matches_domain_context,
    keyword_specificity,
    normalize_phrase,
    select_high_signal_keywords,
    split_csv_terms,
    tokenize,
)

log = logging.getLogger("signalflow.discovery")

DEFAULT_MIN_SUBREDDIT_FIT = 30
MAX_DISCOVERY_KEYWORDS = 5
SUBREDDIT_TRAILING_GENERIC_TOKENS = {
    "app",
    "apps",
    "business",
    "businesses",
    "community",
    "communities",
    "company",
    "companies",
    "dashboard",
    "discovery",
    "marketplace",
    "platform",
    "platforms",
    "search",
    "service",
    "services",
    "software",
    "solution",
    "solutions",
    "system",
    "systems",
    "tool",
    "tools",
}


@dataclass
class SubredditAssessment:
    eligible: bool
    fit_score: int
    activity_score: int
    top_post_types: list[str]
    audience_signals: list[str]
    posting_risk: list[str]
    recommendation: str
    matched_keywords: list[str]
    reasons: list[str]


def get_project_search_keywords(supabase: Client, project: dict, limit: int = 15, *, include_brand: bool = True) -> list[str]:
    """Get high-signal search keywords for a project.

    High-priority keywords (priority_score >= 70) are included first in their
    DB-stored priority order. Remaining slots are filled via the domain-signal
    ranker to catch useful heuristic keywords that didn't come from the LLM.
    """

    rows = list_keywords_for_project(supabase, project["id"])
    active_rows = [r for r in rows if r.get("is_active", True)]
    active_rows.sort(key=lambda x: x.get("priority_score", 50), reverse=True)

    brand = project.get("brand_profile")
    brand_name = brand.get("brand_name") if brand else None
    biz_domain = brand.get("business_domain", "") if brand else ""

    # Split keywords: high-priority (LLM-scored >= 70) vs. the rest
    high_priority = [row["keyword"] for row in active_rows if row.get("priority_score", 50) >= 70]
    remaining = [row["keyword"] for row in active_rows if row.get("priority_score", 50) < 70]

    # Start with brand name if requested
    selected: list[str] = []
    seen: set[str] = set()
    if include_brand and brand_name:
        normalized_brand = brand_name.strip().lower()
        if normalized_brand and len(normalized_brand) >= 4:
            selected.append(brand_name.strip())
            seen.add(normalized_brand)

    # Add high-priority keywords first (already in priority_score DESC order)
    for kw in high_priority:
        if len(selected) >= limit:
            break
        kw_lower = kw.strip().lower()
        if kw_lower not in seen and len(kw_lower) >= 3:
            selected.append(kw.strip())
            seen.add(kw_lower)

    # Fill remaining slots with domain-signal-ranked keywords
    if len(selected) < limit and remaining:
        domain_context = build_domain_context(
            brand_name=brand_name,
            summary=brand.get("summary") if brand else None,
            product_summary=brand.get("product_summary") if brand else None,
            target_audience=brand.get("target_audience") if brand else None,
            keywords=remaining,
            business_domain=biz_domain,
        )
        ranked_remaining = select_high_signal_keywords(
            remaining,
            brand_name=None,  # Already added above
            limit=limit - len(selected),
            domain_context=domain_context,
        )
        for kw in ranked_remaining:
            if len(selected) >= limit:
                break
            kw_lower = kw.strip().lower()
            if kw_lower not in seen:
                selected.append(kw)
                seen.add(kw_lower)

    return selected


def discover_and_store_subreddits(
    supabase: Client,
    project: dict,
    *,
    max_subreddits: int,
    reddit: RedditClient | None = None,
) -> list[dict]:
    """Discover and store subreddits for a project."""
    reddit = reddit or RedditClient()
    base_keywords = get_project_search_keywords(supabase, project, limit=max(MAX_DISCOVERY_KEYWORDS * 2, 8), include_brand=False)

    brand = project.get("brand_profile")
    biz_domain = brand.get("business_domain", "") if brand else ""

    domain_context = build_domain_context(
        brand_name=brand.get("brand_name") if brand else None,
        summary=brand.get("summary") if brand else None,
        product_summary=brand.get("product_summary") if brand else None,
        target_audience=brand.get("target_audience") if brand else None,
        keywords=base_keywords,
        business_domain=biz_domain,
    )
    search_queries = _build_subreddit_search_queries(base_keywords, domain_context=domain_context, limit=MAX_DISCOVERY_KEYWORDS)

    # Fallback: use raw keywords directly if query builder filters all
    if not search_queries:
        log.warning("No subreddit search queries after filtering — falling back to raw keywords")
        search_queries = [kw for kw in base_keywords if len(kw.split()) >= 2][:MAX_DISCOVERY_KEYWORDS]
    if not search_queries and base_keywords:
        search_queries = base_keywords[:MAX_DISCOVERY_KEYWORDS]
    if not search_queries:
        return []

    log.info("Subreddit search queries (%d): %s", len(search_queries), search_queries)

    assessment_keywords = base_keywords

    # Get existing subreddits
    from app.db.tables.discovery import list_subreddits_for_project
    existing_rows = list_subreddits_for_project(supabase, project["id"])
    existing_names = {row["name"].lower() for row in existing_rows}
    seen_names = set(existing_names)
    created: list[dict] = []
    candidates: dict[str, tuple[RedditSubredditMatch, SubredditAssessment, list[str]]] = {}

    from app.services.product.reddit_discovery import _HTTP_BUDGET, _REDDIT_HOSTS

    reddit_blocked = any(_HTTP_BUDGET.is_open(h) for h in _REDDIT_HOSTS)
    if reddit_blocked:
        log.info("Reddit circuit is open — will skip enrichment calls")

    candidate_budget = max(max_subreddits * 6, max_subreddits + 20)
    candidates_reviewed = 0
    enrichment_failed = False  # Set True after first enrichment failure to skip retries

    # Build a simple keyword/brand token set for lightweight matching.
    # Used when enrichment data (sample posts, rules) is unavailable.
    _kw_tokens = set()
    for kw in assessment_keywords:
        for tok in kw.lower().split():
            if len(tok) > 2:
                _kw_tokens.add(tok)
    brand = project.get("brand_profile") or {}
    for field_name in ("brand_name", "business_domain"):
        val = brand.get(field_name, "")
        if val:
            for tok in val.lower().split():
                if len(tok) > 2:
                    _kw_tokens.add(tok)

    for keyword in search_queries:
        try:
            matches = reddit.search_subreddits(keyword, limit=min(max_subreddits * 3, 15))
        except Exception as exc:
            log.warning("Subreddit search failed for %r: %s", keyword, exc)
            continue
        log.info("Query %r returned %d subreddit matches", keyword, len(matches))
        for match in matches:
            if len(created) >= max_subreddits:
                break
            if candidates_reviewed >= candidate_budget:
                break
            normalized_name = match.name.lower()
            if normalized_name in seen_names:
                continue
            seen_names.add(normalized_name)
            candidates_reviewed += 1

            # Try enrichment (sample posts + rules) unless Reddit is known-blocked
            # or a previous enrichment already failed (no point retrying).
            skip_enrichment = reddit_blocked or enrichment_failed or any(_HTTP_BUDGET.is_open(h) for h in _REDDIT_HOSTS)
            if skip_enrichment:
                sample_posts: list[RedditPost] = []
                rules: list[str] = []
            else:
                sample_posts = _safe_subreddit_posts(reddit, match.name)
                if not sample_posts:
                    # First enrichment failure — skip for all remaining candidates.
                    enrichment_failed = True
                    log.info("Enrichment failed for r/%s — skipping enrichment for remaining candidates", match.name)
                rules = _safe_subreddit_rules(reddit, match.name) if sample_posts else []

            if sample_posts:
                # ── ENRICHED MODE: full scoring with real data ────────────
                assessment = assess_subreddit_candidate(
                    match=match,
                    about={},
                    rules=rules,
                    sample_posts=sample_posts,
                    project=project,
                    keywords=assessment_keywords,
                )
                if not assessment.eligible:
                    log.debug(
                        "r/%s not eligible (enriched): fit=%d keywords=%s",
                        match.name, assessment.fit_score,
                        bool(assessment.matched_keywords),
                    )
                    continue
            else:
                # ── LIGHTWEIGHT MODE: keyword match in name/description ───
                # When we have NO sample posts (Reddit blocked, timeout, or
                # empty subreddit), the full scoring pipeline can't work.
                # Accept subreddits that have keyword overlap instead.
                text = f"{match.name} {match.title} {match.description}".lower()
                hit_count = sum(1 for tok in _kw_tokens if tok in text)
                if hit_count == 0:
                    log.debug("r/%s rejected (lightweight): no keyword tokens in name/desc", match.name)
                    continue
                assessment = SubredditAssessment(
                    eligible=True,
                    fit_score=min(30 + hit_count * 10, 80),
                    matched_keywords=[tok for tok in _kw_tokens if tok in text][:5],
                    activity_score=50,
                    top_post_types=[],
                    audience_signals=[],
                    posting_risk=[],
                    recommendation="Accepted via lightweight keyword matching (no enrichment data).",
                    reasons=[f"Keyword match ({hit_count} token(s)) in subreddit metadata."],
                )

            previous = candidates.get(normalized_name)
            if previous and _candidate_selection_score(previous[0], previous[1]) >= _candidate_selection_score(match, assessment):
                continue
            candidates[normalized_name] = (match, assessment, rules)

        if candidates_reviewed >= candidate_budget:
            break
        if len(candidates) >= max_subreddits:
            log.info("Already have %d candidates — stopping keyword search", len(candidates))
            break

    log.info(
        "Subreddit discovery: reviewed %d candidates, %d eligible, selecting up to %d",
        candidates_reviewed, len(candidates), max_subreddits,
    )

    selected_candidates = sorted(
        candidates.values(),
        key=lambda item: (
            _candidate_selection_score(item[0], item[1]),
            item[1].fit_score,
            int(item[0].subscribers or 0),
        ),
        reverse=True,
    )[:max_subreddits]

    for match, assessment, rules in selected_candidates:
        row = create_monitored_subreddit(
            supabase,
            {
                "project_id": project["id"],
                "name": match.name,
                "title": match.title,
                "description": match.description,
                "subscribers": int(match.subscribers or 0),
                "activity_score": assessment.activity_score,
                "fit_score": assessment.fit_score,
                "rules_summary": "\n".join(rules[:5]) if rules else None,
                "is_active": True,
            },
        )

        # Create analysis record. Note: the DB column is subreddit_id (FK
        # to monitored_subreddits.id), not monitored_subreddit_id. The
        # subreddits_analyses table only has: id, subreddit_id,
        # recommendation, audience_signals, top_post_types, posting_risk,
        # created_at — keep this insert payload aligned with that shape.
        from app.db.tables.discovery import create_subreddit_analysis
        create_subreddit_analysis(
            supabase,
            {
                "subreddit_id": row["id"],
                "top_post_types": assessment.top_post_types,
                "audience_signals": assessment.audience_signals,
                "posting_risk": assessment.posting_risk,
                "recommendation": assessment.recommendation,
            },
        )
        created.append(row)

    return created


def refresh_subreddit_analysis(
    supabase: Client,
    project: dict,
    subreddit: dict,
    *,
    reddit: RedditClient | None = None,
) -> SubredditAssessment:
    """Refresh analysis for a monitored subreddit."""
    reddit = reddit or RedditClient()
    keywords = get_project_search_keywords(supabase, project)
    about = _safe_subreddit_about(reddit, subreddit["name"])
    rules = _safe_subreddit_rules(reddit, subreddit["name"])
    sample_posts = _safe_subreddit_posts(reddit, subreddit["name"])

    assessment = assess_subreddit_candidate(
        match=RedditSubredditMatch(
            name=subreddit["name"],
            title=about.get("title") or subreddit.get("title") or "",
            description=about.get("public_description", "") or subreddit.get("description") or "",
            subscribers=int(about.get("subscribers") or subreddit.get("subscribers") or 0),
        ),
        about=about,
        rules=rules,
        sample_posts=sample_posts,
        project=project,
        keywords=keywords,
    )

    # Update subreddit record
    from app.db.tables.discovery import update_monitored_subreddit
    update_monitored_subreddit(
        supabase,
        subreddit["id"],
        {
            "title": about.get("title") or subreddit.get("title"),
            "description": about.get("public_description", "") or subreddit.get("description"),
            "subscribers": int(about.get("subscribers") or subreddit.get("subscribers") or 0),
            "activity_score": assessment.activity_score,
            "fit_score": assessment.fit_score,
            "rules_summary": "\n".join(rules[:5]) if rules else None,
        },
    )

    # Create new analysis record — DB column is subreddit_id (not
    # monitored_subreddit_id); keep shape consistent with the other call
    # site above and with the actual subreddits_analyses schema.
    from app.db.tables.discovery import create_subreddit_analysis
    create_subreddit_analysis(
        supabase,
        {
            "subreddit_id": subreddit["id"],
            "top_post_types": assessment.top_post_types,
            "audience_signals": assessment.audience_signals,
            "posting_risk": assessment.posting_risk,
            "recommendation": assessment.recommendation,
        },
    )

    return assessment


def assess_subreddit_candidate(
    *,
    match: RedditSubredditMatch,
    about: dict,
    rules: list[str],
    sample_posts: list[RedditPost],
    project: dict,
    keywords: list[str],
) -> SubredditAssessment:
    """Assess a subreddit candidate for fit."""
    brand = project.get("brand_profile")
    biz_domain = brand.get("business_domain", "") if brand else ""

    domain_context = build_domain_context(
        brand_name=brand.get("brand_name") if brand else None,
        summary=brand.get("summary") if brand else None,
        product_summary=brand.get("product_summary") if brand else None,
        target_audience=brand.get("target_audience") if brand else None,
        keywords=keywords,
        business_domain=biz_domain,
    )

    title = about.get("title") or match.title
    description = about.get("public_description", "") or match.description
    sample_titles = " ".join(post.title for post in sample_posts[:8])
    sample_bodies = " ".join(post.body[:180] for post in sample_posts[:4] if post.body)
    metadata_text = " ".join(part for part in [match.name, title, description, sample_titles, sample_bodies] if part)
    normalized_text = normalize_phrase(metadata_text)
    token_set = set(tokenize(normalized_text))
    domain_match = assess_domain_match(metadata_text, domain_context)

    matched_keywords: list[str] = []
    topic_score = 0
    for keyword in keywords:
        specificity = keyword_specificity(keyword)
        if keyword in normalized_text:
            matched_keywords.append(keyword)
            topic_score += max(12, specificity // 3)
            continue
        if len(keyword.split()) > 1 and has_meaningful_phrase_overlap(keyword, token_set):
            matched_keywords.append(keyword)
            topic_score += max(8, specificity // 5)
    topic_score = min(topic_score, 60)

    audience_terms = split_csv_terms(brand.get("target_audience") if brand else None)
    matched_audience = [term for term in audience_terms if term in normalized_text]
    if not matched_audience:
        inferred_audience = []
        for term in ["founders", "marketers", "developers", "buyers", "operators"]:
            if term.rstrip("s") in token_set or term in token_set:
                inferred_audience.append(term)
        matched_audience = inferred_audience
    audience_score = min(len(matched_audience) * 4, 12)

    question_threads = sum(bool(find_intent_hits(post.title) or "?" in post.title) for post in sample_posts)
    intent_orientation = min(question_threads * 4, 12)

    subscribers = int(about.get("subscribers") or match.subscribers or 0)
    activity_score = min(
        100,
        18
        + int(subscribers > 5_000) * 14
        + int(subscribers > 25_000) * 16
        + int(subscribers > 100_000) * 16
        + min(len(sample_posts) * 6, 24),
    )

    posting_risk = [rule for rule in rules[:5]]
    risk_penalty = 0
    lowered_rules = " ".join(rule.lower() for rule in rules)
    if any(term in lowered_rules for term in [
        "self-promo", "promotion", "no solicitation", "no advertising",
        "no commercial", "no business", "no marketing",
    ]):
        risk_penalty += 8
    if any(term in lowered_rules for term in [
        "no external link", "no link", "no url",
    ]):
        risk_penalty += 4
    elif "link" in lowered_rules:
        risk_penalty += 2

    offtopic_hits = find_offtopic_signals(metadata_text)
    if match.name.lower() in OFFTOPIC_COMMUNITY_NAMES:
        offtopic_hits.append(match.name.lower())
    unique_offtopic_hits = sorted(set(offtopic_hits))
    offtopic_penalty = min(len(unique_offtopic_hits) * 12, 36)

    # Domain-vocabulary alignment
    domain_vocab_ok, domain_vocab_count, _ = check_domain_vocabulary_match(
        metadata_text, domain_context.business_domain,
    )
    domain_vocab_bonus = 0
    if domain_context.business_domain:
        if domain_vocab_count >= 3:
            domain_vocab_bonus = min(domain_vocab_count * 3, 14)
        elif domain_vocab_count == 0 and domain_match.aligned:
            domain_vocab_bonus = -8

    fit_score = max(
        0,
        min(
            topic_score
            + min(domain_match.score, 22)
            + audience_score
            + intent_orientation
            + activity_score // 5
            + domain_vocab_bonus
            - risk_penalty
            - offtopic_penalty,
            100,
        ),
    )

    topic_ok = topic_score >= 12
    if domain_vocab_count >= 2 and topic_score >= 8:
        topic_ok = True
    eligible = (
        topic_ok
        and (domain_match.aligned or domain_vocab_count >= 1)
        and fit_score >= DEFAULT_MIN_SUBREDDIT_FIT
        and offtopic_penalty < 24
    )

    reasons: list[str] = []
    if matched_keywords:
        reasons.append(f"Matched subreddit context against {len(matched_keywords)} high-signal keyword(s).")
    if domain_match.aligned:
        reasons.append("Subreddit context matches the project's business domain.")
    if matched_audience:
        reasons.append("Audience overlap was detected in the subreddit description or sampled posts.")
    if question_threads:
        reasons.append("Recent subreddit posts show question or recommendation intent.")
    if unique_offtopic_hits:
        reasons.append(f"Off-topic community signals reduced fit: {', '.join(unique_offtopic_hits[:3])}.")
    if not domain_match.aligned:
        reasons.append("Subreddit context does not show clear business-domain overlap.")
    if not reasons:
        reasons.append("Weak topical overlap with the project context.")

    recommendation = (
        f"Good fit for high-intent discovery. Prioritize threads tied to {', '.join(matched_keywords[:2])}."
        if eligible
        else f"Skip for automated discovery. {reasons[-1]}"
    )

    return SubredditAssessment(
        eligible=eligible,
        fit_score=fit_score,
        activity_score=activity_score,
        top_post_types=_classify_post_types(sample_posts),
        audience_signals=matched_audience or ["broad interest audience"],
        posting_risk=posting_risk,
        recommendation=recommendation,
        matched_keywords=matched_keywords,
        reasons=reasons,
    )


def _classify_post_types(sample_posts: list[RedditPost]) -> list[str]:
    """Classify post types from sample posts."""
    top_post_types: list[str] = []
    if any("?" in post.title or find_intent_hits(post.title) for post in sample_posts):
        top_post_types.append("questions")
    if any(
        phrase in post.title.lower()
        for post in sample_posts
        for phrase in ["case study", "what we learned", "launched", "launching", "showcase", "demo"]
    ):
        top_post_types.append("case studies")
    if not top_post_types:
        top_post_types = ["discussion", "advice"]
    return top_post_types


def _safe_subreddit_about(reddit: RedditClient, name: str) -> dict:
    """Safely get subreddit about info."""
    try:
        return reddit.subreddit_about(name)
    except Exception:
        return {}


def _safe_subreddit_rules(reddit: RedditClient, name: str) -> list[str]:
    """Safely get subreddit rules."""
    try:
        return reddit.subreddit_rules(name)
    except Exception:
        return []


def _safe_subreddit_posts(reddit: RedditClient, name: str) -> list[RedditPost]:
    """Safely get subreddit posts."""
    try:
        return reddit.list_subreddit_posts(name, sort="hot", limit=6)
    except Exception:
        return []


def _is_promising_subreddit_match(
    match: RedditSubredditMatch,
    project: dict,
    keywords: list[str],
    *,
    sample_posts: list[RedditPost] | None = None,
) -> bool:
    """Check if a subreddit match is promising."""
    assessment = assess_subreddit_candidate(
        match=match,
        about={},
        rules=[],
        sample_posts=sample_posts or [],
        project=project,
        keywords=keywords,
    )
    if assessment.eligible:
        return True
    if not sample_posts:
        return bool(assessment.matched_keywords) and assessment.fit_score >= (DEFAULT_MIN_SUBREDDIT_FIT - 22)
    return bool(assessment.matched_keywords) and assessment.fit_score >= (DEFAULT_MIN_SUBREDDIT_FIT - 14)


def _candidate_selection_score(match: RedditSubredditMatch, assessment: SubredditAssessment) -> int:
    """Calculate candidate selection score."""
    subscribers = int(match.subscribers or 0)
    subscriber_bonus = 0
    if subscribers >= 500_000:
        subscriber_bonus = 18
    elif subscribers >= 100_000:
        subscriber_bonus = 14
    elif subscribers >= 25_000:
        subscriber_bonus = 10
    elif subscribers >= 5_000:
        subscriber_bonus = 6

    small_niche_penalty = 0
    if subscribers < 100:
        small_niche_penalty = 28
    elif subscribers < 1_000:
        small_niche_penalty = 18
    elif subscribers < 5_000:
        small_niche_penalty = 8
    if subscribers < 1_000 and assessment.activity_score < 55:
        small_niche_penalty += 8

    return assessment.fit_score + assessment.activity_score // 2 + subscriber_bonus - small_niche_penalty


def _build_subreddit_search_queries(
    keywords: list[str],
    *,
    domain_context,
    limit: int,
) -> list[str]:
    """Build search queries for subreddit discovery."""
    queries: list[str] = []
    seen: set[str] = set()
    keyword_set = set(keywords)
    seed_phrases = keywords + list(domain_context.core_phrases) + list(domain_context.audience_phrases)

    for phrase in seed_phrases:
        for candidate in _subreddit_query_variants(phrase, domain_context=domain_context):
            if candidate in seen:
                continue
            queries.append(candidate)
            seen.add(candidate)

    for kw in keywords:
        normalized = normalize_phrase(kw)
        if normalized and normalized not in seen and len(normalized.split()) >= 2:
            queries.append(normalized)
            seen.add(normalized)

    if domain_context.business_domain:
        biz = normalize_phrase(domain_context.business_domain)
        if biz and biz not in seen:
            queries.append(biz)
            seen.add(biz)

    ranked_queries = sorted(
        queries,
        key=lambda query: _subreddit_query_score(query, domain_context=domain_context, keyword_set=keyword_set),
        reverse=True,
    )
    return ranked_queries[:limit]


def _subreddit_query_variants(phrase: str, *, domain_context) -> list[str]:
    """Generate query variants from a phrase."""
    canonical = canonicalize_keyword_phrase(phrase, domain_context=domain_context, max_words=3)
    if not canonical:
        return []

    candidates = [canonical]
    tokens = canonical.split()
    if len(tokens) >= 3:
        if tokens[-1] in SUBREDDIT_TRAILING_GENERIC_TOKENS:
            candidates.append(" ".join(tokens[:-1]))
        candidates.append(" ".join(tokens[:2]))
        candidates.append(" ".join(tokens[-2:]))

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = canonicalize_keyword_phrase(candidate, domain_context=domain_context, max_words=3)
        if (
            not normalized
            or normalized in seen
            or is_low_signal_keyword(normalized)
            or not keyword_matches_domain_context(normalized, domain_context)
        ):
            continue
        deduped.append(normalized)
        seen.add(normalized)
    return deduped


def _subreddit_query_score(query: str, *, domain_context, keyword_set: set[str]) -> int:
    """Score a query for ranking."""
    score = keyword_specificity(query)
    if query in keyword_set:
        score += 24
    words = len(query.split())
    if words == 2:
        score += 12
    elif words == 3:
        score += 8
    elif words == 1:
        score -= 6
    if extract_geo_terms(query):
        score -= 10
    if query in domain_context.core_phrases:
        score += 6
    if query in domain_context.audience_phrases:
        score += 4
    return score
