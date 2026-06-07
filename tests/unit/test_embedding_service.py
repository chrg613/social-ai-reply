"""Tests for the embedding service facade."""

import pytest

from app.services.infrastructure.embeddings.providers.tfidf_provider import TfidfProvider
from app.services.infrastructure.embeddings.service import EmbeddingService


@pytest.fixture(autouse=True)
def reset_embedding_singleton():
    """Reset the EmbeddingService singleton so tests don't share fitted state."""
    EmbeddingService._instance = None
    yield
    EmbeddingService._instance = None


class TestTfidfProvider:
    def test_similar_related_texts(self):
        """TF-IDF similarity for related texts should be > 0.3."""
        provider = TfidfProvider()
        text_a = "email automation sequences for sales teams to improve follow up"
        text_b = "sales teams use email automation for follow up sequences"
        emb_a = provider.embed(text_a)
        emb_b = provider.embed(text_b)
        sim = EmbeddingService.cosine_similarity(emb_a, emb_b)
        assert sim > 0.3

    def test_similar_unrelated_texts(self):
        """TF-IDF similarity for unrelated texts should be < 0.1."""
        provider = TfidfProvider()
        text_a = "best mechanical keyboard for programming under 100 dollars"
        text_b = "email automation tool for sales teams to improve follow up"
        emb_a = provider.embed(text_a)
        emb_b = provider.embed(text_b)
        sim = EmbeddingService.cosine_similarity(emb_a, emb_b)
        assert sim < 0.1

    def test_batch_embedding(self):
        provider = TfidfProvider()
        texts = [
            "email automation for sales",
            "sales team email sequences",
            "best programming keyboard",
        ]
        embeddings = provider.embed_batch(texts)
        assert len(embeddings) == 3
        for emb in embeddings:
            assert len(emb) > 0
            assert all(isinstance(v, float) for v in emb)

    def test_identical_texts_similarity_one(self):
        provider = TfidfProvider()
        text = "email automation tool for sales teams"
        emb_a = provider.embed(text)
        emb_b = provider.embed(text)
        sim = EmbeddingService.cosine_similarity(emb_a, emb_b)
        assert sim == pytest.approx(1.0, abs=1e-9)

    def test_empty_text_returns_zero_embedding(self):
        provider = TfidfProvider()
        provider.fit(["some placeholder text to initialize vocabulary"])
        emb = provider.embed("")
        # Empty text should produce a zero vector after fitting
        assert len(emb) > 0
        assert all(v == 0.0 for v in emb)


class TestEmbeddingService:
    def test_related_texts_similarity(self):
        service = EmbeddingService(model_name="tfidf")
        text_a = "email automation sequences for sales teams to improve follow up"
        text_b = "sales teams use email automation for follow up sequences"
        sim = service.similarity(text_a, text_b)
        assert sim > 0.3

    def test_unrelated_texts_similarity(self):
        service = EmbeddingService(model_name="tfidf")
        text_a = "best mechanical keyboard for programming under 100 dollars"
        text_b = "email automation tool for sales teams to improve follow up"
        sim = service.similarity(text_a, text_b)
        assert sim < 0.1

    def test_batch_embedding(self):
        service = EmbeddingService(model_name="tfidf")
        texts = [
            "email automation for sales",
            "sales team email sequences",
            "best programming keyboard",
        ]
        embeddings = service.embed_batch(texts)
        assert len(embeddings) == 3
        for emb in embeddings:
            assert len(emb) > 0

    def test_caching_same_text(self):
        service = EmbeddingService(model_name="tfidf")
        text = "email automation tool for sales teams"
        emb_a = service.embed_text(text)
        emb_b = service.embed_text(text)
        assert emb_a == emb_b
        # Under the hood, the second call should hit the cache
        assert service._cache  # cache should not be empty after first call

    def test_cosine_similarity_computation(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert EmbeddingService.cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-9)

        c = [1.0, 1.0, 0.0]
        d = [1.0, 1.0, 0.0]
        assert EmbeddingService.cosine_similarity(c, d) == pytest.approx(1.0, abs=1e-9)

        e = [1.0, 2.0, 3.0]
        f = [4.0, 5.0, 6.0]
        sim = EmbeddingService.cosine_similarity(e, f)
        assert 0.0 < sim < 1.0

    def test_cosine_similarity_zero_vector(self):
        assert EmbeddingService.cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
        assert EmbeddingService.cosine_similarity([1.0, 1.0], [0.0, 0.0]) == 0.0

    def test_provider_fitted_on_demand(self):
        service = EmbeddingService(model_name="tfidf")
        # First call should trigger fit
        emb = service.embed_text("some text here")
        assert len(emb) > 0

    def test_embedding_dimensions_consistent(self):
        service = EmbeddingService(model_name="tfidf")
        texts = ["short", "a longer piece of text about email automation", "another one"]
        embeddings = service.embed_batch(texts)
        dims = [len(emb) for emb in embeddings]
        assert len(set(dims)) == 1
