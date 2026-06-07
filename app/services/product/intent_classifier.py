"""Heuristic-based intent classifier for social-media posts.

No LLM calls — fast keyword-pattern matching with confidence scoring.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.product.relevance import normalize_phrase


@dataclass
class IntentResult:
    intent: str
    confidence: float
    reason: str


# ── Keyword pattern banks ──────────────────────────────────────────────

_LOOKING_FOR_RECOMMENDATION = {
    "recommend", "recommendation", "suggest", "suggestion",
    "best", "what should i use", "anyone tried", "which one",
    "looking for", "need recommendations", "recommend a",
    "recommend any", "recommendations for", "what tool",
    "which tool", "can anyone recommend",
}

_ASKING_FOR_HELP = {
    "help", "how do i", "stuck with", "need advice",
    "struggling with", "can't figure out", "need help",
    "how can", "how should", "any advice",
}

_ASKING_HOW_TO = {
    "how to", "tutorial", "guide", "steps to",
    "learn to", "how do you", "how does one",
}

_BUYER_RESEARCH = {
    "review", "compare", "vs", "versus",
    "pros and cons", "worth it", "pricing", "cost",
    "worth buying", "should i buy", "experience with",
}

_COMPARISON = {
    "vs ", "versus", "compare", "comparison",
    "difference between", "better than", " or ",
    "alternatives to", "alternative to",
}

_PAIN_POINT_DISCUSSION = {
    "frustrated", "annoying", "waste of time",
    "inefficient", "slow", "broken", "doesn't work",
    "missing feature", "hate", "tired of",
    "not working", "problem", "issue", "bug",
}

_LAUNCH_OPPORTUNITY = {
    "show hn", "launched", "announce", "new tool",
    "just built", "beta", "feedback on my",
    "just launched", "just shipped", "i built",
    "i created", "i made", "we built", "we launched",
}

_SPAM = {
    "click here", "buy now", "limited time",
    "free money", "earn $", "crypto investment",
    "100x", "make money fast", "get rich",
    "act now", "exclusive deal", "double your",
    "guaranteed profit", "no risk", "click below",
}

_UNSAFE = {
    "hack", "crack", "illegal", "stolen",
    "pirated", "fake id", "carding", "exploit",
    "dox", "swat", "ransomware", "phishing kit",
    "credential stuffing", " credential "
}

# Security-context words that make "hack" or "crack" legitimate
_SECURITY_CONTEXT = {
    "security", "pentest", "penetration test", "ethical",
    "researcher", "vulnerability", "cve", "disclosure",
    "bug bounty", "responsible disclosure", "defensive",
    "blue team", "red team", "cybersecurity", "infosec",
}

_INTENT_ORDER = [
    ("looking_for_recommendation", _LOOKING_FOR_RECOMMENDATION, "user is actively seeking recommendations"),
    ("asking_for_help", _ASKING_FOR_HELP, "user is asking for help or advice"),
    ("asking_how_to", _ASKING_HOW_TO, "user wants a tutorial or guide"),
    ("buyer_research", _BUYER_RESEARCH, "user is researching a purchase"),
    ("comparison", _COMPARISON, "user is comparing options"),
    ("pain_point_discussion", _PAIN_POINT_DISCUSSION, "user is venting about a pain point"),
    ("launch_opportunity", _LAUNCH_OPPORTUNITY, "user is showcasing a launch"),
]

_ALL_INTENTS = [
    "looking_for_recommendation",
    "asking_for_help",
    "complaining_about_competitor",
    "looking_for_alternative",
    "asking_how_to",
    "buyer_research",
    "comparison",
    "pain_point_discussion",
    "launch_opportunity",
    "seo_content_gap",
    "geo_visibility_gap",
    "irrelevant",
    "spam",
    "unsafe",
]


# ── Classification helpers ─────────────────────────────────────────────

def _count_matches(lowered: str, patterns: set[str]) -> int:
    """Count how many distinct patterns appear in *lowered*."""
    hits = 0
    for pat in patterns:
        if pat in lowered:
            hits += 1
    return hits


def _has_security_context(lowered: str) -> bool:
    return any(term in lowered for term in _SECURITY_CONTEXT)


def _build_competitor_patterns(competitors: list[str]) -> dict[str, set[str]]:
    """Build per-intent keyword sets that include competitor names."""
    comp_lower = [c.lower().strip() for c in competitors if c.strip()]
    complain: set[str] = set()
    alternative: set[str] = set()
    for c in comp_lower:
        complain.update({
            f"tired of {c}", f"hate {c}", f"{c} sucks",
            f"{c} problem", f"frustrated with {c}",
            f"{c} is bad", f"{c} terrible",
        })
        alternative.update({
            f"alternative to {c}", f"switching from {c}",
            f"moving away from {c}", f"replace {c}",
            f"cheaper than {c}", f"better than {c}",
            f"leave {c}", f"quit {c}",
        })
    return {"complain": complain, "alternative": alternative}


def classify_intent(text: str, brand_profile: dict | None = None) -> IntentResult:
    """Classify the intent of *text* using fast heuristic patterns.

    Args:
        text: Raw post title + body.
        brand_profile: Optional dict with ``competitors`` list for
            competitor-aware classification.

    Returns:
        IntentResult with intent label, confidence (0.0–1.0), and a
        human-readable reason string.
    """
    lowered = normalize_phrase(text)
    if not lowered:
        return IntentResult(
            intent="irrelevant",
            confidence=0.0,
            reason="Empty text — cannot classify.",
        )

    # ── Hard reject: spam ─────────────────────────────────────────────
    spam_hits = _count_matches(lowered, _SPAM)
    if spam_hits >= 2:
        return IntentResult(
            intent="spam",
            confidence=0.95,
            reason=f"Multiple spam signals detected ({spam_hits} hits).",
        )
    if spam_hits == 1 and len(lowered.split()) < 30:
        return IntentResult(
            intent="spam",
            confidence=0.85,
            reason="Spam signal detected in short promotional text.",
        )

    # ── Hard reject: unsafe ───────────────────────────────────────────
    unsafe_hits = _count_matches(lowered, _UNSAFE)
    if unsafe_hits >= 1 and not _has_security_context(lowered):
        return IntentResult(
            intent="unsafe",
            confidence=0.9,
            reason="Unsafe keywords detected without security context.",
        )

    # ── Competitor-aware intents ──────────────────────────────────────
    competitors = []
    if brand_profile and isinstance(brand_profile.get("competitors"), list):
        competitors = brand_profile["competitors"]
    comp_patterns = _build_competitor_patterns(competitors)

    comp_complain_hits = _count_matches(lowered, comp_patterns["complain"])
    comp_alt_hits = _count_matches(lowered, comp_patterns["alternative"])

    if comp_complain_hits >= 1:
        return IntentResult(
            intent="complaining_about_competitor",
            confidence=min(0.75 + comp_complain_hits * 0.05, 0.95),
            reason=f"Competitor complaint detected ({comp_complain_hits} hit(s)).",
        )
    if comp_alt_hits >= 1:
        return IntentResult(
            intent="looking_for_alternative",
            confidence=min(0.75 + comp_alt_hits * 0.05, 0.95),
            reason=f"Alternative-seeking language detected ({comp_alt_hits} hit(s)).",
        )

    # Also catch generic competitor phrases without a named competitor
    generic_alt_hits = _count_matches(lowered, {
        "alternative to", "switching from", "moving away from",
        "replace ", "cheaper than", "better than",
    })
    if generic_alt_hits >= 1:
        return IntentResult(
            intent="looking_for_alternative",
            confidence=0.7,
            reason="Generic alternative-seeking language detected.",
        )

    # ── Standard intent classification ────────────────────────────────
    best_intent = "irrelevant"
    best_hits = 0
    best_reason = "No strong intent signals found."

    for intent_name, patterns, reason_template in _INTENT_ORDER:
        hits = _count_matches(lowered, patterns)
        if hits > best_hits:
            best_hits = hits
            best_intent = intent_name
            best_reason = reason_template

    # ── Confidence scoring ────────────────────────────────────────────
    if best_hits >= 3:
        confidence = min(0.8 + (best_hits - 3) * 0.03, 0.98)
    elif best_hits == 2:
        confidence = 0.6
    elif best_hits == 1:
        confidence = 0.4
    else:
        confidence = 0.2
        best_intent = "irrelevant"
        best_reason = "No recognizable intent patterns."

    # Boost confidence for very explicit multi-word phrases
    if best_hits >= 2 and any(
        phrase in lowered
        for phrase in [
            "looking for recommendations",
            "can anyone recommend",
            "what should i use",
            "struggling with",
            "how do i",
        ]
    ):
        confidence = min(confidence + 0.1, 0.98)

    return IntentResult(
        intent=best_intent,
        confidence=round(confidence, 2),
        reason=f"{best_reason.capitalize()} ({best_hits} pattern hit(s)).",
    )
