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


# Called at store creation with the dim from RECALL_EMBEDDING_DIMS, before
# PostgresIndexConfig is built (E1.6, issue #91 — see server._build_store).
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
