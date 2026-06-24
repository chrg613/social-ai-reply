"""Persona generation from brand context using LLM."""

from __future__ import annotations

import logging

from app.services.product.copilot.llm_client import LLMClient
from app.services.product.relevance import canonicalize_keyword_phrase, normalize_phrase

logger = logging.getLogger(__name__)


def suggest_personas(brand: dict | None, count: int = 4) -> list[dict]:
    """Generate persona suggestions from brand target audience using LLM.

    Uses the brand's business domain, target audience, and product summary
    to generate realistic, domain-aware personas with specific pain points,
    goals, and triggers relevant to the business.
    """
    if not brand:
        return _fallback_personas(count)

    llm = LLMClient()
    brand_name = brand.get("brand_name", "")
    domain = brand.get("business_domain", "")
    audience = brand.get("target_audience", "")
    summary = brand.get("summary", "")
    product_summary = brand.get("product_summary", "")

    system_prompt = (
        "You generate realistic buyer/customer personas for social media opportunity discovery. "
        "Return a JSON array of persona objects. Each persona must have: "
        "name (short role label like 'First-Time Home Buyer'), "
        "role (full description like 'First-time home buyer looking for affordable apartments'), "
        "summary (1-2 sentence description of what they need), "
        "pain_points (array of 3-5 specific problems they face), "
        "goals (array of 2-4 things they want to achieve), "
        "triggers (array of 2-4 events that make them seek solutions), "
        "preferred_subreddits (array of Reddit subreddit names they would likely visit).\n\n"
        "Make each persona SPECIFIC to the business domain and realistic for Reddit users. "
        "Use real subreddit names that exist (like r/RealEstate, r/firsttimehomebuyer, etc.). "
        "Pain points should be concrete problems, not generic statements."
    )

    context = (
        f"Business: {brand_name}\n"
        f"Domain: {domain}\n"
        f"Target Audience: {audience}\n"
        f"Summary: {summary}\n"
        f"Product Summary: {product_summary}\n\n"
        f"Generate {count} distinct, realistic personas for this business."
    )

    try:
        result = llm.call(system_prompt, context, temperature=0.7)
        if result and isinstance(result, list) and len(result) > 0:
            personas = []
            seen_labels: set[str] = set()
            for item in result:
                if not isinstance(item, dict):
                    continue
                label = (item.get("name") or "").strip()
                if not label or label.lower() in seen_labels:
                    continue
                seen_labels.add(label.lower())
                pain_points = item.get("pain_points") or []
                goals = item.get("goals") or []
                triggers = item.get("triggers") or []
                preferred_subreddits = item.get("preferred_subreddits") or []

                personas.append({
                    "name": label,
                    "role": (item.get("role") or label),
                    "summary": item.get("summary") or f"{label} needs solutions in the {domain or brand_name} space.",
                    "pain_points": pain_points if isinstance(pain_points, list) else [],
                    "goals": goals if isinstance(goals, list) else [],
                    "triggers": triggers if isinstance(triggers, list) else [],
                    "preferred_subreddits": preferred_subreddits if isinstance(preferred_subreddits, list) else [],
                    "source": "generated",
                })
                if len(personas) >= count:
                    break
            if personas:
                return personas
    except Exception:
        logger.exception("LLM persona generation failed; using fallback")

    return _fallback_personas(count)


def _fallback_personas(count: int = 4) -> list[dict]:
    """Fallback personas when LLM is unavailable."""
    seed = ["buyers", "researchers", "comparison shoppers", "problem solvers"]
    personas = []
    seen_labels: set[str] = set()
    for idx, base in enumerate(seed[:count], start=1):
        canonical = canonicalize_keyword_phrase(base, max_words=4) or normalize_phrase(base)
        label = canonical.strip().title() or f"Persona {idx}"
        if not label or label.lower() in seen_labels:
            continue
        seen_labels.add(label.lower())
        personas.append({
            "name": label,
            "role": label,
            "summary": f"{label} wants trustworthy information and relevant options before making a decision.",
            "pain_points": ["Too much noise", "Hard to verify quality", "Needs trusted guidance"],
            "goals": ["Find relevant options", "Reduce decision risk"],
            "triggers": ["A new need appears", "Current options feel unreliable"],
            "preferred_subreddits": [],
            "source": "generated",
        })
        if len(personas) >= count:
            break
    return personas
