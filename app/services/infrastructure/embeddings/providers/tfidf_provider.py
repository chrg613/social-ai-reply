"""TF-IDF embedding provider using scikit-learn."""

from __future__ import annotations

import logging
import re
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer

logger = logging.getLogger(__name__)


def _preprocess(text: str) -> str:
    """Lowercase, remove extra whitespace, keep only alphanumeric and spaces."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class TfidfProvider:
    """TF-IDF embedding provider backed by scikit-learn TfidfVectorizer."""

    def __init__(
        self,
        max_features: int = 5000,
        stop_words: str = "english",
        ngram_range: tuple[int, int] = (1, 2),
    ) -> None:
        self.vectorizer = TfidfVectorizer(
            max_features=max_features,
            stop_words=stop_words,
            ngram_range=ngram_range,
            min_df=1,
            max_df=0.95,
        )
        self._fitted: bool = False

    def fit(self, corpus: list[str]) -> None:
        """Fit the vectorizer on a corpus."""
        processed = [_preprocess(t) for t in corpus]
        if not any(processed):
            logger.warning("TF-IDF fit called with empty/whitespace-only corpus.")
            return
        n_docs = len(processed)
        effective_max_df = self.vectorizer.max_df
        if isinstance(effective_max_df, float) and n_docs * effective_max_df < self.vectorizer.min_df:
            # Adjust max_df so that it doesn't exclude all terms on tiny corpora
            effective_max_df = 1.0
            self.vectorizer.set_params(max_df=effective_max_df)
        self.vectorizer.fit(processed)
        self._fitted = True

    def transform(self, texts: list[str]) -> Any:
        """Transform texts into TF-IDF vectors."""
        processed = [_preprocess(t) for t in texts]
        if not self._fitted:
            self.fit(processed)
        return self.vectorizer.transform(processed)

    def embed(self, text: str) -> list[float]:
        """Return dense embedding vector for a single text."""
        vec = self.transform([text])
        return vec.toarray()[0].tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return dense embedding vectors for a batch of texts."""
        vec = self.transform(texts)
        return vec.toarray().tolist()
