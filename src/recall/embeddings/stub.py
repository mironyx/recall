"""Deterministic stub embeddings provider for tests and local dev."""

from __future__ import annotations

import hashlib
import math
import struct

from recall.embeddings.provider import EmbeddingsProvider


class StubEmbeddingsProvider(EmbeddingsProvider):
    """Produces deterministic vectors from input text via hashing.

    Implements the EmbeddingsProvider interface (ADR-0008):
        dim: int
        embed(texts: list[str]) -> list[list[float]]
    """

    def __init__(self, dim: int = 384) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        """The dimensionality of produced vectors."""
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text. Deterministic and normalised."""
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        """Generate a deterministic normalised vector for ``text``."""
        digest = hashlib.sha256(text.encode()).digest()
        bytes_needed = self.dim * 4
        raw = bytearray(digest)
        counter = 0
        while len(raw) < bytes_needed:
            counter += 1
            raw.extend(hashlib.sha256(digest + counter.to_bytes(4)).digest())
        # Unpack as unsigned 32-bit ints to avoid NaN/inf bit patterns from
        # raw-hash → float reinterpretation.
        ints = struct.unpack(f"{self.dim}I", bytes(raw[:bytes_needed]))
        floats = [((i / 0xFFFFFFFF) * 2.0) - 1.0 for i in ints]
        # L2-normalise
        norm = math.sqrt(sum(f * f for f in floats))
        return [f / norm for f in floats]
