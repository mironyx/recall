"""Thin wrapper over AsyncPostgresStore (ADR-0001, ADR-0002)."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.store.base import Item
from langgraph.store.postgres import AsyncPostgresStore

from recall.errors import ValidationError

GLOBAL_SENTINEL = "_"


class StorageAdapter:
    """Namespace-aware wrapper over AsyncPostgresStore.

    Enforces the (scope, project_id) namespace shape (ADR-0002)
    and the scope invariant as defence-in-depth.
    """

    def __init__(self, store: AsyncPostgresStore) -> None:
        self._store = store

    async def put(
        self,
        scope: str,
        project_id: str,
        key: str,
        value: dict[str, Any],
        index: list[str] | Literal[False] | None = None,
    ) -> None:
        """Store a memory record.

        Args:
            scope: "project" or "global".
            project_id: The project ID, or GLOBAL_SENTINEL for global scope.
            key: The memory ID (UUID).
            value: Flat value dict (ADR-0001).
            index: Fields to embed, or False to skip embedding.

        Raises:
            ValidationError: if scope/project_id invariant is violated.
        """
        namespace = self._build_namespace(scope, project_id)
        await self._store.aput(namespace, key, value, index=index)

    async def get(
        self,
        scope: str,
        project_id: str,
        key: str,
    ) -> Item | None:
        """Retrieve a memory by namespace + key.

        Returns None if not found.
        """
        namespace = self._build_namespace(scope, project_id)
        return await self._store.aget(namespace, key)

    @staticmethod
    def _build_namespace(scope: str, project_id: str) -> tuple[str, str]:
        """Construct the 2-tuple namespace, enforcing the scope invariant.

        Raises:
            ValidationError: if scope=global and project_id != '_',
                or scope=project and project_id == '_'.
        """
        if scope == "global" and project_id != GLOBAL_SENTINEL:
            raise ValidationError("Global scope requires project_id='_'")
        if scope == "project" and project_id == GLOBAL_SENTINEL:
            raise ValidationError("Project scope must not use the reserved sentinel '_'")
        if scope not in ("global", "project"):
            raise ValidationError(f"Invalid scope: {scope}")
        return (scope, project_id)
