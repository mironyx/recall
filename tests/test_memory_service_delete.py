"""Integration tests for MemoryService.delete — REC-11 (E3.2).

Contract: ``docs/design/v2/lld-e3-update-delete-errors.md`` §3.3 (anchor
``LLD-e3-delete``); Story 1.5. Split from ``test_memory_service.py`` to keep that
module under CodeScene's function-count threshold; helpers are reused from it.
Real Postgres via the session-scoped ``store`` fixture (ADR-0012).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

from recall.errors import NotFoundError, ValidationError
from recall.memory_service import MemoryService
from recall.storage_adapter import GLOBAL_SENTINEL, StorageAdapter
from tests.conftest import _CountingStore
from tests.test_memory_service import _PROJECT, _save, _save_args, _vector_row_count

if TYPE_CHECKING:
    from langgraph.store.postgres import AsyncPostgresStore


@pytest_asyncio.fixture
async def service(store: AsyncPostgresStore) -> MemoryService:
    """MemoryService over the session-scoped store fixture."""
    return MemoryService(StorageAdapter(store))


@pytest.mark.integration
class TestMemoryServiceDelete:
    """REC-11 — permanent, idempotent delete; no existence check; namespace-exact."""

    async def test_deleted_memory_absent_from_get_and_search(self, service: MemoryService) -> None:
        """REC-11 invariant 1 — get raises not_found; search never returns the id."""
        text = "a memory that will be deleted"
        mid = await _save(service, content=text)

        await service.delete("project", _PROJECT, mid)

        with pytest.raises(NotFoundError):
            await service.get_by_id("project", _PROJECT, mid)
        assert mid not in [r.id for r in await service.search(_PROJECT, text)]
        assert mid not in [r.id for r in await service.search(_PROJECT, text, scope="project")]

    async def test_deleted_global_memory_absent(self, service: MemoryService) -> None:
        """REC-11 — global memories are deleted under the '_' sentinel."""
        text = "global memory to delete"
        mid = await _save(service, scope="global", content=text)

        await service.delete("global", GLOBAL_SENTINEL, mid)

        with pytest.raises(NotFoundError):
            await service.get_by_id("global", GLOBAL_SENTINEL, mid)
        assert mid not in [r.id for r in await service.search(_PROJECT, text)]

    async def test_delete_removes_embedding_row(
        self, service: MemoryService, pg_conn_string: str
    ) -> None:
        """REC-11 invariant 2 — no store_vectors row remains (real connection count)."""
        mid = await _save(service)
        assert await _vector_row_count(pg_conn_string, mid, f"project.{_PROJECT}") == 1

        await service.delete("project", _PROJECT, mid)

        assert await _vector_row_count(pg_conn_string, mid, f"project.{_PROJECT}") == 0

    async def test_delete_is_idempotent(self, service: MemoryService) -> None:
        """REC-11 invariant 3 — an absent id deletes OK, twice in a row."""
        mid = str(uuid.uuid4())

        await service.delete("project", _PROJECT, mid)
        await service.delete("project", _PROJECT, mid)

    async def test_delete_wrong_namespace_leaves_memory(self, service: MemoryService) -> None:
        """REC-11 invariant 4 — deleting from another namespace leaves the memory."""
        mid = await _save(service)

        await service.delete("project", "other-proj", mid)
        await service.delete("global", GLOBAL_SENTINEL, mid)

        assert (await service.get_by_id("project", _PROJECT, mid))["id"] == mid

    @pytest.mark.parametrize(
        ("scope", "project_id"),
        [("global", _PROJECT), ("project", GLOBAL_SENTINEL), ("bogus", _PROJECT)],
    )
    async def test_delete_scope_invariant_enforced(
        self, store: AsyncPostgresStore, scope: str, project_id: str
    ) -> None:
        """REC-11 invariant 5 — an invalid pairing raises ValidationError; nothing deleted."""
        counting = _CountingStore(store)
        svc = MemoryService(StorageAdapter(counting))  # type: ignore[arg-type]

        with pytest.raises(ValidationError):
            await svc.delete(scope, project_id, str(uuid.uuid4()))
        assert counting.adelete_calls == 0

    async def test_no_existence_check(self, store: AsyncPostgresStore) -> None:
        """REC-11 constraint — no get-then-delete: one adelete, zero aget."""
        counting = _CountingStore(store)
        svc = MemoryService(StorageAdapter(counting))  # type: ignore[arg-type]
        mid = await svc.save(**_save_args())

        await svc.delete("project", "proj-42", mid)

        assert counting.adelete_calls == 1
        assert counting.aget_calls == 0

    async def test_other_users_memory_deletable(self, service: MemoryService) -> None:
        """REC-11 — memories are shared within a project; any user's memory can be deleted."""
        mid = await _save(service, user_id="bob")

        await service.delete("project", _PROJECT, mid)

        with pytest.raises(NotFoundError):
            await service.get_by_id("project", _PROJECT, mid)
