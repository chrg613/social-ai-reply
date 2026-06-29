"""Keyword generation from brand and persona context with LLM enhancement."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.product.copilot.llm_client import LLMClient
from app.services.product.relevance import (
    AMBIGUOUS_CONTEXTLESS_TERMS,
    ROLE_TERMS,
    build_domain_context,
    check_domain_vocabulary_match,
    extract_geo_terms,
    extract_structured_phrases,
    keyword_specificity,
    normalize_phrase,
    select_high_signal_keywords,
)

logger = logging.getLogger(__name__)

async def expand_keywords(seed_keywords: list[str]) -> list[dict]:
    """Two-stage LLM keyword expansion.
    Given seed keywords, generates long-tail conversational variations
    labeled with intent (pain, goal, comparison) and confidence.
    """
    if not seed_keywords:
        return []
    
    llm = LLMClient()
    system_prompt = (
        "You are a market research assistant. "
        f"Given these seed keywords: {', '.join(seed_keywords)} "
        "Generate 5 long-tail variations for each seed, and label each with the underlying intent: "
        "- pain (problem) "
        "- goal (desired outcome) "
        "- comparison (looking at alternatives). "
        "Return ONLY a JSON array with fields: seed, keyword, intent, priority_score."
    )
    
    try:
        # Run in executor since llm.call is sync
        import asyncio
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: llm.call(system_prompt, "", temperature=0.7))
        
        if not result or not isinstance(result, list):
            return []
            
        valid_items: list[dict] = []
        for item in result:
            if not isinstance(item, dict):
                continue
            kw = item.get("keyword")
            if not kw or not isinstance(kw, str) or len(kw.strip()) < 3:
                continue
            valid_items.append({
                "keyword": kw.strip(),
                "type": item.get("intent", "goal"),
                "priority_score": int(item.get("priority_score", 50))
            })
        return valid_items
    except Exception:
        logger.exception("expand_keywords failed")
        return [{"keyword": kw, "type": "core", "priority_score": 50} for kw in seed_keywords]


@dataclass
class GeneratedKeyword:
    """A generated keyword with metadata."""

    keyword: str
    rationale: str
    priority_score: int
    category: str = "general_buyer_seller"
    specificity: int = 0


def generate_keywords(
    brand: dict | None,
    personas: list[dict],
    count: int = 55,
) -> list[GeneratedKeyword]:
    """Generate categorized, prioritized keywords from brand and persona context.

    Uses a structured LLM prompt that produces keywords in 4 buckets:
    - pain_point: things people say when frustrated with a problem the brand solves
    - solution_seeking: actively looking for a solution like the brand
    - competitor_alternative: comparing or looking for alternatives
    - general_buyer_seller: broader market queries from the target audience

    Keywords sound like real things humans type on Reddit/Twitter — conversational,
    long-tail phrases, not robotic SEO terms.

    Args:
        brand: Brand profile dict containing brand_name, summary, product_summary,
               target_audience, business_domain, and geography.
        personas: List of persona dicts with name, role, summary, pain_points, etc.
        count: Maximum number of keywords to generate (default 25).

    Returns:
        List of GeneratedKeyword dataclasses, sorted by priority score.
    """
    if not brand:
        return []

    brand_name = brand.get("brand_name", "")
    domain = brand.get("business_domain", "")
    audience = brand.get("target_audience", "")
    summary = brand.get("summary", "")
    product_summary = brand.get("product_summary", "")

    # Try structured LLM keywords first
    llm_results = _llm_keywords_structured(
        brand_name, domain, audience, summary, product_summary, personas, count,
    )

    if llm_results:
        # LLM returned structured data — use it directly
        generated: list[GeneratedKeyword] = []
        seen: set[str] = set()
        for item in llm_results:
            kw = item.get("keyword", "").strip()
            if not kw or len(kw) < 3 or kw.lower() in seen:
                continue
            seen.add(kw.lower())
            generated.append(GeneratedKeyword(
                keyword=kw,
                rationale=item.get("rationale", f"Keyword for {domain or brand_name}."),
                priority_score=max(1, min(int(item.get("priority_score", 50)), 100)),
                category=item.get("category", "general_buyer_seller"),
                specificity=keyword_specificity(kw),
            ))
            if len(generated) >= count:
                break
        if generated:
            return sorted(generated, key=lambda g: g.priority_score, reverse=True)

    # Fallback: heuristic extraction if LLM failed
    logger.warning("Structured LLM keyword generation returned no results; using heuristic fallback")
    heuristic_keywords = _heuristic_keywords(brand, personas, count)
    generated = []
    # Cycle through categories for variety in heuristic results
    category_cycle = ["pain_point", "solution_seeking", "general_buyer_seller", "user_intent", "competitor_alternative"]
    for idx, keyword in enumerate(heuristic_keywords):
        spec = keyword_specificity(keyword)
        score = max(min(95 - idx * 3, 100), 10)
        # Assign category heuristically based on keyword content
        kw_lower = keyword.lower()
        if any(w in kw_lower for w in ("alternative", "vs", "better than", "compare")):
            cat = "competitor_alternative"
        elif any(w in kw_lower for w in ("tired", "frustrated", "problem", "issue", "hate", "annoying", "expensive", "fee")):
            cat = "pain_point"
        elif any(w in kw_lower for w in ("best", "top", "find", "search", "looking for", "app", "tool", "software", "platform")):
            cat = "solution_seeking"
        elif any(w in kw_lower for w in ("need", "want", "help", "how to", "anyone")):
            cat = "user_intent"
        else:
            cat = category_cycle[idx % len(category_cycle)]
        generated.append(GeneratedKeyword(
            keyword=keyword,
            rationale=f"Heuristic keyword for {domain or brand_name}.",
            priority_score=score,
            category=cat,
            specificity=spec,
        ))
        if len(generated) >= count:
            break

    return generated


_VALID_CATEGORIES = {"pain_point", "solution_seeking", "competitor_alternative", "general_buyer_seller", "user_intent"}


def _llm_keywords_structured(
    brand_name: str,
    domain: str,
    audience: str,
    summary: str,
    product_summary: str,
    personas: list[dict],
    count: int,
) -> list[dict]:
    """Use LLM to generate categorized, prioritized keywords with rationale."""
    if not domain and not audience and not summary:
        return []

    # Build persona context
    persona_context = ""
    for p in personas[:3]:
        pain_points = p.get("pain_points", [])
        if isinstance(pain_points, list):
            pain_points = ", ".join(pain_points[:3])
        persona_context += f"  - {p.get('name', 'Unknown')}: {p.get('role', '')} — pain points: {pain_points}\n"

    llm = LLMClient()
    short_count = max(count * 6 // 10, 5)  # ~60% short (2-3 words)
    long_count = count - short_count        # ~40% long (conversational)
    system_prompt = (
        "You are a keyword strategist for social media opportunity discovery on Reddit and Twitter.\n"
        "Generate keywords that REAL HUMANS actually type.\n\n"
        "CRITICAL — KEYWORD LENGTH MIX:\n"
        f"- Generate {short_count} SHORT keywords (2-3 words) — broad terms that match many posts\n"
        f"  (e.g., \"real estate app\", \"property listing\", \"virtual tour\", \"flatmate search\",\n"
        "  \"house hunting\", \"rent apartment\", \"broker commission\", \"home loan\")\n"
        f"- Generate {long_count} LONG keywords (4-8 words) — conversational, high-intent phrases\n"
        "  (e.g., \"tired of blurry property photos\", \"best way to sell property fast\",\n"
        "  \"looking for flatmate in Gurugram\", \"how to inspect house remotely\")\n\n"
        "KEYWORD CATEGORIES — you MUST generate keywords for ALL 5 buckets:\n"
        "1. **pain_point** (~25%) — what people say when frustrated with a problem this product solves\n"
        '   SHORT: "broker issues", "high brokerage"  LONG: "tired of paying broker commission"\n'
        "2. **solution_seeking** (~25%) — actively looking for a tool/service like this\n"
        '   SHORT: "property app", "house finder"  LONG: "best app to find flats in Delhi"\n'
        "3. **competitor_alternative** (~15%) — comparing products or seeking alternatives\n"
        '   SHORT: "magicbricks alternative"  LONG: "magicbricks vs 99acres which is better"\n'
        "4. **general_buyer_seller** (~20%) — broader market queries from the target audience\n"
        '   SHORT: "NRI property", "rental market"  LONG: "NRI buying property in India guide"\n'
        "5. **user_intent** (~15%) — what the product's END USERS would naturally post online\n"
        "   when they have the exact need this product solves.\n"
        '   SHORT: "need flatmate", "room available"  LONG: "looking for flatmate near metro station"\n\n'
        "PRIORITY SCORING:\n"
        "  90-100 = extreme buying intent (ready to purchase/switch)\n"
        "  70-89 = high intent (actively researching solutions)\n"
        "  50-69 = informational intent (exploring the problem space)\n"
        "  30-49 = awareness level (broad topic interest)\n\n"
        "RULES:\n"
        "- Keywords MUST sound like real things typed on Reddit/Twitter — NOT robotic SEO terms\n"
        "- MUST include BOTH short broad keywords AND long conversational queries\n"
        "- Short keywords cast a WIDE NET, long keywords are HIGH PRECISION — you need both\n"
        "- Each rationale must explain WHY this keyword signals an opportunity for the brand\n"
        "- Include competitor names if you can infer them from the domain\n"
        "- If the brand context mentions specific locations, cities, or regions, include\n"
        "  location-qualified keywords naturally (people in those areas search with location terms)\n"
        f"- Generate exactly {count} keywords, spread across all 5 categories\n"
        f"- At least {max(count // 5, 2)} keywords should be user_intent\n"
        f"- At least {max(count // 4, 3)} keywords MUST be pain_point\n"
        f"- At least {max(count // 4, 3)} keywords MUST be solution_seeking\n\n"
        "Return ONLY a JSON array:\n"
        '[{"keyword": "...", "rationale": "...", "priority_score": N, "category": "..."}]'
    )

    context = (
        f"Brand: {brand_name}\n"
        f"Domain: {domain}\n"
        f"Target Audience: {audience}\n"
        f"Summary: {summary}\n"
        f"Product: {product_summary}\n"
    )
    if persona_context:
        context += f"\nTarget Personas:\n{persona_context}"

    try:
        result = llm.call(system_prompt, context, temperature=0.7)
        if not result or not isinstance(result, list):
            return []
        # Validate and normalize each item
        valid_items: list[dict] = []
        for item in result:
            if not isinstance(item, dict):
                continue
            kw = item.get("keyword")
            if not kw or not isinstance(kw, str) or len(kw.strip()) < 3:
                continue
            # Normalize category
            cat = str(item.get("category", "general_buyer_seller")).strip().lower()
            if cat not in _VALID_CATEGORIES:
                cat = "general_buyer_seller"
            item["category"] = cat
            # Clamp priority score
            try:
                item["priority_score"] = max(1, min(int(item.get("priority_score", 50)), 100))
            except (ValueError, TypeError):
                item["priority_score"] = 50
            valid_items.append(item)
        return valid_items
    except Exception:
        logger.exception("Structured LLM keyword generation failed")
    return []


def _heuristic_keywords(brand: dict | None, personas: list[dict], count: int) -> list[str]:
    """Fallback heuristic keyword extraction."""
    if not brand:
        return []

    phrase_map: dict[str, tuple[str, int]] = {}

    def add_candidate(keyword: str, rationale: str, base_score: int) -> None:
        normalized = normalize_phrase(keyword)
        if not normalized:
            return
        specificity = keyword_specificity(normalized)
        # Relaxed filter — only drop very generic single words
        if normalize_phrase(brand.get("brand_name") or "") and specificity < 20:
            return
        score = max(min(base_score + specificity // 5, 100), 1)
        previous = phrase_map.get(normalized)
        if previous and previous[1] >= score:
            return
        phrase_map[normalized] = (rationale, score)

    if brand.get("brand_name"):
        add_candidate(brand.get("brand_name", ""), "Track direct brand mentions and exact product references.", 95)

    biz_domain = brand.get("business_domain", "") or ""
    summary_sources = [brand.get("product_summary") or "", brand.get("summary") or ""]
    for source in summary_sources:
        for phrase in extract_structured_phrases(source, limit=15):
            add_candidate(phrase, f"Specific product or problem phrase from the website copy: {phrase}.", 74)

    for audience in split_csv_terms(brand.get("target_audience")):
        base = 70 if len(audience.split()) > 1 else 58
        if audience in ROLE_TERMS:
            base -= 2
        add_candidate(audience, f"Audience phrase derived from the target audience: {audience}.", base)

    persona_sources: list[str] = []
    for persona in personas[:5]:
        persona_sources.extend([persona.get("name", ""), persona.get("role") or ""])
        if persona.get("source") != "generated":
            persona_sources.extend([
                persona.get("summary", ""),
                " ".join(persona.get("pain_points") or []),
                " ".join(persona.get("goals") or []),
                " ".join(persona.get("triggers") or []),
            ])
    for source in persona_sources:
        for phrase in extract_structured_phrases(source, limit=6):
            add_candidate(phrase, f"Persona-driven phrase linked to a likely pain point or goal: {phrase}.", 68)

    domain_context = build_domain_context(
        brand_name=brand.get("brand_name"),
        summary=brand.get("summary"),
        product_summary=brand.get("product_summary"),
        target_audience=brand.get("target_audience"),
        keywords=list(phrase_map),
        extra_texts=[persona.get("name", "") for persona in personas[:5]],
        business_domain=biz_domain,
    )

    geo_source = " ".join(
        part for part in [
            brand.get("website_url") or "",
            brand.get("summary") or "",
            brand.get("product_summary") or "",
            brand.get("target_audience") or "",
        ] if part
    )
    for geo in extract_geo_terms(geo_source):
        add_candidate(geo, f"Geographic qualifier from the website context: {geo}.", 55)
    for phrase in domain_context.core_phrases[:12]:
        add_candidate(phrase, f"Canonical business-domain phrase distilled from the website context: {phrase}.", 76)
    for anchor in domain_context.anchor_terms[:10]:
        add_candidate(anchor, f"High-signal domain term repeated across the website context: {anchor}.", 58)

    ranked_keywords = select_high_signal_keywords(
        list(phrase_map),
        brand_name=brand.get("brand_name"),
        limit=count * 3,
        domain_context=domain_context,
    )

    # Relaxed domain-vocabulary post-filter
    if biz_domain:
        filtered_keywords: list[str] = []
        brand_norm = normalize_phrase(brand.get("brand_name") or "")
        for kw in ranked_keywords:
            if kw == brand_norm:
                filtered_keywords.append(kw)
                continue
            tokens = kw.split()
            meaningful = [t for t in tokens if t not in AMBIGUOUS_CONTEXTLESS_TERMS]
            if not meaningful:
                continue
            kw_domain_ok, _, _ = check_domain_vocabulary_match(kw, biz_domain)
            kw_has_anchor = bool(set(meaningful) & set(domain_context.anchor_terms))
            # Only drop if it fails ALL checks AND has no meaningful content
            if not kw_domain_ok and not kw_has_anchor and all(
                t in AMBIGUOUS_CONTEXTLESS_TERMS for t in tokens
            ):
                continue
            filtered_keywords.append(kw)
        ranked_keywords = filtered_keywords

    return ranked_keywords


# Need to import this here to avoid circular dependency
from app.services.product.relevance import split_csv_terms  # noqa: E402
