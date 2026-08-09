"""Core memory lifecycle — save and get (Phase 1). Search/update/delete in later phases."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from recall.errors import NotFoundError
from recall.storage_adapter import StorageAdapter


class MemoryService:
    """Orchestrates memory operations: build value, delegate to storage, resolve get-by-id."""

    def __init__(self, storage: StorageAdapter) -> None:
        self._storage = storage

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
        4. Write the reverse index entry (id → namespace) for get_by_id.

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

        # Memory first, index second: if embedding fails or the invariant is
        # violated, nothing is persisted at all (Story 1.3 AC4).
        await self._storage.put(
            scope=scope,
            project_id=project_id,
            key=memory_id,
            value=value,
            index=["content"],  # embed the content field
        )

        # TODO(#90): save() is two non-atomic writes — if the index write
        # fails after the memory write, the memory stays searchable but
        # get_by_id raises NotFoundError. AsyncPostgresStore exposes no
        # multi-write transaction; revisit if orphaned memories surface.
        # Reverse index: ("_index", "_") is outside the adapter's (scope,
        # project_id) domain, so it goes to the wrapped raw store directly.
        await self._storage._store.aput(
            ("_index", "_"),
            memory_id,
            {"scope": scope, "project_id": project_id},
            index=False,
        )

        return memory_id

    async def get_by_id(self, memory_id: str) -> dict[str, Any]:
        """Retrieve a memory by ID.

        Uses a reverse index stored in namespace ("_index", "_"): on save,
        an index entry mapping memory_id → (scope, project_id) is also
        persisted. On get_by_id, the index is consulted first to find
        the correct namespace, then the actual record is fetched.

        Returns:
            The full record dict — the flat value plus the memory id — which
            satisfies the MemoryResponse shape (Story 2.4 AC1).

        Raises:
            NotFoundError: memory not found.
        """
        entry = await self._storage._store.aget(("_index", "_"), memory_id)
        if entry is None:
            raise NotFoundError(memory_id)
        scope: str = entry.value["scope"]
        project_id: str = entry.value["project_id"]

        item = await self._storage.get(scope, project_id, memory_id)
        if item is None:
            raise NotFoundError(memory_id)

        return {"id": memory_id, **item.value}
