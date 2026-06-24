"""In-memory TTL cache for platform API responses.

Prevents burning API credits on repeated identical queries within a short
time window.  Thread-safe via :class:`threading.Lock`.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any


class PlatformCache:
    """In-memory TTL cache for platform API responses.

    Prevents burning API credits on repeated identical queries
    within a short time window.
    """

    def __init__(self, default_ttl: int = 900, max_size: int = 200) -> None:
        self._store: dict[str, tuple[float, str, Any]] = {}  # key -> (expires_at, platform, value)
        self._default_ttl = default_ttl  # 15 minutes
        self._max_size = max_size
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(platform: str, query: str) -> str:
        """Hash (platform, query) into a compact cache key."""
        raw = f"{platform}:{query}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, platform: str, query: str) -> Any | None:
        """Return cached value if it exists and is not expired, else ``None``."""
        key = self._make_key(platform, query)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            expires_at, _platform, value = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, platform: str, query: str, value: Any, ttl: int | None = None) -> None:
        """Cache *value* under *(platform, query)*.

        If the cache exceeds *max_size* after insertion the oldest entry
        (by expiry time) is evicted.
        """
        key = self._make_key(platform, query)
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.monotonic() + effective_ttl
        with self._lock:
            self._store[key] = (expires_at, platform, value)
            self._evict_expired()
            # If still over capacity, drop the entry closest to expiry.
            while len(self._store) > self._max_size:
                oldest_key = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest_key]

    def clear(self, platform: str | None = None) -> None:
        """Clear the cache.

        If *platform* is given, only entries for that platform are removed.
        """
        with self._lock:
            if platform is None:
                self._store.clear()
            else:
                keys_to_delete = [k for k, (_, p, _) in self._store.items() if p == platform]
                for k in keys_to_delete:
                    del self._store[k]

    @property
    def stats(self) -> dict[str, int]:
        """Return cache hit / miss statistics."""
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._store),
            }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evict_expired(self) -> None:
        """Remove all entries whose TTL has passed.

        **Must** be called while holding ``self._lock``.
        """
        now = time.monotonic()
        expired_keys = [k for k, (exp, _, _) in self._store.items() if now > exp]
        for k in expired_keys:
            del self._store[k]
