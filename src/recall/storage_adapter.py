"""Thin wrapper over AsyncPostgresStore (ADR-0001, ADR-0002)."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.store.base import Item, SearchItem
from langgraph.store.postgres import AsyncPostgresStore

from recall.errors import ValidationError

GLOBAL_SENTINEL = "_"

# ADR-0004: the only caller-supplied filter keys search accepts.
_ALLOWED_FILTER_KEYS = frozenset({"kind", "user_id"})


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

    async def search(
        self,
        scope: str,
        project_id: str,
        query: str,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[SearchItem]:
        """Semantic search within exactly one (scope, project_id) namespace.

        Scores are the store's cosine similarity, returned untouched.

        Raises:
            ValidationError: on a scope/project_id invariant violation or a
                filter key outside {kind, user_id} (ADR-0004).
        """
        namespace = self._build_namespace(scope, project_id)
        self._validate_filter_keys(filter)
        return await self._store.asearch(
            namespace,
            query=query,
            filter=self._scoping_filter(scope, project_id, filter),
            limit=limit,
        )

    @staticmethod
    def _validate_filter_keys(filter: dict[str, Any] | None) -> None:
        """Reject caller filter keys outside {kind, user_id} (ADR-0004)."""
        for key in filter or {}:
            if key not in _ALLOWED_FILTER_KEYS:
                raise ValidationError(
                    f"Unsupported filter key: {key!r}; allowed: {sorted(_ALLOWED_FILTER_KEYS)}"
                )

    @staticmethod
    def _scoping_filter(
        scope: str,
        project_id: str,
        filter: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Merge exact ``scope``/``project_id`` clauses over the caller filter.

        asearch scopes by namespace *prefix* (SQL LIKE), so 'app' would also match
        'app-v2'. These top-level $eq clauses make the scoping exact. Added last
        so the caller cannot override them. Do not remove.
        """
        return {**(filter or {}), "scope": scope, "project_id": project_id}

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
