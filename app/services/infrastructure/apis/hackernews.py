"""Hacker News API client.

Thin wrapper around the official HN Firebase REST API with:
- Rate limiting (30 requests per 10 seconds)
- In-memory caching (5-minute TTL)
- httpx for HTTP requests
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://hacker-news.firebaseio.com/v0"
_DEFAULT_LIMIT = 50
_CACHE_TTL_SECONDS = 300.0
_MAX_REQ_PER_10S = 30
_MIN_INTERVAL = 10.0 / _MAX_REQ_PER_10S  # ≈ 0.333s


class HackerNewsAPI:
    """Client for the Hacker News Firebase API."""

    def __init__(self, *, timeout: float = 15.0) -> None:
        self._client = httpx.Client(
            base_url=_BASE_URL,
            timeout=timeout,
            follow_redirects=True,
        )
        self._cache: dict[str, tuple[float, Any]] = {}
        self._last_request_time: float = 0.0
        self._min_interval: float = _MIN_INTERVAL

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HackerNewsAPI:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # ── Feed endpoints ─────────────────────────────────────────────────

    def get_top_story_ids(self, limit: int = _DEFAULT_LIMIT) -> list[int]:
        """Return top story IDs (up to *limit*)."""
        return self._get_story_ids("topstories", limit=limit)

    def get_new_story_ids(self, limit: int = _DEFAULT_LIMIT) -> list[int]:
        """Return new story IDs (up to *limit*)."""
        return self._get_story_ids("newstories", limit=limit)

    def get_ask_story_ids(self, limit: int = 30) -> list[int]:
        """Return Ask HN story IDs (up to *limit*)."""
        return self._get_story_ids("askstories", limit=limit)

    def get_show_story_ids(self, limit: int = 30) -> list[int]:
        """Return Show HN story IDs (up to *limit*)."""
        return self._get_story_ids("showstories", limit=limit)

    # ── Item endpoint ──────────────────────────────────────────────────

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        """Fetch a single item by ID.

        Returns a dict with keys such as:
        - id, type, by, time, title, text, url, score, descendants
        - kids (list of comment IDs)
        """
        path = f"/item/{item_id}.json"
        data = self._get(path)
        if not isinstance(data, dict):
            return None
        return data

    # ── Internal helpers ───────────────────────────────────────────────

    def _get_story_ids(self, endpoint: str, limit: int) -> list[int]:
        """Fetch a list of story IDs from a feed endpoint."""
        data = self._get(f"/{endpoint}.json")
        if isinstance(data, list):
            return [int(x) for x in data[:limit] if isinstance(x, int) or str(x).isdigit()]
        return []

    def _get(self, path: str) -> Any:
        """Cached GET with rate limiting."""
        now = time.time()

        # Check cache
        cached = self._cache.get(path)
        if cached is not None:
            cached_at, value = cached
            if (now - cached_at) < _CACHE_TTL_SECONDS:
                return value

        # Rate limiting
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

        response: httpx.Response | None = None
        for attempt in range(3):
            try:
                response = self._client.get(path)
                self._last_request_time = time.time()
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning("HN connection error on %s (attempt %d/3): %s", path, attempt + 1, exc)
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise

            if response.status_code == 429:
                wait = min(2 ** attempt * 2, 10)
                logger.warning("HN 429 rate-limited on %s; waiting %ds (attempt %d/3)", path, wait, attempt + 1)
                time.sleep(wait)
                continue

            response.raise_for_status()
            data = response.json()
            self._cache[path] = (time.time(), data)
            return data

        if response is None:
            raise RuntimeError(f"HN request did not execute for {path}")
        response.raise_for_status()
        return response.json()
