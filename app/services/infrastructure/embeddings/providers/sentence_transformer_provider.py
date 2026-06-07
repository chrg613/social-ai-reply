"""Optional sentence-transformers embedding provider."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SentenceTransformerProvider:
    """Sentence-transformers embedding provider.

    Import is deferred to __init__ so that the app does not crash when
    sentence-transformers is not installed.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(model_name)
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Install it with: pip install sentence-transformers"
            ) from exc

    def embed(self, text: str) -> list[float]:
        """Return embedding vector for a single text."""
        embedding = self.model.encode(text, convert_to_numpy=True, show_progress_bar=False)
        return embedding.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a batch of texts."""
        embeddings = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return embeddings.tolist()
