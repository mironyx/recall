"""Integration tests for the Memory Service — save + get_by_id (Issue #90, E1.5).

Contract sources:
- ``docs/design/v2/lld-e1-one-memory-e2e.md`` §E1.5 (anchor ``LLD-e1-memory-service``)
  — save (flat value + index=["content"]) and get_by_id with the reverse index
  in namespace ("_index", "_")
- ``docs/requirements/v2-requirements.md`` — Story 1.1 (store), Story 1.2 (scope
  invariant), Story 1.3 AC1/AC4 (embedding on save), Story 2.4 (get full record),
  Story 5.4 (storage namespace)
- Issue #90 acceptance criteria and BDD specs

Design notes:
- The unit under test is ``recall.memory_service.MemoryService``. Integration
  tests hit real Postgres+pgvector via the session-scoped ``store`` fixture
  (ADR-0012); the store is never mocked (CLAUDE.md). Reverse-index and
  embedding state are observed through the raw store and SQL, following the
  ``test_storage_adapter.py`` conventions.
- ``recall.errors.ValidationError`` is still the bare form pending issue #91
  (see TODO in ``src/recall/errors.py``), so invariant tests assert the
  exception type only. ``NotFoundError`` carries the structured
  {error, hint} shape already and is asserted fully.
- Embedding failure is observed at the save() boundary: the LLD implementation
  note (issue #88) dropped the interface-level EmbeddingError clause — retry
  and error machinery are provider-level (E4) — so the provider's error
  propagates and, per Story 1.3 AC4, no memory is stored without an embedding.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import psycopg
import pytest
import pytest_asyncio

from recall.errors import NotFoundError, ValidationError
from recall.memory_service import MemoryService
from recall.models import MemoryResponse
from recall.storage_adapter import GLOBAL_SENTINEL, StorageAdapter

if TYPE_CHECKING:
    from langgraph.store.postgres import AsyncPostgresStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_args(**overrides: Any) -> dict[str, Any]:
    """Valid save() kwargs for a project-scoped memory (Story 1.1 AC1)."""
    args: dict[str, Any] = {
        "scope": "project",
        "project_id": "proj-42",
        "user_id": "alice",
        "kind": "decision",
        "title": "Use event sourcing",
        "content": "The billing service uses event sourcing.",
    }
    args.update(overrides)
    return args


async def _store_value(conn_string: str, key: str) -> dict[str, Any]:
    """Read the raw JSONB ``value`` of a store row by key (LLD invariant I4)."""
    async with (
        await psycopg.AsyncConnection.connect(conn_string, autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        await cur.execute("SELECT value FROM store WHERE key = %s", (key,))
        row = await cur.fetchone()
        if row is None:
            raise AssertionError(f"no store row for key {key}")
        raw = row[0]
        # psycopg returns jsonb as str or dict depending on loader config.
        if isinstance(raw, str):
            parsed: dict[str, Any] = json.loads(raw)
            return parsed
        value: dict[str, Any] = raw
        return value


async def _vector_row_count(conn_string: str, key: str, prefix: str) -> int:
    """Count store_vectors rows for a key within a prefix (dot-joined namespace)."""
    async with (
        await psycopg.AsyncConnection.connect(conn_string, autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        await cur.execute(
            "SELECT COUNT(*) FROM store_vectors WHERE key = %s AND prefix = %s",
            (key, prefix),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


@pytest_asyncio.fixture
async def service(store: AsyncPostgresStore) -> MemoryService:
    """MemoryService over the session-scoped store fixture (LLD BDD ``service``)."""
    return MemoryService(StorageAdapter(store))


# ---------------------------------------------------------------------------
# save()
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMemoryServiceSave:
    """Issue #90 AC1/AC2/AC5 — save() builds the flat value, embeds content,
    writes the reverse index, and enforces the scope invariant."""

    async def test_save_returns_generated_uuid_id(self, service: MemoryService) -> None:
        """Given a valid project-scoped request, when save() is called, then a
        UUIDv4 string id is returned and the memory is retrievable by that id
        (Issue #90 AC1; Story 1.1 AC1; LLD BDD
        test_save_delegates_to_storage_and_returns_id)."""
        first_id = await service.save(**_save_args())
        second_id = await service.save(**_save_args())

        assert uuid.UUID(first_id).version == 4
        assert first_id != second_id
        assert (await service.get_by_id(first_id))["id"] == first_id

    async def test_save_persists_flat_value_at_root(
        self, service: MemoryService, pg_conn_string: str
    ) -> None:
        """Given a save() call, when the raw store row is inspected via SQL,
        then all ten flat fields sit at the root of the JSONB value with the
        given values — the model IS the stored shape, no hoisting (ADR-0001;
        LLD invariant I4; Issue #90 AC1)."""
        memory_id = await service.save(
            **_save_args(tags=["architecture"], metadata={"source": "adr-0001"})
        )

        value = await _store_value(pg_conn_string, memory_id)

        assert value["scope"] == "project"
        assert value["project_id"] == "proj-42"
        assert value["user_id"] == "alice"
        assert value["kind"] == "decision"
        assert value["title"] == "Use event sourcing"
        assert value["content"] == "The billing service uses event sourcing."
        assert value["tags"] == ["architecture"]
        assert value["metadata"] == {"source": "adr-0001"}
        assert "created_at" in value
        assert "updated_at" in value

    async def test_save_sets_created_and_updated_at(
        self, service: MemoryService, pg_conn_string: str
    ) -> None:
        """Given a save(), then created_at and updated_at are set automatically
        to the same ISO-8601 UTC timestamp (Story 1.1 AC6)."""
        memory_id = await service.save(**_save_args())

        value = await _store_value(pg_conn_string, memory_id)

        assert value["created_at"] == value["updated_at"]
        created = datetime.fromisoformat(value["created_at"])
        assert created.tzinfo is not None
        assert created.utcoffset() == timedelta(0)

    async def test_save_defaults_tags_and_metadata(
        self, service: MemoryService, pg_conn_string: str
    ) -> None:
        """Given tags and metadata omitted, when save() is called, then the
        stored value has tags=[] and metadata={} — never None (LLD save() code
        block; Story 1.1 AC3)."""
        memory_id = await service.save(**_save_args())

        value = await _store_value(pg_conn_string, memory_id)

        assert value["tags"] == []
        assert value["metadata"] == {}

    async def test_save_accepts_out_of_vocabulary_kind(self, service: MemoryService) -> None:
        """Given a kind value outside the default vocabulary, when save() is
        called, then the memory is stored successfully with that kind intact —
        kind is free-form with no server-side validation against a fixed list
        (Story 1.1 AC5). Eval addition: the sibling tests only ever use
        kind='decision', so the free-form property was unexercised."""
        memory_id = await service.save(**_save_args(kind="custom-schema-2026"))

        record = await service.get_by_id(memory_id)
        assert record["kind"] == "custom-schema-2026"

    async def test_save_embeds_content_but_not_index_entry(
        self, service: MemoryService, pg_conn_string: str
    ) -> None:
        """Given a save(), then exactly one store_vectors row exists for the
        memory (prefix 'project.proj-42') and none for the reverse-index entry
        (prefix '_index._') — index=["content"] for the memory, index=False
        for the index entry (Issue #90 AC1/AC2; Story 1.3 AC1; LLD design
        note)."""
        memory_id = await service.save(**_save_args())

        assert await _vector_row_count(pg_conn_string, memory_id, "project.proj-42") == 1
        assert await _vector_row_count(pg_conn_string, memory_id, "_index._") == 0

    async def test_save_writes_reverse_index_entry(
        self, service: MemoryService, store: AsyncPostgresStore
    ) -> None:
        """Given a save(), then the reverse index in namespace ("_index", "_")
        maps the memory id to {"scope", "project_id"} so get_by_id can resolve
        the namespace (Issue #90 AC2; LLD design note)."""
        memory_id = await service.save(**_save_args())

        entry = await store.aget(("_index", "_"), memory_id)

        assert entry is not None
        assert entry.namespace == ("_index", "_")
        assert entry.value == {"scope": "project", "project_id": "proj-42"}

    async def test_saved_memory_is_findable_by_semantic_search(
        self, service: MemoryService, store: AsyncPostgresStore
    ) -> None:
        """Given a saved memory with content, when the store is searched with a
        related query, then the memory appears — the content embedding exists
        and is searchable (LLD invariant I5; Story 1.3 AC1)."""
        memory_id = await service.save(**_save_args())

        results = await store.asearch(("project", "proj-42"), query="event sourcing billing")

        assert any(item.key == memory_id for item in results)

    async def test_save_global_memory_round_trip(
        self, service: MemoryService, store: AsyncPostgresStore, pg_conn_string: str
    ) -> None:
        """Given scope='global' and project_id='_', when save() is called, then
        the memory is stored under ('global', '_') with a matching reverse-index
        entry and get_by_id resolves it — cross-scope get works (Story 5.4 AC2;
        LLD BDD test_save_global_memory; Issue #90 AC3)."""
        memory_id = await service.save(**_save_args(scope="global", project_id=GLOBAL_SENTINEL))

        item = await store.aget(("global", GLOBAL_SENTINEL), memory_id)
        assert item is not None
        assert item.value["scope"] == "global"
        assert item.value["project_id"] == GLOBAL_SENTINEL

        entry = await store.aget(("_index", "_"), memory_id)
        assert entry is not None
        assert entry.value == {"scope": "global", "project_id": GLOBAL_SENTINEL}

        record = await service.get_by_id(memory_id)
        assert record["scope"] == "global"
        assert record["project_id"] == GLOBAL_SENTINEL

    @pytest.mark.parametrize(
        ("scope", "project_id"),
        [
            ("global", "proj-42"),  # Story 1.2 AC4 — global must not carry a project ID
            ("project", GLOBAL_SENTINEL),  # Story 1.2 AC2 — project requires a real ID, not '_'
            ("team", "proj-42"),  # Story 1.2 AC5 — invalid scope value
        ],
    )
    async def test_save_rejects_scope_invariant_violations(
        self,
        service: MemoryService,
        pg_conn_string: str,
        scope: str,
        project_id: str,
    ) -> None:
        """Given a (scope, project_id) pair that violates the invariant, when
        save() is called, then ValidationError is raised and nothing is
        persisted — no memory row and no reverse-index entry (Issue #90 AC5;
        Story 1.2 AC2/AC4/AC5)."""
        with pytest.raises(ValidationError):
            await service.save(**_save_args(scope=scope, project_id=project_id))

        # The store fixture TRUNCATEs per test, so any row at all is a leak.
        async with (
            await psycopg.AsyncConnection.connect(pg_conn_string, autocommit=True) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute("SELECT COUNT(*) FROM store")
            row = await cur.fetchone()
            assert (row[0] if row else 0) == 0

    async def test_save_embedding_failure_persists_nothing(
        self, service: MemoryService, pg_conn_string: str
    ) -> None:
        """Given an embedding provider that fails, when save() is attempted,
        then the error propagates and no memory is stored — a memory never
        exists with a missing embedding (Story 1.3 AC4). The {error, hint}
        envelope and retry machinery are provider-level (E4, LLD implementation
        note for issue #88), so here the provider's error surfaces raw at the
        save() boundary."""
        from langgraph.store.postgres import AsyncPostgresStore
        from langgraph.store.postgres.base import PostgresIndexConfig

        def _raise(texts: Sequence[str]) -> list[list[float]]:
            raise RuntimeError("embedding provider unavailable")

        # Dim must match the schema column (same resolution as the conftest
        # store fixture); the embedder is never invoked with real texts.
        # The match pins propagation of the provider's error, keeping this
        # test red against the NotImplementedError stub (which is itself a
        # RuntimeError subclass).
        raw_dims = os.environ.get("RECALL_EMBEDDING_DIMS")
        dims = int(raw_dims) if raw_dims else 1536
        config = PostgresIndexConfig(dims=dims, embed=_raise)
        async with AsyncPostgresStore.from_conn_string(
            pg_conn_string, index=config
        ) as broken_store:
            broken_service = MemoryService(StorageAdapter(broken_store))

            with pytest.raises(RuntimeError, match="embedding provider unavailable"):
                await broken_service.save(**_save_args(content="must not be stored"))

        async with (
            await psycopg.AsyncConnection.connect(pg_conn_string, autocommit=True) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute("SELECT COUNT(*) FROM store")
            row = await cur.fetchone()
            assert (row[0] if row else 0) == 0


# ---------------------------------------------------------------------------
# get_by_id()
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMemoryServiceGet:
    """Issue #90 AC3/AC4 — get_by_id resolves the namespace via the reverse
    index and returns the full record."""

    async def test_get_by_id_returns_full_record(self, service: MemoryService) -> None:
        """Given a saved memory, when get_by_id is called with its id, then the
        full record is returned — id plus all ten flat fields with the stored
        values, satisfying the MemoryResponse model (Story 2.4 AC1; LLD
        invariant I6; BDD test_get_by_id_returns_full_record)."""
        memory_id = await service.save(
            **_save_args(tags=["architecture"], metadata={"source": "adr-0001"})
        )

        record = await service.get_by_id(memory_id)

        assert record["id"] == memory_id
        assert record["scope"] == "project"
        assert record["project_id"] == "proj-42"
        assert record["user_id"] == "alice"
        assert record["kind"] == "decision"
        assert record["title"] == "Use event sourcing"
        assert record["content"] == "The billing service uses event sourcing."
        assert record["tags"] == ["architecture"]
        assert record["metadata"] == {"source": "adr-0001"}
        assert record["created_at"] == record["updated_at"]
        MemoryResponse(**record)

    async def test_get_by_id_not_found(self, service: MemoryService) -> None:
        """Given an id that was never saved, when get_by_id is called, then
        NotFoundError is raised with the structured not_found shape; a
        non-UUID string id is treated the same (Story 2.4 AC2; Issue #90 AC4;
        BDD test_get_by_id_not_found)."""
        for unknown_id in (str(uuid.uuid4()), "not-a-uuid"):
            with pytest.raises(NotFoundError) as exc_info:
                await service.get_by_id(unknown_id)
            assert exc_info.value.error == "not_found"
            assert unknown_id in exc_info.value.hint

    async def test_get_by_id_resolves_namespace_via_reverse_index(
        self, service: MemoryService, store: AsyncPostgresStore
    ) -> None:
        """Given a saved memory whose reverse-index entry is removed, when
        get_by_id is called, then NotFoundError is raised even though the
        memory itself still exists — the id is resolved through the index
        (Issue #90 AC3; LLD design note)."""
        memory_id = await service.save(**_save_args())

        await store.adelete(("_index", "_"), memory_id)
        assert await store.aget(("project", "proj-42"), memory_id) is not None

        with pytest.raises(NotFoundError):
            await service.get_by_id(memory_id)
