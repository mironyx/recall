"""Unit tests for the deterministic StubEmbeddingsProvider (Issue #77).

Contract sources:
- ``docs/design/lld-e05-test-fixture.md`` (BDD spec, invariants I4, I5)
- ``docs/requirements/v2-requirements.md`` (Story 1.1 — stub embeddings AC)
- ``docs/adr/0008-embeddings-provider-interface.md`` (embed() interface shape)

The stub currently raises ``NotImplementedError``; all tests fail pre-implementation.
"""

from __future__ import annotations

import math

from recall.embeddings.stub import StubEmbeddingsProvider


class TestStubEmbeddingsProvider:
    """Unit tests for the deterministic stub provider (Issue #77)."""

    # ------------------------------------------------------------------
    # Deterministic output — invariant I4
    # ------------------------------------------------------------------

    def test_deterministic_output(self) -> None:
        """Given the same input text, embed() returns an identical vector on
        repeated calls (I4)."""
        provider = StubEmbeddingsProvider()
        texts = ["hello world"]
        first = provider.embed(texts)
        second = provider.embed(texts)
        assert first == second

    def test_deterministic_output_multiple_texts(self) -> None:
        """Given multiple input texts, embed() returns identical results on
        repeated calls."""
        provider = StubEmbeddingsProvider()
        texts = ["alpha", "beta", "gamma"]
        first = provider.embed(texts)
        second = provider.embed(texts)
        assert first == second

    # ------------------------------------------------------------------
    # Correct dimension — invariant I5
    # ------------------------------------------------------------------

    def test_correct_dimension_default(self) -> None:
        """Given the default dim=384, each returned vector has exactly 384
        elements."""
        provider = StubEmbeddingsProvider()
        vectors = provider.embed(["hello"])
        assert len(vectors) == 1
        vec = vectors[0]
        assert len(vec) == 384
        assert all(isinstance(v, float) for v in vec)

    def test_correct_dimension_custom(self) -> None:
        """Given a custom dim=128, each returned vector has exactly 128
        elements."""
        provider = StubEmbeddingsProvider(dim=128)
        vectors = provider.embed(["hello"])
        assert len(vectors) == 1
        vec = vectors[0]
        assert len(vec) == 128

    def test_correct_dimension_all_vectors(self) -> None:
        """Given a batch of N texts, every one of the N vectors has the
        configured dimension."""
        provider = StubEmbeddingsProvider(dim=64)
        vectors = provider.embed(["a", "bb", "ccc", "dddd"])
        assert len(vectors) == 4
        for vec in vectors:
            assert len(vec) == 64

    # ------------------------------------------------------------------
    # Different inputs yield different vectors
    # ------------------------------------------------------------------

    def test_different_inputs_different_vectors(self) -> None:
        """Given two different input texts, the returned vectors are not
        identical."""
        provider = StubEmbeddingsProvider()
        va = provider.embed(["alpha"])
        vb = provider.embed(["beta"])
        assert va[0] != vb[0]

    # ------------------------------------------------------------------
    # Batch input — N texts in, N vectors out
    # ------------------------------------------------------------------

    def test_batch_input_returns_n_vectors(self) -> None:
        """Given a list of N texts, embed() returns a list of exactly N
        vectors."""
        provider = StubEmbeddingsProvider()
        texts = ["one", "two", "three", "four", "five"]
        vectors = provider.embed(texts)
        assert len(vectors) == len(texts)

    def test_empty_input(self) -> None:
        """Given an empty list, embed() returns an empty list."""
        provider = StubEmbeddingsProvider()
        vectors = provider.embed([])
        assert vectors == []

    # ------------------------------------------------------------------
    # L2 normalisation — each vector has unit norm
    # ------------------------------------------------------------------

    @staticmethod
    def _l2_norm(vec: list[float]) -> float:
        return math.sqrt(sum(x * x for x in vec))

    def test_normalised_vectors(self) -> None:
        """Given any input text, the returned vector has unit L2 norm
        (within floating-point tolerance)."""
        provider = StubEmbeddingsProvider()
        vectors = provider.embed(["some text"])
        norm = self._l2_norm(vectors[0])
        assert math.isclose(norm, 1.0, abs_tol=1e-6)

    def test_normalised_vectors_multiple(self) -> None:
        """Given multiple input texts, every returned vector has unit L2
        norm."""
        provider = StubEmbeddingsProvider()
        texts = ["foo", "bar", "baz", "qux"]
        vectors = provider.embed(texts)
        for vec in vectors:
            norm = self._l2_norm(vec)
            assert math.isclose(norm, 1.0, abs_tol=1e-6)

    def test_normalised_vectors_custom_dim(self) -> None:
        """Given a custom dimension, returned vectors still have unit L2
        norm."""
        provider = StubEmbeddingsProvider(dim=256)
        vectors = provider.embed(["test"])
        norm = self._l2_norm(vectors[0])
        assert math.isclose(norm, 1.0, abs_tol=1e-6)

    # ------------------------------------------------------------------
    # dim attribute — public interface
    # ------------------------------------------------------------------

    def test_dim_attribute(self) -> None:
        """The dim attribute is readable after construction and matches the
        configured value."""
        provider = StubEmbeddingsProvider(dim=512)
        assert provider.dim == 512

    def test_default_dim(self) -> None:
        """Given no dim argument, the default dim is 384."""
        provider = StubEmbeddingsProvider()
        assert provider.dim == 384
