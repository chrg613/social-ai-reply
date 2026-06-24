"""Reddit platform adapter — ReddAPI (reddapi.p.rapidapi.com).

Uses the "ReddAPI" by SeasonedCode on the RapidAPI marketplace.
Primary endpoints:
  - GET /api/v2/search/posts     — keyword search across Reddit
  - GET /api/v2/search/comments  — keyword search in comments
  - GET /api/v2/search/subreddits — find subreddits

Rate limit: 70 requests/month on free tier.
Strategy: use 2-3 requests per scan (keyword search + comment search)
instead of browsing each subreddit individually.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.infrastructure.platforms.base import PlatformAdapter
from app.services.infrastructure.platforms.models import UnifiedComment, UnifiedPost

logger = logging.getLogger(__name__)

REDDAPI_HOST = "reddapi.p.rapidapi.com"


class RedditAdapter(PlatformAdapter):
    """Reddit adapter using ReddAPI (reddapi.p.rapidapi.com).

    Uses keyword-based search (not per-subreddit browsing) to minimise
    API calls, since the free tier only gives 70 requests/month.
    """

    platform_name = "reddit"

    def __init__(self, api_host: str | None = None):
        self._subreddits: list[str] = []
        self._available = False

        from app.core.config import get_settings
        settings = get_settings()
        self._api_key = settings.rapidapi_key
        if self._api_key:
            self._available = True
            logger.info("Reddit adapter: using ReddAPI (reddapi.p.rapidapi.com)")
        else:
            logger.warning("Reddit adapter: no RAPIDAPI_KEY — disabled")

    def set_subreddits(self, subreddits: list[str]) -> None:
        """Set the list of monitored subreddits for relevance filtering."""
        self._subreddits = list(subreddits)

    # ── HTTP helpers ─────────────────────────────────────────────

    _reddapi_circuit_broken: float | None = None  # class-level circuit breaker

    async def _api_get(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Make a GET request to ReddAPI."""
        # Circuit breaker: skip if quota is known to be exhausted
        if RedditAdapter._reddapi_circuit_broken is not None:
            import time
            if time.monotonic() - RedditAdapter._reddapi_circuit_broken < 300:
                raise Exception("ReddAPI quota exhausted (circuit breaker active)")  # noqa: TRY002
            RedditAdapter._reddapi_circuit_broken = None
            logger.info("ReddAPI circuit breaker reset — retrying")

        headers = {
            "x-rapidapi-key": self._api_key,
            "x-rapidapi-host": REDDAPI_HOST,
        }
        url = f"https://{REDDAPI_HOST}{endpoint}"

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code == 429:
                import time
                remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
                logger.warning("ReddAPI rate limited (remaining=%s) — circuit breaker tripped", remaining)
                RedditAdapter._reddapi_circuit_broken = time.monotonic()
                raise Exception(f"ReddAPI rate limited (remaining={remaining})")  # noqa: TRY002
            resp.raise_for_status()
            return resp.json()

    # ── Post / Comment parsing ───────────────────────────────────

    def _parse_post(self, raw: dict[str, Any]) -> UnifiedPost:
        """Convert a ReddAPI post to UnifiedPost."""
        created_utc = raw.get("created_utc")
        created_at = None
        if created_utc:
            try:
                if isinstance(created_utc, (int, float)):
                    created_at = datetime.fromtimestamp(created_utc, tz=UTC)
                elif isinstance(created_utc, str):
                    created_at = datetime.fromisoformat(created_utc.replace("Z", "+00:00"))
            except (ValueError, OSError):
                pass

        title = raw.get("title") or ""
        body = raw.get("selftext") or raw.get("body") or ""
        subreddit = raw.get("subreddit") or ""
        if subreddit.startswith("r/"):
            subreddit = subreddit[2:]

        permalink = raw.get("permalink") or ""
        if permalink and not permalink.startswith("http"):
            permalink = f"https://www.reddit.com{permalink}"

        return UnifiedPost(
            platform="reddit",
            external_id=str(raw.get("id") or ""),
            author=str(raw.get("author") or ""),
            author_id="",
            title=title,
            body=body,
            url=permalink,
            subreddit=subreddit,
            upvotes=int(raw.get("score") or raw.get("ups") or 0),
            comments_count=int(raw.get("num_comments") or 0),
            shares=0,
            views=0,
            created_at=created_at,
            media_urls=self._extract_media(raw),
            raw_data=raw,
        )

    def _extract_media(self, raw: dict[str, Any]) -> list[str]:
        """Extract media URLs from a Reddit post."""
        media: list[str] = []
        if raw.get("thumbnail") and raw["thumbnail"].startswith("http"):
            media.append(raw["thumbnail"])
        if raw.get("url", "").endswith((".jpg", ".png", ".gif")):
            media.append(raw["url"])
        return media

    def _parse_comment(self, raw: dict[str, Any], post_id: str = "") -> UnifiedComment:
        """Convert a ReddAPI comment to UnifiedComment."""
        created_utc = raw.get("created_utc")
        created_at = None
        if created_utc and isinstance(created_utc, (int, float)):
            with contextlib.suppress(ValueError, OSError):
                created_at = datetime.fromtimestamp(created_utc, tz=UTC)

        return UnifiedComment(
            platform="reddit",
            external_id=str(raw.get("id") or ""),
            post_id=post_id or str(raw.get("post_id") or ""),
            author=str(raw.get("author") or ""),
            body=str(raw.get("body") or ""),
            upvotes=int(raw.get("score") or raw.get("ups") or 0),
            created_at=created_at,
            parent_comment_id=raw.get("parent_id"),
            raw_data=raw,
        )

    # ── Core API methods ─────────────────────────────────────────

    async def search_posts(
        self,
        keywords: list[str],
        *,
        limit: int = 50,
        sort: str = "relevance",
        time_filter: str = "week",
    ) -> list[UnifiedPost]:
        """Search Reddit posts by keywords via ReddAPI."""
        if not self._available:
            return []

        query = " OR ".join(keywords[:5])  # combine top keywords
        try:
            data = await self._api_get(
                "/api/v2/search/posts",
                params={
                    "query": query,
                    "limit": str(min(limit, 100)),
                    "sort": sort,
                },
            )
        except Exception as e:
            logger.warning("ReddAPI post search failed: %s", e)
            return []

        posts_raw = data.get("posts", [])
        posts = []
        for item in posts_raw[:limit]:
            try:
                if isinstance(item, dict):
                    posts.append(self._parse_post(item))
            except Exception as e:
                logger.debug("Failed to parse Reddit post: %s", e)

        logger.info("[reddit] Search '%s' → %d posts", query[:50], len(posts))
        return posts

    async def search_comments(
        self,
        keywords: list[str],
        *,
        limit: int = 25,
    ) -> list[UnifiedComment]:
        """Search Reddit comments by keywords via ReddAPI."""
        if not self._available:
            return []

        query = " OR ".join(keywords[:5])
        try:
            data = await self._api_get(
                "/api/v2/search/comments",
                params={
                    "query": query,
                    "limit": str(min(limit, 50)),
                },
            )
        except Exception as e:
            logger.warning("ReddAPI comment search failed: %s", e)
            return []

        comments_raw = data.get("comments", [])
        comments = []
        for item in comments_raw[:limit]:
            try:
                if isinstance(item, dict):
                    comments.append(self._parse_comment(item))
            except Exception as e:
                logger.debug("Failed to parse Reddit comment: %s", e)

        logger.info("[reddit] Comment search '%s' → %d comments", query[:50], len(comments))
        return comments

    async def get_subreddit_posts(
        self,
        subreddit: str,
        *,
        sort: str = "new",
        limit: int = 25,
    ) -> list[UnifiedPost]:
        """Search for posts mentioning the subreddit topic.

        ReddAPI doesn't have a per-subreddit browsing endpoint on free tier,
        so we use keyword search with the subreddit name as a hint.
        """
        if not self._available:
            return []

        try:
            data = await self._api_get(
                "/api/v2/search/posts",
                params={
                    "query": subreddit,
                    "limit": str(min(limit, 50)),
                    "sort": sort,
                    "subreddit": subreddit,
                },
            )
        except Exception as e:
            logger.warning("ReddAPI: failed to search r/%s: %s", subreddit, e)
            return []

        posts_raw = data.get("posts", [])
        posts = []
        for item in posts_raw[:limit]:
            try:
                if isinstance(item, dict):
                    posts.append(self._parse_post(item))
            except Exception as e:
                logger.debug("Failed to parse Reddit post: %s", e)

        logger.info("[reddit] r/%s search → %d posts", subreddit, len(posts))
        return posts

    async def get_post_comments(
        self,
        post_id: str,
        *,
        limit: int = 20,
    ) -> list[UnifiedComment]:
        """Search for comments related to a post.

        ReddAPI free tier doesn't have a per-post comments endpoint,
        so we search for comments using keywords from the post title.
        """
        # We don't have a per-post comments endpoint, return empty
        return []

    # ── search_and_enrich (efficient keyword-based scanning) ─────

    @staticmethod
    def _extract_broad_terms(keywords: list[str], subreddits: list[str]) -> list[str]:
        """Extract short, broad search terms from specific keyword phrases.

        Discovery keywords are often very specific (e.g. "tired of fake property
        listings gurugram").  Reddit search works better with short 1-2 word terms
        like "real estate" or "property investment".

        Strategy:
          1. Split every keyword phrase into individual words.
          2. Keep only words >= 4 chars, remove stop words and brand names.
          3. Build 2-word combinations from the most frequent words.
          4. Add subreddit names as bonus search terms.
        """
        stop_words = {
            "with", "from", "that", "this", "have", "will", "your", "what",
            "when", "where", "which", "there", "their", "about", "been",
            "some", "them", "than", "just", "also", "into", "most", "much",
            "know", "find", "need", "good", "best", "hard", "many", "very",
            "more", "like", "make", "does", "each", "only", "over", "such",
            "take", "even", "well", "back", "give", "want", "someone",
            "tired", "platform", "service", "online", "operators", "founders",
            "workflows", "assisted", "noise", "trusted", "verified",
        }

        # Collect meaningful words
        from collections import Counter
        word_freq: Counter[str] = Counter()
        for kw in keywords:
            words = kw.lower().split()
            for w in words:
                w = w.strip(".,!?;:'\"()[]")
                if len(w) >= 4 and w not in stop_words:
                    word_freq[w] += 1

        # Top words by frequency
        top_words = [w for w, _ in word_freq.most_common(15)]

        # Build search queries: 2-word combos from top words + single high-freq words
        queries: list[str] = []
        seen: set[str] = set()

        # 2-word combinations from top words
        for i, w1 in enumerate(top_words[:8]):
            for w2 in top_words[i + 1 : i + 4]:
                term = f"{w1} {w2}"
                if term not in seen:
                    queries.append(term)
                    seen.add(term)

        # Add subreddit names as search terms (great for finding relevant content)
        for sub in subreddits[:5]:
            sub_clean = sub.lower().replace("_", " ")
            if sub_clean not in seen and len(sub_clean) >= 4:
                queries.append(sub_clean)
                seen.add(sub_clean)

        # Add single high-frequency domain words
        for w in top_words[:5]:
            if w not in seen:
                queries.append(w)
                seen.add(w)

        return queries[:10]

    async def search_and_enrich(
        self,
        keywords: list[str],
        *,
        limit: int = 50,
        fetch_comments: bool = False,
        comments_per_post: int = 10,
        time_filter: str = "week",
    ) -> list[UnifiedPost]:
        """Efficient Reddit scanning using keyword search.

        Instead of browsing each subreddit (which would use 10+ API calls),
        this does 2-3 keyword searches to find relevant posts across ALL
        subreddits at once. Uses only 2-3 of our 70 monthly requests.

        Keywords are automatically broadened from specific discovery phrases
        to short, effective Reddit search terms.
        """
        if not self._available:
            return []

        all_posts: list[UnifiedPost] = []
        seen_ids: set[str] = set()

        # Extract broad search terms from specific keywords
        broad_terms = self._extract_broad_terms(keywords, self._subreddits)
        logger.info("[reddit] Broad search terms: %s", broad_terms[:8])

        # Build 2 search queries from broad terms (max 2 API calls for posts)
        queries: list[str] = []
        if broad_terms:
            # First query: top 4 terms OR-combined
            queries.append(" OR ".join(broad_terms[:4]))
            # Second query: next 4 terms (if available)
            if len(broad_terms) > 4:
                queries.append(" OR ".join(broad_terms[4:8]))

        if not queries:
            queries = ["discussion advice help"]

        for query in queries[:2]:
            try:
                data = await self._api_get(
                    "/api/v2/search/posts",
                    params={
                        "query": query,
                        "limit": str(min(limit, 100)),
                        "sort": "new",
                        "time": time_filter,
                    },
                )
                posts_raw = data.get("posts", [])
                for item in posts_raw:
                    try:
                        if isinstance(item, dict):
                            post = self._parse_post(item)
                            if post.external_id not in seen_ids:
                                all_posts.append(post)
                                seen_ids.add(post.external_id)
                    except Exception:
                        continue
                logger.info("[reddit] Search '%s' → %d posts", query[:50], len(posts_raw))
            except Exception as e:
                logger.warning("[reddit] Search failed for '%s': %s", query[:40], e)

            # Small delay between queries
            if len(queries) > 1:
                await asyncio.sleep(1)

        # Also search comments (1 API call) using broad terms
        comment_query = " OR ".join(broad_terms[:4]) if broad_terms else ""
        if comment_query:
            try:
                data = await self._api_get(
                    "/api/v2/search/comments",
                    params={
                        "query": comment_query,
                        "limit": "25",
                        "time": time_filter,
                    },
                )
                comments_raw = data.get("comments", [])
                # Convert high-engagement comments to pseudo-posts for opportunity scoring
                for item in comments_raw:
                    try:
                        if isinstance(item, dict) and item.get("body"):
                            # Create a post-like entry from the comment
                            parent = item.get("parent_post", {}) or {}
                            subreddit = item.get("subreddit") or ""
                            if subreddit.startswith("r/"):
                                subreddit = subreddit[2:]

                            permalink = item.get("permalink") or ""
                            if permalink and not permalink.startswith("http"):
                                permalink = f"https://www.reddit.com{permalink}"

                            created_utc = item.get("created_utc")
                            created_at = None
                            if created_utc and isinstance(created_utc, (int, float)):
                                with contextlib.suppress(ValueError, OSError):
                                    created_at = datetime.fromtimestamp(created_utc, tz=UTC)

                            post = UnifiedPost(
                                platform="reddit",
                                external_id=f"comment_{item.get('id', '')}",
                                author=str(item.get("author") or ""),
                                author_id="",
                                title=str(parent.get("title") or item.get("body", "")[:100]),
                                body=str(item.get("body") or ""),
                                url=permalink,
                                subreddit=subreddit,
                                upvotes=int(item.get("score") or 0),
                                comments_count=0,
                                shares=0,
                                views=0,
                                created_at=created_at,
                                media_urls=[],
                                raw_data={**item, "source_type": "comment"},
                            )
                            all_posts.append(post)
                    except Exception:
                        continue
                logger.info("[reddit] Comment search '%s' → %d comments", comment_query[:40], len(comments_raw))
            except Exception as e:
                logger.warning("[reddit] Comment search failed: %s", e)

        # Filter to monitored subreddits if any are set
        if self._subreddits:
            sub_set = {s.lower() for s in self._subreddits}
            before = len(all_posts)
            # Keep posts from monitored subreddits + any high-score posts from others
            filtered = []
            for post in all_posts:
                if post.subreddit.lower() in sub_set:
                    filtered.append(post)
                elif post.upvotes >= 10 or post.comments_count >= 5:
                    # Keep high-engagement posts even from non-monitored subreddits
                    filtered.append(post)
            all_posts = filtered
            logger.info("[reddit] Filtered %d → %d posts (monitored subs + high engagement)", before, len(all_posts))

        logger.info("[reddit] Total: %d posts from keyword search", len(all_posts))
        return all_posts

    # ── Trending & health check ──────────────────────────────────

    async def get_trending(
        self,
        *,
        topic: str | None = None,
        limit: int = 25,
    ) -> list[UnifiedPost]:
        """Get trending posts (uses search with general terms)."""
        if not self._available:
            return []

        query = topic or "trending"
        try:
            data = await self._api_get(
                "/api/v2/search/posts",
                params={"query": query, "limit": str(limit), "sort": "hot"},
            )
            posts_raw = data.get("posts", [])
            posts = []
            for item in posts_raw[:limit]:
                try:
                    if isinstance(item, dict):
                        posts.append(self._parse_post(item))
                except Exception:
                    continue
            return posts
        except Exception:
            return []

    async def health_check(self) -> bool:
        """Check if the ReddAPI is reachable."""
        if not self._available:
            return False
        try:
            data = await self._api_get(
                "/api/v2/search/subreddits",
                params={"query": "test", "limit": "1"},
            )
            return isinstance(data, dict) and data.get("success", False)
        except Exception:
            return False
