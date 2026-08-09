"""Embeddings provider interface (ADR-0008)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingsProvider(ABC):
    """Abstract base for embedding providers.

    All providers must declare their vector dimension and implement
    batch embedding.
    """

    @property
    @abstractmethod
    def dim(self) -> int:
        """The dimensionality of produced vectors."""
        ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Args:
            texts: Non-empty list of strings to embed.

        Returns:
            One vector per input text, each of length self.dim.
        """
        ...


# TODO(#91): call validate_dim at store creation with EMBEDDINGS_DIM from
# env, before PostgresIndexConfig is built. Deferred from E1.4 (#89) — the
# storage adapter wraps an injected store and has no creation call site;
# store creation lives at the composition root (E1.6, issue #91).
# Justification: LLD BDD spec test_dim_mismatch_fails_fast (§LLD-e1-embedder)
# requires the fail-fast check but names no mechanism; this pure function is
# that mechanism. Not in the LLD's decomposition table — lld-sync will add it.
def validate_dim(provider: EmbeddingsProvider, configured_dim: int) -> None:
    """Fail-fast check that the configured dim matches the provider's dim.

    Called at startup wiring; a mismatch raises before any memory operation.

    Raises:
        ValueError: if ``configured_dim`` != ``provider.dim``.
    """
    if provider.dim != configured_dim:
        raise ValueError(
            f"EMBEDDINGS_DIM={configured_dim} does not match "
            f"{type(provider).__name__}.dim={provider.dim}"
        )
