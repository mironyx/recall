"""Unit tests for the embeddings provider interface and stub upgrade (Issue #88).

Contract sources:
- ``docs/design/v2/lld-e1-one-memory-e2e.md`` (E1.3 — TestEmbedderInterface BDD spec)
- ``docs/requirements/v2-requirements.md`` (Story 1.3 — embedding on save;
  Story 6.4 — EMBEDDINGS_DIM fail-fast check)
- Issue #88 acceptance criteria

Design notes:
- ``embed`` is synchronous. The LLD's ``async def embed`` sketch is a known
  design deviation, resolved to sync: AsyncPostgresStore (the only v1 consumer)
  invokes the embed callable synchronously inside a thread-pool executor, so an
  async-only callable raises at runtime.
- ``validate_dim`` is the startup fail-fast check for EMBEDDINGS_DIM; a mismatch
  raises ValueError.
"""

from __future__ import annotations

import inspect

import pytest

from recall.embeddings.provider import EmbeddingsProvider, validate_dim
from recall.embeddings.stub import StubEmbeddingsProvider


class TestEmbedderInterface:
    """LLD BDD spec (E1.3) — interface + stub + fail-fast dim check."""

    def test_stub_deterministic(self) -> None:
        """Given the same input text, when embed() is called repeatedly, then
        identical vectors are returned."""
        provider = StubEmbeddingsProvider()
        texts = ["hello world"]
        first = provider.embed(texts)
        second = provider.embed(texts)
        assert first == second

    def test_stub_correct_dim(self) -> None:
        """Given the default stub (dim=384), when embed() is called, then each
        returned vector has exactly 384 elements."""
        provider = StubEmbeddingsProvider()
        vectors = provider.embed(["hello"])
        assert len(vectors) == 1
        assert len(vectors[0]) == 384

    def test_dim_mismatch_fails_fast(self) -> None:
        """Given EMBEDDINGS_DIM != provider.dim, when validate_dim runs at
        startup, then ValueError is raised (fail-fast)."""
        provider = StubEmbeddingsProvider()
        with pytest.raises(ValueError):
            validate_dim(provider, provider.dim + 1)


class TestEmbeddingsProviderInterface:
    """Unit tests for the EmbeddingsProvider ABC (Issue #88)."""

    def test_abc_cannot_be_instantiated(self) -> None:
        """Given the abstract EmbeddingsProvider, instantiating it directly
        raises TypeError (dim and embed are abstract)."""
        with pytest.raises(TypeError):
            EmbeddingsProvider()  # type: ignore[abstract]

    def test_dim_and_embed_are_abstract(self) -> None:
        """Given the ABC, both dim and embed are declared abstract so every
        subclass must implement them."""
        assert "dim" in EmbeddingsProvider.__abstractmethods__
        assert "embed" in EmbeddingsProvider.__abstractmethods__


class TestStubEmbeddingsProvider:
    """Unit tests for the stub's contract as an EmbeddingsProvider (Issue #88)."""

    def test_stub_is_embeddings_provider_subclass(self) -> None:
        """Given StubEmbeddingsProvider, it satisfies EmbeddingsProvider by
        subclass and instance (issubclass / isinstance)."""
        assert issubclass(StubEmbeddingsProvider, EmbeddingsProvider)
        assert isinstance(StubEmbeddingsProvider(), EmbeddingsProvider)

    def test_custom_dim_honored(self) -> None:
        """Given a custom dim=128, embed() returns vectors of length 128 and
        the dim attribute reflects the configured value."""
        provider = StubEmbeddingsProvider(dim=128)
        vectors = provider.embed(["text"])
        assert provider.dim == 128
        assert len(vectors) == 1
        assert len(vectors[0]) == 128

    def test_batch_one_vector_per_text(self) -> None:
        """Given N input texts, embed() returns exactly N vectors, one per
        input text."""
        provider = StubEmbeddingsProvider()
        texts = ["one", "two", "three", "four", "five"]
        vectors = provider.embed(texts)
        assert len(vectors) == len(texts)

    def test_empty_input_returns_empty_list(self) -> None:
        """Given an empty text list, embed() returns an empty list."""
        provider = StubEmbeddingsProvider()
        assert provider.embed([]) == []

    def test_embed_is_synchronous(self) -> None:
        """Given the resolved sync embed() contract, embed() returns a list of
        vectors directly — not a coroutine."""
        provider = StubEmbeddingsProvider()
        result = provider.embed(["text"])
        assert isinstance(result, list)
        assert all(isinstance(v, list) for v in result)
        assert not inspect.iscoroutinefunction(StubEmbeddingsProvider.embed)


class TestValidateDim:
    """Unit tests for the startup fail-fast dim check (Issue #88)."""

    def test_dim_match_returns_none(self) -> None:
        """Given EMBEDDINGS_DIM == provider.dim, when validate_dim is called,
        then it completes without raising (no-op)."""
        provider = StubEmbeddingsProvider()
        validate_dim(provider, provider.dim)

    @pytest.mark.parametrize("configured_dim", [0, 383, 385, 512])
    def test_dim_mismatch_raises_value_error(self, configured_dim: int) -> None:
        """Given EMBEDDINGS_DIM differing from the provider dim of 384
        (boundary values included), when validate_dim is called, then ValueError
        is raised."""
        provider = StubEmbeddingsProvider()
        with pytest.raises(ValueError):
            validate_dim(provider, configured_dim)

    def test_custom_dim_provider_match_returns_none(self) -> None:
        """Given a stub with custom dim where EMBEDDINGS_DIM == provider.dim,
        when validate_dim is called, then it completes without raising — the
        check accepts any EmbeddingsProvider subclass."""
        provider = StubEmbeddingsProvider(dim=256)
        validate_dim(provider, 256)

    def test_custom_dim_provider_mismatch_raises(self) -> None:
        """Given a stub with custom dim where EMBEDDINGS_DIM != provider.dim,
        when validate_dim is called, then ValueError is raised."""
        provider = StubEmbeddingsProvider(dim=256)
        with pytest.raises(ValueError):
            validate_dim(provider, 384)
