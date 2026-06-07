"""Keyword Expansion Service — generates a universe of brand keywords."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.db.tables.brand_keywords import create_brand_keyword, list_brand_keywords_for_company

logger = logging.getLogger(__name__)

_KEYWORD_TEMPLATES: dict[str, list[str]] = {
    "core": [
        "{product_name}",
        "{category} app",
        "{category} tool",
        "{category} software",
        "{category} platform",
    ],
    "pain_point": [
        "how to solve {pain_point}",
        "tired of {pain_point}",
        "frustrated with {pain_point}",
        "{pain_point} solution",
        "dealing with {pain_point}",
        "how to avoid {pain_point}",
    ],
    "competitor": [
        "alternative to {competitor}",
        "cheaper than {competitor}",
        "{competitor} problem",
        "tired of {competitor}",
        "{competitor} vs {product_name}",
        "{product_name} vs {competitor}",
        "better than {competitor}",
    ],
    "alternative": [
        "best {category} tool",
        "{category} software",
        "top {category} apps",
        "best {category} platform",
        "{category} solution",
    ],
    "audience": [
        "{category} for {audience}",
        "{audience} {category}",
        "{category} app for {audience}",
        "{category} tool for {audience}",
    ],
    "location": [
        "{category} in {location}",
        "{location} {pain_point}",
        "best {category} {location}",
        "{location} {category} app",
        "{category} app {location}",
    ],
    "problem": [
        "how to {problem}",
        "{problem} without {pain_point}",
        "how do I {problem}",
        "best way to {problem}",
    ],
    "feature": [
        "{feature} tool",
        "app with {feature}",
        "{feature} software",
        "{feature} app",
        "{feature} platform",
    ],
    "buying_intent": [
        "looking for {category}",
        "need {category} recommendation",
        "which {category} should I use",
        "best {category} for {audience}",
        "{category} recommendation",
        "recommend a {category}",
    ],
    "question": [
        "how to {action} {category}",
        "what is the best way to {action}",
        "is {product_name} worth it",
        "how does {product_name} work",
        "what is {product_name}",
        "{product_name} review",
    ],
}

_TYPE_WEIGHTS: dict[str, float] = {
    "core": 1.5,
    "pain_point": 1.3,
    "competitor": 1.2,
    "alternative": 1.1,
    "audience": 1.0,
    "location": 0.9,
    "problem": 1.2,
    "feature": 1.1,
    "buying_intent": 1.4,
    "question": 1.0,
}

_SEARCH_QUERY_TEMPLATES: dict[str, list[str]] = {
    "reddit": [
        "site:reddit.com {keyword}",
        "subreddit:{category} {keyword}",
        "reddit {keyword}",
    ],
    "hn": [
        "site:news.ycombinator.com {keyword}",
        "Ask HN {keyword}",
        "Show HN {keyword}",
    ],
    "seo": [
        "{keyword} tools",
        "best {keyword}",
        "{keyword} review",
        "{keyword} alternative",
    ],
    "x": [
        "{keyword} -filter:retweets",
        '"{keyword}"',
    ],
    "linkedin": [
        "{keyword} post",
        "{keyword} insights",
    ],
}


def _normalize_list(value: Any) -> list[str]:
    """Coerce a value into a clean list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _expand_template(template: str, ctx: dict[str, str]) -> str:
    """Replace placeholders in a template using the provided context."""
    result = template
    for key, val in ctx.items():
        result = result.replace("{" + key + "}", val)
    return result


def _deduplicate_keywords(keywords: list[dict]) -> list[dict]:
    """Remove duplicate keyword+type combinations, keeping the first."""
    seen: set[tuple[str, str]] = set()
    result: list[dict] = []
    for kw in keywords:
        key = (kw["keyword"].lower().strip(), kw["type"])
        if key not in seen:
            seen.add(key)
            result.append(kw)
    return result


class KeywordExpansionService:
    """Generates a comprehensive keyword universe for a company profile."""

    def expand(self, company_profile: dict[str, Any]) -> list[dict]:
        """Generate keyword universe from a company profile.

        Args:
            company_profile: Dict with keys: name, description, category,
                target_audience, features, benefits, pain_points,
                competitors, geography.

        Returns:
            List of keyword dicts with keys: keyword, type, weight, source.
        """
        product_name = (company_profile.get("name") or "").strip()
        category = (company_profile.get("category") or "").strip()
        description = (company_profile.get("description") or "").strip()
        target_audience = (company_profile.get("target_audience") or "").strip()
        geography = (company_profile.get("geography") or "").strip()

        features = _normalize_list(company_profile.get("features"))
        benefits = _normalize_list(company_profile.get("benefits"))
        pain_points = _normalize_list(company_profile.get("pain_points"))
        competitors = _normalize_list(company_profile.get("competitors"))

        # Derive actions from description and benefits for question/problem templates
        actions = _derive_actions(description, benefits, features)

        keywords: list[dict] = []

        # 1. Core keywords
        if product_name or category:
            ctx = {
                "product_name": product_name,
                "category": category,
            }
            for tpl in _KEYWORD_TEMPLATES["core"]:
                expanded = _expand_template(tpl, ctx)
                if "{" not in expanded and expanded.strip():
                    keywords.append({
                        "keyword": expanded,
                        "type": "core",
                        "weight": _TYPE_WEIGHTS["core"],
                        "source": "product identity",
                    })

        # 2. Pain point keywords
        for pp in pain_points:
            ctx = {"pain_point": pp}
            for tpl in _KEYWORD_TEMPLATES["pain_point"]:
                expanded = _expand_template(tpl, ctx)
                if "{" not in expanded and expanded.strip():
                    keywords.append({
                        "keyword": expanded,
                        "type": "pain_point",
                        "weight": _TYPE_WEIGHTS["pain_point"],
                        "source": f"pain point: {pp}",
                    })

        # 3. Competitor keywords
        for comp in competitors:
            ctx = {"competitor": comp, "product_name": product_name}
            for tpl in _KEYWORD_TEMPLATES["competitor"]:
                expanded = _expand_template(tpl, ctx)
                if "{" not in expanded and expanded.strip():
                    keywords.append({
                        "keyword": expanded,
                        "type": "competitor",
                        "weight": _TYPE_WEIGHTS["competitor"],
                        "source": f"competitor: {comp}",
                    })

        # 4. Alternative keywords
        if category:
            ctx = {"category": category}
            for tpl in _KEYWORD_TEMPLATES["alternative"]:
                expanded = _expand_template(tpl, ctx)
                if "{" not in expanded and expanded.strip():
                    keywords.append({
                        "keyword": expanded,
                        "type": "alternative",
                        "weight": _TYPE_WEIGHTS["alternative"],
                        "source": "category expansion",
                    })

        # 5. Audience keywords
        for audience in _normalize_list(target_audience):
            if not audience or not category:
                continue
            ctx = {"category": category, "audience": audience}
            for tpl in _KEYWORD_TEMPLATES["audience"]:
                expanded = _expand_template(tpl, ctx)
                if "{" not in expanded and expanded.strip():
                    keywords.append({
                        "keyword": expanded,
                        "type": "audience",
                        "weight": _TYPE_WEIGHTS["audience"],
                        "source": f"audience: {audience}",
                    })

        # 6. Location keywords
        if geography and category:
            for pp in pain_points[:3] if pain_points else [""]:
                ctx = {"category": category, "location": geography, "pain_point": pp}
                for tpl in _KEYWORD_TEMPLATES["location"]:
                    expanded = _expand_template(tpl, ctx)
                    if "{" not in expanded and expanded.strip():
                        keywords.append({
                            "keyword": expanded,
                            "type": "location",
                            "weight": _TYPE_WEIGHTS["location"],
                            "source": f"geo: {geography}",
                        })

        # 7. Problem keywords
        for action in actions:
            for pp in pain_points[:3] if pain_points else [""]:
                ctx = {"problem": action, "pain_point": pp}
                for tpl in _KEYWORD_TEMPLATES["problem"]:
                    expanded = _expand_template(tpl, ctx)
                    if "{" not in expanded and expanded.strip():
                        keywords.append({
                            "keyword": expanded,
                            "type": "problem",
                            "weight": _TYPE_WEIGHTS["problem"],
                            "source": f"action: {action}",
                        })

        # 8. Feature keywords
        for feat in features:
            ctx = {"feature": feat}
            for tpl in _KEYWORD_TEMPLATES["feature"]:
                expanded = _expand_template(tpl, ctx)
                if "{" not in expanded and expanded.strip():
                    keywords.append({
                        "keyword": expanded,
                        "type": "feature",
                        "weight": _TYPE_WEIGHTS["feature"],
                        "source": f"feature: {feat}",
                    })

        # 9. Buying intent keywords
        if category:
            for audience in _normalize_list(target_audience):
                ctx = {"category": category, "audience": audience}
                for tpl in _KEYWORD_TEMPLATES["buying_intent"]:
                    expanded = _expand_template(tpl, ctx)
                    if "{" not in expanded and expanded.strip():
                        keywords.append({
                            "keyword": expanded,
                            "type": "buying_intent",
                            "weight": _TYPE_WEIGHTS["buying_intent"],
                            "source": "buying intent",
                        })

        # 10. Question keywords
        if category:
            for action in actions:
                ctx = {"action": action, "category": category, "product_name": product_name}
                for tpl in _KEYWORD_TEMPLATES["question"]:
                    expanded = _expand_template(tpl, ctx)
                    if "{" not in expanded and expanded.strip():
                        keywords.append({
                            "keyword": expanded,
                            "type": "question",
                            "weight": _TYPE_WEIGHTS["question"],
                            "source": f"question: {action}",
                        })

        return _deduplicate_keywords(keywords)

    def generate_search_queries(self, keywords: list[dict], platform: str | None = None) -> list[str]:
        """Generate platform-specific search queries from keywords.

        Args:
            keywords: List of keyword dicts (from expand()).
            platform: Optional platform name (reddit, hn, seo, x, linkedin).
                If None, returns queries for all platforms.

        Returns:
            List of search query strings.
        """
        queries: list[str] = []
        platforms = [platform] if platform else list(_SEARCH_QUERY_TEMPLATES.keys())

        for kw in keywords:
            keyword_text = kw["keyword"]
            category = kw.get("source", "").replace("category expansion", "").strip()
            if not category:
                # Try to infer category from keyword
                parts = keyword_text.split()
                if len(parts) >= 2:
                    category = parts[-1] if parts[-1] not in {"tool", "app", "software", "platform"} else parts[-2]
                else:
                    category = keyword_text

            ctx = {"keyword": keyword_text, "category": category}
            for plat in platforms:
                for tpl in _SEARCH_QUERY_TEMPLATES.get(plat, []):
                    expanded = _expand_template(tpl, ctx)
                    if "{" not in expanded and expanded.strip():
                        queries.append(expanded)

        # Deduplicate while preserving order
        seen: set[str] = set()
        result: list[str] = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                result.append(q)
        return result

    def store_keywords(self, db: Any, company_id: int, keywords: list[dict]) -> None:
        """Bulk insert keywords into brand_keywords table, skipping duplicates.

        Args:
            db: Supabase client.
            company_id: Company ID to associate keywords with.
            keywords: List of keyword dicts from expand().
        """
        existing = list_brand_keywords_for_company(db, company_id)
        existing_set: set[tuple[str, str]] = {
            (row["keyword"].lower().strip(), row["type"])
            for row in existing
        }

        inserted = 0
        for kw in keywords:
            key = (kw["keyword"].lower().strip(), kw["type"])
            if key in existing_set:
                continue
            weight = int(kw.get("weight", 1))
            data = {
                "company_id": company_id,
                "keyword": kw["keyword"],
                "type": kw["type"],
                "weight": max(1, min(weight, 10)),
                "source": kw.get("source", ""),
                "is_enabled": True,
            }
            try:
                create_brand_keyword(db, data)
                existing_set.add(key)
                inserted += 1
            except Exception:
                logger.exception("Failed to insert keyword %s", kw["keyword"])

        logger.info("Inserted %s new keywords for company %s", inserted, company_id)


def _derive_actions(description: str, benefits: list[str], features: list[str]) -> list[str]:
    """Derive action phrases from description, benefits, and features."""
    actions: list[str] = []
    # From description: look for verb-noun patterns
    text = f"{description} {' '.join(benefits)} {' '.join(features)}"
    # Simple extraction of gerunds and verb phrases
    words = text.lower().split()
    action_starters = {
        "find", "search", "manage", "track", "automate", "build", "create", "solve",
        "reduce", "eliminate", "avoid", "prevent", "save", "improve", "increase",
        "discover", "organize", "schedule", "plan", "compare", "review", "choose",
        "select", "buy", "rent", "lease", "sell", "list", "filter", "sort",
        "integrate", "sync", "connect", "share", "collaborate", "communicate",
    }
    for i, word in enumerate(words):
        cleaned = re.sub(r"[^a-z]", "", word)
        if cleaned in action_starters and i + 1 < len(words):
            next_word = re.sub(r"[^a-z]", "", words[i + 1])
            if next_word and len(next_word) > 2 and next_word not in {"the", "a", "an", "and", "or"}:
                actions.append(f"{cleaned} {next_word}")
    # Also add generic actions from benefits
    for benefit in benefits:
        benefit_lower = benefit.lower()
        if any(benefit_lower.startswith(a) for a in action_starters):
            actions.append(benefit_lower.split(".")[0].strip()[:40])
    # Deduplicate and limit
    seen: set[str] = set()
    result: list[str] = []
    for a in actions:
        if a not in seen and len(a) > 3:
            seen.add(a)
            result.append(a)
        if len(result) >= 8:
            break
    # Fallbacks
    if not result:
        result = ["find", "manage", "solve", "improve"]
    return result
