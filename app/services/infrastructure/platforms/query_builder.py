"""Platform-optimized search query builder.

Transforms generic keyword lists into search strings tuned for each
platform's query syntax.  Pure string transformation — no LLM calls,
no database access.
"""

from __future__ import annotations


class QueryBuilder:
    """Transform generic keywords into platform-optimized search queries."""

    @staticmethod
    def build_query(keywords: list[str], platform: str) -> str:
        """Build a single optimized search query string for the given platform.

        Args:
            keywords: Raw keyword phrases (e.g. ``["virtual tour", "3D walkthrough"]``).
            platform: Target platform identifier (``twitter``, ``reddit``,
                ``instagram``, ``linkedin``, or anything else for the default).

        Returns:
            A ready-to-use query string formatted for *platform*.
        """
        cleaned = [kw.strip() for kw in keywords if kw.strip()]
        if not cleaned:
            return ""

        builder = _PLATFORM_BUILDERS.get(platform, _build_default)
        return builder(cleaned)

    @staticmethod
    def keywords_to_hashtags(keywords: list[str]) -> list[str]:
        """Convert keywords to hashtag-formatted strings for Instagram / Twitter.

        Multi-word phrases are collapsed and lower-cased:

        * ``"virtual tour"``  → ``"#virtualtour"``
        * ``"Real Estate"``   → ``"#realestate"``
        * ``"AI"``            → ``"#ai"``

        Args:
            keywords: Raw keyword phrases.

        Returns:
            De-duplicated list of hashtag strings.
        """
        seen: set[str] = set()
        hashtags: list[str] = []
        for kw in keywords:
            tag = "#" + kw.replace(" ", "").lower()
            if tag not in seen:
                seen.add(tag)
                hashtags.append(tag)
        return hashtags


# ---------------------------------------------------------------------------
# Private per-platform builders
# ---------------------------------------------------------------------------


def _build_twitter(keywords: list[str]) -> str:
    """Twitter/X: OR-join keywords, exclude retweets, English only."""
    joined = " OR ".join(keywords)
    return f"({joined}) -is:retweet lang:en"


def _build_reddit(keywords: list[str]) -> str:
    """Reddit: space-separated — the search API handles relevance."""
    return " ".join(keywords)


def _build_instagram(keywords: list[str]) -> str:
    """Instagram: hashtag candidates (collapsed, lower-cased)."""
    return " ".join(QueryBuilder.keywords_to_hashtags(keywords))


def _build_linkedin(keywords: list[str]) -> str:
    """LinkedIn: quote multi-word phrases so exact-match works."""
    parts: list[str] = []
    for kw in keywords:
        if " " in kw:
            parts.append(f'"{kw}"')
        else:
            parts.append(kw)
    return " ".join(parts)


def _build_default(keywords: list[str]) -> str:
    """Fallback: simple space-join."""
    return " ".join(keywords)


_PLATFORM_BUILDERS: dict[str, callable] = {
    "twitter": _build_twitter,
    "reddit": _build_reddit,
    "instagram": _build_instagram,
    "linkedin": _build_linkedin,
}
