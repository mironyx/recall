"""Adversarial evaluation tests for Issue #88 — E1.3: Embedder interface + stub upgrade.

Probes one gap left by tests/test_embeddings.py and tests/test_stub_embeddings.py:

- Determinism is tested only within a single provider instance. The acceptance
  criterion "Stub produces deterministic vectors (same input → same vector)"
  is instance-agnostic, and the stub's real usage is instance-per-construction:
  tests/conftest.py builds a fresh ``StubEmbeddingsProvider()`` for every store
  (PostgresIndexConfig embed callable). If embed ever depended on instance-local
  state (e.g., a random seed), every existing determinism test would still pass
  while cross-run reproducibility — the entire point of a deterministic test
  provider per ADR-0008 — silently breaks.

Imports reuse the production classes directly (as the sibling unit tests do);
no mocks, no DB.
"""

from __future__ import annotations

from recall.embeddings.stub import StubEmbeddingsProvider


class TestCrossInstanceDeterminism:
    """AC-3 strengthened: same input → same vector across provider instances."""

    def test_same_input_same_vector_across_instances(self) -> None:
        """Given two separately constructed default-dim stub providers, when
        the same text is embedded, then identical vectors are returned."""
        a = StubEmbeddingsProvider()
        b = StubEmbeddingsProvider()
        assert a.embed(["hello world"]) == b.embed(["hello world"])

    def test_same_input_same_vector_across_instances_custom_dim(self) -> None:
        """Given two separately constructed custom-dim stub providers, when
        the same text is embedded, then identical vectors are returned."""
        a = StubEmbeddingsProvider(dim=128)
        b = StubEmbeddingsProvider(dim=128)
        assert a.embed(["hello world"]) == b.embed(["hello world"])

    def test_cross_instance_vectors_match_own_dim(self) -> None:
        """Given a vector from instance A, its dimension equals the configured
        dim on instance B — the two instances agree on the contract."""
        a = StubEmbeddingsProvider(dim=256)
        b = StubEmbeddingsProvider(dim=256)
        assert len(b.embed(["x"])[0]) == a.dim == 256
