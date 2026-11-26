"""Embeddings provider interface (ADR-0008)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence

import structlog

from recall.errors import EmbeddingError

log = structlog.get_logger()


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


# Called at store creation with the dim from EMBEDDINGS_DIM, before
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


def guarded_embed(provider: EmbeddingsProvider) -> Callable[[Sequence[str]], list[list[float]]]:
    """Return the embed function for ``PostgresIndexConfig``: any provider exception is
    logged with its cause and re-raised as ``EmbeddingError`` (LLD §3.4)."""

    def embed(texts: Sequence[str]) -> list[list[float]]:
        try:
            return provider.embed(list(texts))
        except Exception as exc:
            log.exception("embedding_provider_failed", provider=type(provider).__name__)
            raise EmbeddingError() from exc

    return embed
