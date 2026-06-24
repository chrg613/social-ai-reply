from __future__ import annotations

import re
from dataclasses import dataclass

GENERIC_SINGLE_WORDS = {
    "about",
    "advice",
    "after",
    "around",
    "away",
    "back",
    "before",
    "best",
    "better",
    "build",
    "built",
    "check",
    "company",
    "content",
    "customer",
    "customers",
    "discover",
    "engage",
    "engagement",
    "find",
    "finding",
    "first",
    "from",
    "get",
    "getting",
    "good",
    "great",
    "grow",
    "growth",
    "help",
    "helps",
    "home",
    "idea",
    "improve",
    "individual",
    "individuals",
    "just",
    "learn",
    "like",
    "looking",
    "made",
    "make",
    "more",
    "need",
    "online",
    "platform",
    "problem",
    "product",
    "question",
    "really",
    "reply",
    "said",
    "service",
    "solution",
    "some",
    "strategy",
    "team",
    "their",
    "there",
    "these",
    "they",
    "thing",
    "this",
    "thread",
    "threads",
    "tool",
    "tools",
    "use",
    "used",
    "using",
    "want",
    "way",
    "what",
    "when",
    "with",
    "work",
    "working",
    "would",
    "your",
    "you",
}

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "our",
    "out",
    "s",
    "so",
    "than",
    "that",
    "the",
    "them",
    "to",
    "up",
    "we",
    "who",
}

ROLE_TERMS = {
    "agency",
    "agencies",
    "broker",
    "brokers",
    "buyer",
    "buyers",
    "developer",
    "developers",
    "founder",
    "founders",
    "manager",
    "managers",
    "marketer",
    "marketers",
    "operator",
    "operators",
    "realtor",
    "realtors",
    "sales",
    "seller",
    "sellers",
    "startup",
    "startups",
}

KNOWN_GEO_TERMS = {
    "america",
    "asia",
    "australia",
    "britain",
    "canada",
    "delhi",
    "dubai",
    "europe",
    "india",
    "indian",
    "london",
    "local",
    "mumbai",
    "remote",
    "singapore",
    "uk",
    "usa",
}

AMBIGUOUS_CONTEXTLESS_TERMS = {
    "ai",
    "ar",
    "automated",
    "automation",
    "digital",
    "driven",
    "first",
    "intelligent",
    "llm",
    "ml",
    "modern",
    "next",
    "online",
    "powered",
    "real",
    "smart",
    "virtual",
    "vr",
}

EDGE_MODIFIER_TOKENS = {
    "ai",
    "ar",
    "automated",
    "automation",
    "based",
    "built",
    "compare",
    "comparing",
    "connect",
    "connecting",
    "dedicated",
    "discover",
    "discovering",
    "driven",
    "earn",
    "earning",
    "facilitate",
    "facilitates",
    "enabled",
    "eliminate",
    "eliminates",
    "exact",
    "experience",
    "find",
    "finding",
    "first",
    "free",
    "guided",
    "hassle",
    "immersive",
    "interested",
    "leverage",
    "leverages",
    "llm",
    "locations",
    "looking",
    "ml",
    "modern",
    "next",
    "powered",
    "quality",
    "seeking",
    "support",
    "transparent",
    "transparency",
    "utilize",
    "utilizes",
    "verified",
    "vr",
}

MARKETING_NOISE_TOKENS = {
    "assisted",
    "based",
    "dedicated",
    "details",
    "enabled",
    "exact",
    "experience",
    "facilitate",
    "facilitates",
    "features",
    "free",
    "guided",
    "hassle",
    "immersive",
    "interested",
    "innovation",
    "innovative",
    "leverage",
    "leverages",
    "locations",
    "looking",
    "modern",
    "offer",
    "offering",
    "offers",
    "program",
    "programs",
    "provide",
    "provides",
    "quality",
    "relationship",
    "rewards",
    "seeking",
    "service",
    "services",
    "smart",
    "solution",
    "solutions",
    "support",
    "transparent",
    "transparency",
    "transaction",
    "user",
    "users",
    "utilize",
    "utilizes",
    "verified",
    "workflow",
    "workflows",
    "documentation",
    "management",
    "platform",
    "platforms",
}

PHRASE_CONTINUATION_TOKENS = {
    "for",
    "in",
    "interested",
    "looking",
    "need",
    "needs",
    "seeking",
    "to",
    "want",
    "wants",
    "with",
    "without",
}

HIGH_INTENT_PHRASES = (
    "any advice",
    "any recommendations",
    "best tool",
    "best tools",
    "best way",
    "can anyone recommend",
    "how can",
    "how do",
    "how should",
    "looking for",
    "need help",
    "need recommendations",
    "recommend a",
    "recommend any",
    "recommendations for",
    "struggling with",
    "what should i use",
    "what tool",
    "which tool",
)

COMPARISON_TERMS = (
    "alternative to",
    "alternatives to",
    "compare",
    "comparison",
    "vs ",
    "versus",
)

QUESTION_WORDS = {"how", "what", "which", "who", "where", "why", "can", "should"}

OFFTOPIC_COMMUNITY_NAMES = {
    "askreddit",
    "hbo",
    "movies",
    "netflix",
    "television",
}

OFFTOPIC_COMMUNITY_TERMS = {
    "anime",
    "beermoney",
    "celebrity",
    "cricket",
    "episode",
    "fantasy football",
    "funny",
    "gaming",
    "giveaway",
    "meme",
    "memes",
    "movie",
    "movies",
    "music",
    "nsfw",
    "piracy",
    "reality show",
    "sports",
    "streaming",
    "television",
    "tv show",
}

EDGE_STRIP_TOKENS = STOP_WORDS | EDGE_MODIFIER_TOKENS
DOMAIN_CONTEXT_LIMIT = 8
DOMAIN_ANCHOR_LIMIT = 12
MAX_QUERY_WORDS = 4

# ── Domain-specific vocabulary ──────────────────────────────────────────
# Maps a business domain label to terms that MUST appear in relevant content.
# When a business_domain is set, posts missing ALL of these terms are penalized.
DOMAIN_VOCABULARY: dict[str, set[str]] = {
    "real estate": {
        "real estate", "property", "properties", "apartment", "apartments",
        "house", "houses", "rent", "rental", "mortgage", "realtor", "broker",
        "home buying", "home selling", "home buyer", "home buyers",
        "housing", "flat", "flats", "villa", "villas",
        "condo", "condos", "condominium", "residential", "commercial property",
        "plot", "plots", "land", "acre", "acres",
        "construction", "builder", "builders", "tenant", "tenants",
        "landlord", "landlords", "lease", "leasing", "bhk",
        "bedroom", "bedrooms", "sqft", "square feet", "listing", "listings",
        "mls", "neighborhood", "neighbourhood", "realty", "homeowner",
        "homeowners", "zoning", "down payment", "closing cost",
        "property tax", "home loan", "home inspection",
        "real estate agent", "property dealer", "property management",
    },
    "healthcare": {
        "health", "medical", "hospital", "doctor", "patient", "clinic",
        "pharma", "wellness", "therapy", "diagnosis", "treatment",
        "healthcare", "nurse", "prescription", "surgery", "disease",
        "symptom", "medicare", "insurance", "telemedicine",
    },
    "fintech": {
        "finance", "fintech", "banking", "payment", "invest", "loan",
        "credit", "insurance", "trading", "stock", "mutual fund", "wealth",
        "portfolio", "mortgage", "debit", "savings", "interest rate",
        "cryptocurrency", "blockchain", "budget", "accounting",
    },
    "edtech": {
        "education", "edtech", "learning", "course", "student", "tutor",
        "university", "school", "training", "certification", "e-learning",
        "curriculum", "teacher", "classroom", "exam", "lecture",
    },
    "ecommerce": {
        "ecommerce", "e-commerce", "shop", "shopping", "store", "marketplace",
        "retail", "buy online", "sell online", "product catalog", "cart",
        "checkout", "shipping", "delivery", "inventory", "merchant",
    },
    "travel": {
        "travel", "tourism", "hotel", "booking", "flight", "vacation",
        "trip", "destination", "hospitality", "resort", "airbnb",
        "itinerary", "passport", "visa", "tourist",
    },
    "food and restaurant": {
        "food", "restaurant", "delivery", "recipe", "cuisine", "dining",
        "chef", "catering", "meal", "menu", "order", "kitchen",
    },
    "marketing": {
        "marketing", "advertising", "seo", "social media", "content marketing",
        "brand", "campaign", "lead generation", "digital marketing",
        "analytics", "conversion", "engagement", "audience",
    },
    "developer tools": {
        "developer", "api", "sdk", "devops", "code", "programming",
        "framework", "library", "open source", "github", "deploy",
        "infrastructure", "backend", "frontend", "database",
    },
    "saas": {
        "saas", "software", "subscription", "churn", "mrr", "arr",
        "onboarding", "pricing", "freemium", "trial", "b2b", "b2c",
        "customer success", "feature request", "roadmap", "integration",
        "api", "dashboard", "analytics", "workflow", "automation",
        "user retention", "product market fit", "growth",
    },
    "legal": {
        "legal", "lawyer", "attorney", "law firm", "contract", "litigation",
        "compliance", "regulation", "lawsuit", "court", "paralegal",
        "intellectual property", "patent", "trademark", "copyright",
    },
    "logistics": {
        "logistics", "shipping", "freight", "warehouse", "supply chain",
        "delivery", "fleet", "tracking", "fulfillment", "inventory",
        "distribution", "carrier", "last mile", "courier",
    },
    "automotive": {
        "automotive", "car", "cars", "vehicle", "vehicles", "auto",
        "dealership", "mechanic", "repair", "maintenance", "ev",
        "electric vehicle", "test drive", "lease", "trade in",
    },
    "fitness": {
        "fitness", "gym", "workout", "exercise", "training", "coach",
        "nutrition", "diet", "weight loss", "muscle", "personal trainer",
        "yoga", "crossfit", "running", "strength",
    },
}
STRUCTURE_SPLIT_PATTERN = re.compile(
    r"[.;:|()\[\]\n]+|,\s+|\b(?:offering|offers?|provides?|providing|features?|featuring|includes?|including|"
    r"focused on|focuses on|aiming to|based in|based|dedicated to|designed for|designed to|built for|built to|"
    r"helping|helps?|enables?|looking to|looking for|interested in|seeking|through|via|using|with|for|and)\b"
)


@dataclass(frozen=True)
class DomainContext:
    brand_phrase: str | None = None
    core_phrases: tuple[str, ...] = ()
    audience_phrases: tuple[str, ...] = ()
    anchor_terms: tuple[str, ...] = ()
    business_domain: str = ""


@dataclass(frozen=True)
class DomainMatch:
    aligned: bool
    score: int
    phrase_hits: tuple[str, ...] = ()
    audience_hits: tuple[str, ...] = ()
    token_hits: tuple[str, ...] = ()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def normalize_phrase(text: str) -> str:
    return normalize_text(text)


def tokenize(text: str) -> list[str]:
    return [token for token in normalize_phrase(text).split() if token]


def split_csv_terms(text: str | None) -> list[str]:
    if not text:
        return []
    merged_terms: list[str] = []
    for segment in re.split(r"[/;\n]+", text):
        segment_terms: list[str] = []
        parts = [normalize_phrase(part) for part in re.split(r",\s+", segment) if normalize_phrase(part)]
        for raw in parts:
            normalized = re.sub(r"^(and|or)\s+", "", raw).strip()
            normalized = re.sub(r"\s+(and|or)$", "", normalized).strip()
            if not normalized:
                continue
            if segment_terms and _should_merge_term(segment_terms[-1], normalized):
                segment_terms[-1] = normalize_phrase(f"{segment_terms[-1]} {normalized}")
                continue
            segment_terms.append(normalized)
        merged_terms.extend(segment_terms)

    deduped: list[str] = []
    seen: set[str] = set()
    for term in merged_terms:
        if not term or term in seen:
            continue
        deduped.append(term)
        seen.add(term)
    return deduped


def is_low_signal_keyword(keyword: str) -> bool:
    normalized = normalize_phrase(keyword)
    if not normalized:
        return True
    meaningful = [word for word in normalized.split() if word not in STOP_WORDS]
    if not meaningful:
        return True
    if len(meaningful) == 1:
        word = meaningful[0]
        if word in ROLE_TERMS or word in KNOWN_GEO_TERMS:
            return False
        if len(word) < 4 or word in GENERIC_SINGLE_WORDS or word in AMBIGUOUS_CONTEXTLESS_TERMS:
            return True
    return all(word in GENERIC_SINGLE_WORDS or word in AMBIGUOUS_CONTEXTLESS_TERMS for word in meaningful)


def keyword_specificity(keyword: str) -> int:
    normalized = normalize_phrase(keyword)
    meaningful = [word for word in normalized.split() if word not in STOP_WORDS]
    if not meaningful:
        return 0
    score = 18 + len(meaningful) * 18 + min(sum(min(len(word), 8) for word in meaningful), 32)
    if len(meaningful) == 1 and meaningful[0] not in ROLE_TERMS and meaningful[0] not in KNOWN_GEO_TERMS:
        score -= 18
    if any(word in GENERIC_SINGLE_WORDS or word in AMBIGUOUS_CONTEXTLESS_TERMS for word in meaningful):
        score -= 8
    if len(normalized) >= 18:
        score += 6
    return max(0, min(score, 100))


def select_high_signal_keywords(
    keywords: list[str],
    *,
    brand_name: str | None = None,
    limit: int = 8,
    domain_context: DomainContext | None = None,
) -> list[str]:
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()

    if brand_name:
        normalized_brand = normalize_phrase(brand_name)
        if normalized_brand and normalized_brand not in seen and len(normalized_brand) >= 4:
            ranked.append((max(keyword_specificity(normalized_brand), 92), normalized_brand))
            seen.add(normalized_brand)

    for keyword in keywords:
        normalized = canonicalize_keyword_phrase(keyword, domain_context=domain_context)
        if not normalized or normalized in seen or is_low_signal_keyword(normalized):
            continue
        specificity = keyword_specificity(normalized)
        if (
            specificity < 20
            and normalized not in ROLE_TERMS
            and normalized not in KNOWN_GEO_TERMS
            and normalized not in (domain_context.anchor_terms if domain_context else ())
        ):
            continue
        if domain_context and normalized != normalize_phrase(brand_name or ""):
            if not keyword_matches_domain_context(normalized, domain_context):
                continue
            specificity += domain_keyword_score(normalized, domain_context)
        ranked.append((specificity + _query_shape_bonus(normalized), normalized))
        seen.add(normalized)

    ranked.sort(key=lambda item: (item[0], -abs(len(item[1].split()) - 3), -len(item[1])), reverse=True)

    ordered_keywords = [keyword for _score, keyword in ranked]
    selected: list[str] = []
    seen_selected: set[str] = set()

    def add_selected(keyword: str) -> None:
        if keyword and keyword not in seen_selected and keyword in ordered_keywords and len(selected) < limit:
            selected.append(keyword)
            seen_selected.add(keyword)

    if brand_name:
        add_selected(normalize_phrase(brand_name))

    if domain_context:
        core_candidates = [
            canonicalize_keyword_phrase(phrase, domain_context=domain_context)
            for phrase in domain_context.core_phrases
        ]
        audience_candidates = [
            canonicalize_keyword_phrase(phrase, domain_context=domain_context)
            for phrase in domain_context.audience_phrases
        ]

        for phrase in core_candidates[:4]:
            add_selected(phrase)
        for phrase in audience_candidates[:3]:
            add_selected(phrase)
        for phrase in core_candidates[4:]:
            add_selected(phrase)
        for phrase in audience_candidates[3:]:
            add_selected(phrase)
        for anchor in domain_context.anchor_terms:
            add_selected(anchor)

    for keyword in ordered_keywords:
        add_selected(keyword)

    return selected[:limit]


def extract_structured_phrases(
    text: str,
    *,
    min_words: int = 2,
    max_words: int = 4,
    limit: int = 12,
) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()

    for fragment in _split_structured_fragments(text):
        for tokens in _fragment_token_groups(fragment, min_words=min_words):
            for phrase in _fragment_phrase_variants(tokens, min_words=min_words, max_words=max_words):
                if phrase in seen or is_low_signal_keyword(phrase):
                    continue
                specificity = keyword_specificity(phrase) + _query_shape_bonus(phrase)
                if specificity < 48:
                    continue
                seen.add(phrase)
                candidates.append((specificity, phrase))

    candidates.sort(key=lambda item: (item[0], -abs(len(item[1].split()) - 3), -len(item[1])), reverse=True)
    return [phrase for _score, phrase in candidates[:limit]]


def check_domain_vocabulary_match(text: str, business_domain: str) -> tuple[bool, int, list[str]]:
    """Check whether *text* contains terms from the known vocabulary for *business_domain*.

    Returns ``(has_match, match_count, matched_terms)``.
    When *business_domain* is empty or not recognised the function returns
    ``(True, 0, [])`` so that the caller treats it as a no-op rather than a
    rejection.

    Uses word-boundary matching for single-word terms to avoid false positives
    like "property" matching inside "properly" or "real" inside "unrealistic".
    Multi-word terms use simple substring matching since they are naturally
    more specific.
    """
    if not business_domain:
        return True, 0, []
    vocab = DOMAIN_VOCABULARY.get(business_domain.lower())
    if not vocab:
        return True, 0, []
    lowered = text.lower()
    matched: list[str] = []
    for term in vocab:
        if " " in term:
            # Multi-word terms: substring is safe (e.g. "real estate" is specific)
            if term in lowered:
                matched.append(term)
        else:
            # Single-word terms: require word boundary to avoid partial matches
            if re.search(rf"\b{re.escape(term)}\b", lowered):
                matched.append(term)
    return bool(matched), len(matched), matched[:8]


def build_domain_context(
    *,
    brand_name: str | None = None,
    summary: str | None = None,
    product_summary: str | None = None,
    target_audience: str | None = None,
    keywords: list[str] | None = None,
    extra_texts: list[str] | None = None,
    business_domain: str = "",
) -> DomainContext:
    brand_phrase = normalize_phrase(brand_name) if brand_name else None
    phrase_scores: dict[str, int] = {}
    audience_terms = split_csv_terms(target_audience)
    anchor_scores = _ranked_anchor_scores(
        summary=summary,
        product_summary=product_summary,
        target_audience=target_audience,
        keywords=keywords,
        extra_texts=extra_texts,
    )

    def add_phrase(raw_phrase: str, weight: int) -> None:
        normalized = canonicalize_keyword_phrase(raw_phrase, max_words=MAX_QUERY_WORDS)
        if not normalized or normalized == brand_phrase or is_low_signal_keyword(normalized):
            return
        meaningful = [token for token in normalized.split() if token not in STOP_WORDS]
        anchor_tokens = _domain_anchor_tokens(normalized)
        if not meaningful:
            return
        if not anchor_tokens and normalized not in audience_terms:
            return
        if all(token in AMBIGUOUS_CONTEXTLESS_TERMS for token in meaningful):
            return
        phrase_scores[normalized] = max(
            phrase_scores.get(normalized, 0),
            keyword_specificity(normalized)
            + weight
            + _query_shape_bonus(normalized)
            + _phrase_anchor_bonus(normalized, anchor_scores),
        )

    for source, weight, per_source_limit in [
        (product_summary or "", 18, 12),
        (summary or "", 14, 10),
    ]:
        for phrase in extract_structured_phrases(source, limit=per_source_limit):
            add_phrase(phrase, weight)

    for audience in audience_terms:
        add_phrase(audience, 14 if len(audience.split()) > 1 else 8)

    for keyword in keywords or []:
        normalized = normalize_phrase(keyword)
        if not normalized or is_low_signal_keyword(normalized):
            continue
        add_phrase(normalized, 12 if len(normalized.split()) > 1 else 6)

    for source in extra_texts or []:
        for phrase in extract_structured_phrases(source, limit=4):
            add_phrase(phrase, 10)

    ranked_phrases = sorted(
        phrase_scores.items(),
        key=lambda item: (item[1], len(item[0].split()), len(item[0])),
        reverse=True,
    )
    core_phrases = tuple(phrase for phrase, _score in ranked_phrases[:DOMAIN_CONTEXT_LIMIT])

    anchor_terms = tuple(
        token
        for token, _score in sorted(
            anchor_scores.items(),
            key=lambda item: (item[1], len(item[0])),
            reverse=True,
        )[:DOMAIN_ANCHOR_LIMIT]
    )

    return DomainContext(
        brand_phrase=brand_phrase,
        core_phrases=core_phrases,
        audience_phrases=tuple(audience_terms),
        anchor_terms=anchor_terms,
        business_domain=business_domain,
    )


def assess_domain_match(text: str, context: DomainContext | None) -> DomainMatch:
    normalized = normalize_phrase(text)
    if not normalized or not context:
        return DomainMatch(aligned=False, score=0)

    token_set = set(tokenize(normalized))
    phrase_hits = tuple(
        phrase
        for phrase in context.core_phrases
        if phrase
        and len(phrase.split()) >= 2
        and (phrase in normalized or _partial_phrase_hit(phrase, token_set))
    )
    audience_hits = tuple(phrase for phrase in context.audience_phrases if phrase and phrase in normalized)
    token_hits = tuple(token for token in context.anchor_terms if token in token_set)
    multiword_audience_hits = tuple(hit for hit in audience_hits if len(hit.split()) >= 2)

    # ── Domain-vocabulary gate ──────────────────────────────────────────
    # When a business_domain is known, require at least one domain-vocab
    # term in the text for it to count as aligned.  This prevents posts
    # that happen to share generic keywords (e.g. "VR" from a real-estate
    # site) from being treated as domain-relevant.
    domain_vocab_ok, domain_vocab_count, _ = check_domain_vocabulary_match(text, context.business_domain)

    base_aligned = bool(phrase_hits or multiword_audience_hits or len(token_hits) >= 2)

    score = min(len(phrase_hits) * 14 + len(multiword_audience_hits) * 6 + len(token_hits) * 4, 36)

    # Bonus for strong domain-vocabulary presence
    if domain_vocab_count >= 2:
        score = min(score + min(domain_vocab_count * 4, 16), 36)

    if context.business_domain:
        if domain_vocab_ok:
            # At least one curated domain-vocabulary term is present — the
            # post is topically relevant to the business domain.
            aligned = True
        elif base_aligned and (len(phrase_hits) >= 2 or len(token_hits) >= 3):
            # No explicit domain vocab, but strong keyword/phrase overlap
            # suggests genuine relevance — allow through with reduced score.
            aligned = True
            score = max(score - 8, 0)
        else:
            # Weak overlap and no domain vocab — likely off-topic.
            aligned = False
    else:
        aligned = base_aligned

    return DomainMatch(
        aligned=aligned,
        score=score,
        phrase_hits=phrase_hits[:4],
        audience_hits=audience_hits[:3],
        token_hits=token_hits[:5],
    )


def keyword_matches_domain_context(keyword: str, context: DomainContext | None) -> bool:
    normalized = normalize_phrase(keyword)
    if not normalized or not context:
        return bool(normalized)
    if context.brand_phrase and normalized == context.brand_phrase:
        return True
    if normalized in context.core_phrases or normalized in context.audience_phrases:
        return True
    tokens = normalized.split()
    anchor_overlap = set(_domain_anchor_tokens(normalized)) & set(context.anchor_terms)
    if len(tokens) == 1:
        return normalized in context.anchor_terms and normalized not in AMBIGUOUS_CONTEXTLESS_TERMS
    if len(anchor_overlap) >= 2:
        return True
    if len(anchor_overlap) == 1 and len(tokens) <= 3 and not any(token in AMBIGUOUS_CONTEXTLESS_TERMS for token in tokens):
        return True
    return assess_domain_match(normalized, context).aligned


def domain_keyword_score(keyword: str, context: DomainContext | None) -> int:
    normalized = normalize_phrase(keyword)
    if not normalized or not context:
        return 0
    match = assess_domain_match(normalized, context)
    if match.score:
        return match.score
    if normalized in context.audience_phrases:
        return 8 if len(normalized.split()) >= 2 else 4
    if len(normalized.split()) == 1 and normalized in context.anchor_terms:
        return 6
    return min(len(set(_domain_anchor_tokens(normalized)) & set(context.anchor_terms)) * 6, 18)


def extract_geo_terms(text: str, *, limit: int = 3) -> list[str]:
    matches: list[str] = []
    seen: set[str] = set()
    for token in tokenize(text):
        if token not in KNOWN_GEO_TERMS or token in seen:
            continue
        matches.append(token)
        seen.add(token)
        if len(matches) >= limit:
            break
    return matches


def canonicalize_keyword_phrase(
    text: str,
    *,
    domain_context: DomainContext | None = None,
    max_words: int = MAX_QUERY_WORDS,
) -> str:
    normalized = normalize_phrase(text)
    if not normalized:
        return ""

    tokens = _clean_fragment_tokens(normalized)
    if not tokens:
        return ""
    if len(tokens) <= max_words:
        return " ".join(tokens)

    variants: list[str] = []
    for group in _token_groups(tokens, min_words=2):
        variants.extend(_fragment_phrase_variants(group, min_words=2, max_words=max_words))
    if domain_context:
        variants = [phrase for phrase in variants if keyword_matches_domain_context(phrase, domain_context)]
    if variants:
        ranked = sorted(
            variants,
            key=lambda phrase: _canonical_phrase_score(phrase, domain_context=domain_context),
            reverse=True,
        )
        return ranked[0]

    fallback = [
        token
        for token in tokens
        if token not in GENERIC_SINGLE_WORDS and token not in AMBIGUOUS_CONTEXTLESS_TERMS
    ]
    return " ".join(fallback[:max_words]).strip()


def meaningful_phrase_tokens(text: str) -> list[str]:
    return _meaningful_tokens(text)


def has_meaningful_phrase_overlap(phrase: str, token_set: set[str]) -> bool:
    tokens = _meaningful_tokens(phrase)
    if not tokens:
        return False
    token_hits = sum(1 for token in tokens if token in token_set)
    if len(tokens) == 1:
        return token_hits == 1
    if len(tokens) == 2:
        return token_hits == 2
    return token_hits >= len(tokens) - 1 and token_hits >= 2


def _domain_anchor_tokens(text: str) -> list[str]:
    return [
        token
        for token in tokenize(text)
        if token not in STOP_WORDS
        and token not in GENERIC_SINGLE_WORDS
        and token not in KNOWN_GEO_TERMS
        and token not in AMBIGUOUS_CONTEXTLESS_TERMS
        and token not in MARKETING_NOISE_TOKENS
        and (len(token) >= 4 or token in ROLE_TERMS)
    ]


def _meaningful_tokens(text: str) -> list[str]:
    return [token for token in tokenize(text) if token not in STOP_WORDS]


def _ranked_anchor_scores(
    *,
    summary: str | None,
    product_summary: str | None,
    target_audience: str | None,
    keywords: list[str] | None,
    extra_texts: list[str] | None,
) -> dict[str, int]:
    source_weights = [
        (product_summary or "", 4),
        (summary or "", 3),
        (target_audience or "", 3),
    ]
    source_weights.extend((keyword, 2) for keyword in keywords or [])
    source_weights.extend((text, 1) for text in extra_texts or [])

    anchor_scores: dict[str, int] = {}
    for source, weight in source_weights:
        if not source:
            continue
        seen_in_source: set[str] = set()
        for token in _domain_anchor_tokens(source):
            anchor_scores[token] = anchor_scores.get(token, 0) + weight
            if token not in seen_in_source:
                anchor_scores[token] += 1
                seen_in_source.add(token)
    return anchor_scores


def _phrase_anchor_bonus(phrase: str, anchor_scores: dict[str, int]) -> int:
    return min(sum(anchor_scores.get(token, 0) for token in _domain_anchor_tokens(phrase)), 24)


def _canonical_phrase_score(phrase: str, *, domain_context: DomainContext | None) -> int:
    score = keyword_specificity(phrase) + _query_shape_bonus(phrase)
    tokens = phrase.split()
    score -= sum(token in MARKETING_NOISE_TOKENS for token in tokens) * 8
    if tokens and tokens[-1] in MARKETING_NOISE_TOKENS:
        score -= 10
    if domain_context:
        score += len(set(_domain_anchor_tokens(phrase)) & set(domain_context.anchor_terms)) * 14
        score += assess_domain_match(phrase, domain_context).score
    return score


def _split_structured_fragments(text: str) -> list[str]:
    fragments: list[str] = []
    for fragment in STRUCTURE_SPLIT_PATTERN.split(text):
        normalized = normalize_phrase(fragment)
        normalized = re.sub(r"^(and|or)\s+", "", normalized).strip()
        normalized = re.sub(r"\s+(and|or)$", "", normalized).strip()
        if normalized:
            fragments.append(normalized)
    return fragments


def _should_merge_term(previous: str, current: str) -> bool:
    previous_tokens = tokenize(previous)
    current_tokens = tokenize(current)
    if not previous_tokens or not current_tokens:
        return False
    if (
        len(current_tokens) == 1
        and " in " in previous
        and current_tokens[0] not in ROLE_TERMS
        and current_tokens[0] not in GENERIC_SINGLE_WORDS
    ):
        return True
    if current in KNOWN_GEO_TERMS:
        return bool(" in " in previous or any(token in ROLE_TERMS or token in KNOWN_GEO_TERMS for token in previous_tokens))
    if previous_tokens[-1] in PHRASE_CONTINUATION_TOKENS:
        return True
    if current_tokens[0] in {"for", "to", "with", "without"}:
        return True
    return bool(set(previous_tokens) & {"interested", "looking", "need", "needs", "seeking", "want", "wants"})


def _clean_fragment_tokens(text: str) -> list[str]:
    tokens = [token for token in tokenize(text) if token and not token.isdigit()]
    while tokens and tokens[0] in EDGE_STRIP_TOKENS:
        tokens = tokens[1:]
    while tokens and tokens[-1] in EDGE_STRIP_TOKENS:
        tokens = tokens[:-1]
    return tokens


def _fragment_token_groups(text: str, *, min_words: int) -> list[list[str]]:
    tokens = _clean_fragment_tokens(text)
    return _token_groups(tokens, min_words=min_words)


def _token_groups(tokens: list[str], *, min_words: int) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in STOP_WORDS:
            if len(current) >= min_words:
                groups.append(current)
            current = []
            continue
        current.append(token)
    if len(current) >= min_words:
        groups.append(current)
    return groups


def _fragment_phrase_variants(
    tokens: list[str],
    *,
    min_words: int,
    max_words: int,
) -> list[str]:
    if len(tokens) < min_words:
        return []
    if len(tokens) <= max_words:
        phrase = " ".join(tokens)
        return [phrase] if not is_low_signal_keyword(phrase) else []

    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for size in range(max_words, min_words - 1, -1):
        for index in range(0, len(tokens) - size + 1):
            phrase_tokens = tokens[index:index + size]
            phrase = " ".join(phrase_tokens)
            if phrase in seen or is_low_signal_keyword(phrase):
                continue
            seen.add(phrase)
            candidates.append((_phrase_variant_score(phrase_tokens), phrase))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [phrase for _score, phrase in candidates[:3]]


def _phrase_variant_score(tokens: list[str]) -> int:
    phrase = " ".join(tokens)
    score = keyword_specificity(phrase) + _query_shape_bonus(phrase)
    score -= sum(token in AMBIGUOUS_CONTEXTLESS_TERMS for token in tokens) * 12
    score -= sum(token in GENERIC_SINGLE_WORDS for token in tokens) * 6
    score -= sum(token in MARKETING_NOISE_TOKENS for token in tokens) * 8
    if any(token.isdigit() for token in tokens):
        score -= 8
    if tokens and tokens[0] in EDGE_STRIP_TOKENS:
        score -= 8
    if tokens and tokens[-1] in EDGE_STRIP_TOKENS:
        score -= 8
    return score


def _query_shape_bonus(phrase: str) -> int:
    words = len(phrase.split())
    if words == 1:
        return 4
    if words == 2:
        return 14
    if words == 3:
        return 18
    if words == 4:
        return 10
    if words == 5:
        return 0
    return -12


def _partial_phrase_hit(phrase: str, token_set: set[str]) -> bool:
    tokens = _meaningful_tokens(phrase)
    if len(tokens) < 3:
        return False
    return sum(1 for token in tokens if token in token_set) >= len(tokens) - 1


def find_intent_hits(text: str) -> list[str]:
    lowered = text.lower()
    hits = [phrase for phrase in HIGH_INTENT_PHRASES if phrase in lowered]
    if "?" in text and any(token in QUESTION_WORDS for token in tokenize(text)):
        hits.append("direct question")
    if any(term in lowered for term in COMPARISON_TERMS):
        hits.append("comparison intent")
    deduped: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        normalized = normalize_phrase(hit)
        if not normalized or normalized in seen:
            continue
        deduped.append(normalized)
        seen.add(normalized)
    return deduped


def find_offtopic_signals(text: str) -> list[str]:
    lowered = text.lower()
    hits = [term for term in OFFTOPIC_COMMUNITY_TERMS if term in lowered]
    deduped: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        normalized = normalize_phrase(hit)
        if normalized in seen:
            continue
        deduped.append(normalized)
        seen.add(normalized)
    return deduped


# ── Self-promotion / non-opportunity detection ───────────────────────
# Posts where the author is showcasing their own work are not
# opportunities for engagement — the user is promoting, not seeking.

SELF_PROMO_PHRASES = (
    "i built",
    "i created",
    "i made",
    "i launched",
    "just launched",
    "just shipped",
    "check out my",
    "check out our",
    "i am building",
    "i'm building",
    "we built",
    "we created",
    "we launched",
    "we just launched",
    "introducing my",
    "introducing our",
    "my new project",
    "my new tool",
    "my side project",
    "our new product",
    "here is my",
    "here's my",
    "feedback on my",
    "try my",
    "try our",
    "i wrote a",
    "i developed",
    "we developed",
    "show hn",
    "show reddit",
    "[ad]",
    "sponsored",
    "promo code",
    "discount code",
    "use code",
    "affiliate",
)


def find_self_promo_signals(text: str) -> list[str]:
    """Detect phrases that indicate the author is promoting their own
    product/project rather than seeking help or recommendations.

    Returns a list of matched self-promotion phrases found in the text.
    """
    lowered = text.lower()
    hits: list[str] = []
    seen: set[str] = set()
    for phrase in SELF_PROMO_PHRASES:
        if phrase in lowered and phrase not in seen:
            hits.append(phrase)
            seen.add(phrase)
    return hits


def score_title_keyword_match(title: str, keywords: list[str]) -> tuple[list[str], int]:
    """Score keyword matches specifically in the post title.

    Title matches are a stronger relevance signal than body matches
    because the title captures the core topic of the post.

    Returns ``(matched_keywords, bonus_score)``.
    """
    normalized_title = normalize_phrase(title)
    title_tokens = set(tokenize(title))
    hits: list[str] = []
    score = 0

    for keyword in keywords:
        keyword_tokens = keyword.split()
        # Exact match in title
        if keyword in normalized_title:
            hits.append(keyword)
            score += 6  # bonus on top of regular match
            continue
        # Partial overlap for multi-word keywords
        if len(keyword_tokens) > 1:
            non_generic = [t for t in keyword_tokens if t not in STOP_WORDS and t not in GENERIC_SINGLE_WORDS]
            if non_generic and all(t in title_tokens for t in non_generic):
                hits.append(keyword)
                score += 4

    return hits, min(score, 18)


def intent_quality_score(intent_hits: list[str]) -> int:
    """Assign differentiated scores based on intent quality.

    Recommendation and comparison intents are highest value for
    engagement because the user is actively evaluating options.
    Direct questions are moderate. Generic help-seeking is lower.

    Returns a bonus score (0–12) based on the best intent quality found.
    """
    quality = 0
    for hit in intent_hits:
        lowered = hit.lower()
        # High-value: actively evaluating options
        if any(term in lowered for term in [
            "recommend", "recommendation", "alternative", "comparison",
            "compare", "versus", "best tool", "which tool", "what tool",
        ]):
            quality = max(quality, 12)
        # Medium-value: direct question
        elif "direct question" in lowered:
            quality = max(quality, 6)
        # Base: general help-seeking
        elif any(term in lowered for term in [
            "need help", "struggling", "looking for", "any advice",
        ]):
            quality = max(quality, 3)
    return quality
