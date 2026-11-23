"""Core memory lifecycle — save, get, search, update and delete."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.store.base import SearchItem

from recall.config import SearchConfig
from recall.errors import NotFoundError, ValidationError
from recall.models import SearchResult
from recall.storage_adapter import GLOBAL_SENTINEL, StorageAdapter


class MemoryService:
    """Orchestrates memory operations: build value, delegate to storage, direct get-by-id."""

    def __init__(self, storage: StorageAdapter, search_config: SearchConfig | None = None) -> None:
        self._storage = storage
        self._search_config = search_config or SearchConfig()

    async def search(
        self,
        project_id: str,
        query: str,
        scope: str | None = None,
        kind: str | None = None,
        author_user_id: str | None = None,
        limit: int | None = None,
    ) -> list[SearchResult]:
        """Search one explicit scope, or — when ``scope`` is None — project and
        global merged with ADR-0010's additive project boost.

        ``author_user_id`` is the memory's author to filter by — NOT the
        authenticated caller (Story 5.2 AC3). Merged scores are ranking scores
        (project hits ``raw + project_boost``); explicit-scope scores are raw.
        A failure in either merged query propagates — no partial results.
        """
        filt = self._build_filter(kind, author_user_id)
        effective = self._clamp_limit(limit)

        async def one(sc: str, pid: str) -> list[SearchResult]:
            items = await self._storage.search(
                scope=sc, project_id=pid, query=query, filter=filt, limit=effective
            )
            return [self._to_result(item, item.score or 0.0) for item in items]

        if scope is not None:
            return await one(scope, project_id)
        # Plain gather, no return_exceptions: partial results are worse than an error.
        project, glob = await asyncio.gather(
            one("project", project_id), one("global", GLOBAL_SENTINEL)
        )
        return self._merge(project, glob, effective)

    def _merge(
        self, project: list[SearchResult], glob: list[SearchResult], limit: int
    ) -> list[SearchResult]:
        boost = self._search_config.project_boost
        boosted = [r.model_copy(update={"score": r.score + boost}) for r in project]
        # Project-first + stable sort: ties resolve to project, even at boost 0.
        return sorted(boosted + glob, key=lambda r: r.score, reverse=True)[:limit]

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

    async def update(
        self,
        scope: str,
        project_id: str,
        memory_id: str,
        title: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Update supplied fields of an existing memory (read-modify-write).

        ``tags`` and ``metadata`` replace wholesale; ``created_at`` and the
        author ``user_id`` are untouched. Re-embeds only when ``content``
        actually differs from the stored value.

        Raises:
            ValidationError: no fields supplied, or scope invariant violation.
            NotFoundError: memory not found in the given namespace.
        """
        if title is None and content is None and tags is None and metadata is None:
            raise ValidationError(
                "No fields to update: provide at least one of title, content, tags, metadata"
            )
        item = await self._storage.get(scope, project_id, memory_id)
        if item is None:
            raise NotFoundError(memory_id)
        value = self._apply_changes(item.value, title, content, tags, metadata)
        content_changed = content is not None and content != item.value["content"]
        # index=False (not None): None would re-embed on every edit.
        await self._storage.put(
            scope=scope,
            project_id=project_id,
            key=memory_id,
            value=value,
            index=["content"] if content_changed else False,
        )
        return memory_id

    async def delete(self, scope: str, project_id: str, memory_id: str) -> None:
        """Permanently delete a memory (Story 1.5).

        Idempotent: no existence check — an absent id is a no-op, never
        ``NotFoundError`` (a get-then-delete would add a round trip and a race).

        Raises:
            ValidationError: scope invariant violation.
        """
        await self._storage.delete(scope, project_id, memory_id)

    @staticmethod
    def _apply_changes(
        stored: dict[str, Any],
        title: str | None,
        content: str | None,
        tags: list[str] | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        supplied = {"title": title, "content": content, "tags": tags, "metadata": metadata}
        changes = {k: v for k, v in supplied.items() if v is not None}
        return {**stored, **changes, "updated_at": datetime.now(UTC).isoformat()}
