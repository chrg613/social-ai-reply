"""Embedding service facade - unified entry point for text embeddings."""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import TYPE_CHECKING

import numpy as np

from app.services.infrastructure.embeddings.providers.tfidf_provider import TfidfProvider

if TYPE_CHECKING:
    from app.services.infrastructure.embeddings.providers.sentence_transformer_provider import (
        SentenceTransformerProvider,
    )

logger = logging.getLogger(__name__)

_DEFAULT_MAX_CACHE_SIZE = 1000


def _normalize_text(text: str) -> str:
    """Normalize text for stable hashing."""
    return " ".join(text.lower().split())


def _text_hash(text: str) -> str:
    """Return a stable hash for the normalized text."""
    return hashlib.md5(_normalize_text(text).encode("utf-8"), usedforsecurity=False).hexdigest()


class EmbeddingService:
    """Singleton-like facade for text embedding and similarity.

    Supports TF-IDF (default) and optional sentence-transformers backends.
    Thread-safe via locks when fitting TF-IDF vectorizer on demand.
    """

    _instance: EmbeddingService | None = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls, model_name: str = "tfidf", max_cache_size: int = _DEFAULT_MAX_CACHE_SIZE) -> EmbeddingService:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, model_name: str = "tfidf", max_cache_size: int = _DEFAULT_MAX_CACHE_SIZE) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._model_name = model_name
            self._max_cache_size = max_cache_size
            self._cache: dict[str, list[float]] = {}
            self._cache_lock = threading.Lock()
            self._provider = self._create_provider()
            self._initialized = True

    def _create_provider(self) -> TfidfProvider | SentenceTransformerProvider:
        name = self._model_name
        if name == "sentence-transformers":
            try:
                from app.services.infrastructure.embeddings.providers.sentence_transformer_provider import (
                    SentenceTransformerProvider,
                )

                logger.info("Using sentence-transformers embedding provider.")
                return SentenceTransformerProvider()
            except Exception as exc:
                logger.warning(
                    "sentence-transformers provider failed to load (%s). Falling back to TF-IDF.",
                    exc,
                )
                return TfidfProvider()
        return TfidfProvider()

    def _get_cached(self, text: str) -> list[float] | None:
        key = _text_hash(text)
        with self._cache_lock:
            return self._cache.get(key)

    def _set_cached(self, text: str, embedding: list[float]) -> None:
        key = _text_hash(text)
        with self._cache_lock:
            if len(self._cache) >= self._max_cache_size:
                # Simple LRU eviction: remove an arbitrary oldest key
                # Python 3.7+ dict preserves insertion order
                self._cache.pop(next(iter(self._cache)), None)
            self._cache[key] = embedding

    def embed_text(self, text: str) -> list[float]:
        """Return embedding vector for a single text (with caching)."""
        cached = self._get_cached(text)
        if cached is not None:
            return cached

        embedding = self._provider.embed(text)
        self._set_cached(text, embedding)
        return embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a batch of texts (with caching)."""
        results: list[list[float]] = []
        uncached_texts: list[str] = []
        uncached_indices: list[int] = []

        for idx, text in enumerate(texts):
            cached = self._get_cached(text)
            if cached is not None:
                results.append(cached)
            else:
                results.append([])
                uncached_texts.append(text)
                uncached_indices.append(idx)

        if uncached_texts:
            embeddings = self._provider.embed_batch(uncached_texts)
            for idx, text, emb in zip(uncached_indices, uncached_texts, embeddings, strict=False):
                self._set_cached(text, emb)
                results[idx] = emb

        return results

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        arr_a = np.array(a, dtype=np.float64)
        arr_b = np.array(b, dtype=np.float64)
        norm_a = np.linalg.norm(arr_a)
        norm_b = np.linalg.norm(arr_b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(arr_a, arr_b) / (norm_a * norm_b))

    def similarity(self, text_a: str, text_b: str) -> float:
        """Convenience: embed both texts and compute cosine similarity."""
        emb_a = self.embed_text(text_a)
        emb_b = self.embed_text(text_b)
        return self.cosine_similarity(emb_a, emb_b)
