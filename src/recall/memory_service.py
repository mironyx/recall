"""Core memory lifecycle — save and get (Phase 1). Search/update/delete in later phases."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.store.base import SearchItem

from recall.config import SearchConfig
from recall.errors import NotFoundError
from recall.models import SearchResult
from recall.storage_adapter import StorageAdapter


class MemoryService:
    """Orchestrates memory operations: build value, delegate to storage, direct get-by-id."""

    def __init__(self, storage: StorageAdapter, search_config: SearchConfig | None = None) -> None:
        self._storage = storage
        self._search_config = search_config or SearchConfig()

    async def search(
        self,
        project_id: str,
        query: str,
        scope: str,
        kind: str | None = None,
        author_user_id: str | None = None,
        limit: int | None = None,
    ) -> list[SearchResult]:
        """Search one explicit scope. ``author_user_id`` is the memory's author to
        filter by — NOT the authenticated caller (Story 5.2 AC3)."""
        items = await self._storage.search(
            scope=scope,
            project_id=project_id,
            query=query,
            filter=self._build_filter(kind, author_user_id),
            limit=self._clamp_limit(limit),
        )
        return [self._to_result(item, item.score or 0.0) for item in items]

    def _clamp_limit(self, limit: int | None) -> int:
        cfg = self._search_config
        return max(1, min(cfg.default_limit if limit is None else limit, cfg.max_limit))

    @staticmethod
    def _build_filter(kind: str | None, author_user_id: str | None) -> dict[str, str] | None:
        # The stored `user_id` is the author; the filter key is storage-level.
        filt = {}
        if kind is not None:
            filt["kind"] = kind
        if author_user_id is not None:
            filt["user_id"] = author_user_id
        return filt or None

    def _to_result(self, item: SearchItem, score: float) -> SearchResult:
        v = item.value
        return SearchResult(
            id=item.key,
            scope=v["scope"],
            project_id=v["project_id"],
            kind=v["kind"],
            title=v["title"],
            snippet=self._snippet(v["content"]),
            score=score,
        )

    def _snippet(self, content: str) -> str:
        return content[: self._search_config.snippet_max_chars]

    async def save(
        self,
        scope: str,
        project_id: str,
        user_id: str,
        kind: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Save a new memory.

        1. Enforce scope invariant (StorageAdapter validates before any write).
        2. Build the flat value dict (ADR-0001).
        3. Delegate to StorageAdapter — AsyncPostgresStore handles embedding
           internally via PostgresIndexConfig when index=["content"] is passed.
        4. Return the generated ID.

        Args:
            scope: "project" or "global".
            project_id: Project ID or "_" for global.
            user_id: Resolved from auth.
            kind: Free-form category (decision, convention, gotcha, etc.).
            title: Short title for the memory.
            content: Full content text.
            tags: Optional list of tag strings.
            metadata: Optional additional metadata dict.

        Returns:
            The generated memory ID (UUID string).

        Raises:
            ValidationError: scope invariant violation.
            EmbeddingError: embedding generation failed.
        """
        memory_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()

        value: dict[str, Any] = {
            "scope": scope,
            "project_id": project_id,
            "user_id": user_id,
            "kind": kind,
            "title": title,
            "content": content,
            "tags": tags or [],
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }

        # Single write: if embedding fails or the invariant is violated,
        # nothing is persisted at all (Story 1.3 AC4).
        await self._storage.put(
            scope=scope,
            project_id=project_id,
            key=memory_id,
            value=value,
            index=["content"],  # embed the content field
        )

        return memory_id

    async def get_by_id(self, scope: str, project_id: str, memory_id: str) -> dict[str, Any]:
        """Retrieve a memory by ID within its known namespace.

        The (scope, project_id) namespace is provided by the caller
        (ADR-0015) — search results carry it, and id-only resolution is
        intentionally unsupported. get is a direct namespaced read.

        Returns:
            The full record dict — the flat value plus the memory id — which
            satisfies the MemoryResponse shape (Story 2.4 AC1).

        Raises:
            NotFoundError: memory not found.
        """
        item = await self._storage.get(scope, project_id, memory_id)
        if item is None:
            raise NotFoundError(memory_id)

        return {"id": memory_id, **item.value}
