"""Integration tests for StorageAdapter and domain models (Issue #89).

Contract sources:
- ``docs/design/v2/lld-e1-one-memory-e2e.md`` §E1.4 (anchor ``LLD-e1-storage-adapter``)
  and §E1 models (anchor ``LLD-e1-models``)
- ``docs/requirements/v2-requirements.md`` (Story 1.2 — scope invariant;
  Story 5.4 — storage namespace ``(scope, project_id)``)
- Issue #89 acceptance criteria and BDD specs

Design notes:
- Integration tests hit real Postgres+pgvector via the session-scoped ``store``
  fixture (ADR-0012); the store is never mocked (CLAUDE.md).
- Namespace construction (``_build_namespace``) is private; it is observed
  through the public put/get API plus direct reads/writes on the raw store.
- Invariant violations raise ``recall.errors.ValidationError`` — not pydantic's.
  The structured {error, hint} envelope is deferred to issue #91 (see TODO in
  ``src/recall/errors.py``), so tests assert the exception type only.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import psycopg
import pytest
from pydantic import ValidationError as PydanticValidationError

from recall.errors import ValidationError
from recall.models import MemoryRecord, MemoryResponse
from recall.storage_adapter import GLOBAL_SENTINEL, StorageAdapter

if TYPE_CHECKING:
    from langgraph.store.postgres import AsyncPostgresStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _memory_value(**overrides: Any) -> dict[str, Any]:
    """A flat memory value dict in the ADR-0001 shape (all MemoryRecord fields)."""
    value: dict[str, Any] = {
        "scope": "project",
        "project_id": "proj-42",
        "user_id": "alice",
        "kind": "decision",
        "title": "Use event sourcing",
        "content": "The billing service uses event sourcing.",
        "tags": ["architecture"],
        "metadata": {"source": "adr-0001"},
        "created_at": "2026-08-09T10:00:00+00:00",
        "updated_at": "2026-08-09T10:00:00+00:00",
    }
    value.update(overrides)
    return value


@pytest.mark.integration
class TestStorageAdapter:
    """BDD spec (issue #89) — put/get with namespace construction."""

    async def test_put_and_get_round_trip(self, store: AsyncPostgresStore) -> None:
        """Given a scope, project_id, key, and flat value, when put() then
        get() are called through the adapter, then the same value dict is
        returned (Issue #89 AC1/AC2; Story 1.4 AC1).

        ``index=["content"]`` exercises the forwarded ``index`` argument —
        put() must delegate the full signature to store.aput()."""
        adapter = StorageAdapter(store)
        key = str(uuid.uuid4())
        value = _memory_value()

        await adapter.put("project", "proj-42", key, value, index=["content"])
        item = await adapter.get("project", "proj-42", key)

        assert item is not None
        assert item.key == key
        assert item.value == value
        assert item.namespace == ("project", "proj-42")

    async def test_namespace_construction(self, store: AsyncPostgresStore) -> None:
        """Given project and global memories stored via put(), when the raw
        store is read under the expected (scope, project_id) tuples, then both
        are found — project uses ('project', pid) and global uses
        ('global', '_') with the GLOBAL_SENTINEL (Story 5.4 AC1/AC2; Issue #89
        BDD spec)."""
        adapter = StorageAdapter(store)

        proj_key = str(uuid.uuid4())
        proj_value = _memory_value()
        await adapter.put("project", "proj-42", proj_key, proj_value)
        proj_item = await store.aget(("project", "proj-42"), proj_key)
        assert proj_item is not None
        assert proj_item.value == proj_value

        glob_key = str(uuid.uuid4())
        glob_value = _memory_value(scope="global", project_id=GLOBAL_SENTINEL)
        await adapter.put("global", GLOBAL_SENTINEL, glob_key, glob_value)
        glob_item = await store.aget(("global", GLOBAL_SENTINEL), glob_key)
        assert glob_item is not None
        assert glob_item.value == glob_value

        assert GLOBAL_SENTINEL == "_"

    async def test_scope_invariant_defence_in_depth(self, store: AsyncPostgresStore) -> None:
        """Given scope='project' with project_id='_', when put() is called,
        then recall.errors.ValidationError is raised and nothing is persisted
        — the adapter rejects before any DB write (Issue #89 BDD spec;
        Story 1.2 AC3)."""
        adapter = StorageAdapter(store)
        key = str(uuid.uuid4())

        with pytest.raises(ValidationError):
            await adapter.put("project", GLOBAL_SENTINEL, key, _memory_value())

        assert await store.aget(("project", GLOBAL_SENTINEL), key) is None

    async def test_get_constructs_the_same_namespace(self, store: AsyncPostgresStore) -> None:
        """Given a value written directly into the store under ('project', pid)
        (bypassing the adapter), when get() is called with the same scope and
        project_id, then the item is returned with that namespace — get()
        delegates to store.aget() with the constructed namespace (Issue #89
        AC2)."""
        adapter = StorageAdapter(store)
        key = str(uuid.uuid4())
        value = _memory_value()
        await store.aput(("project", "proj-42"), key, value, index=False)

        item = await adapter.get("project", "proj-42", key)

        assert item is not None
        assert item.key == key
        assert item.value == value
        assert item.namespace == ("project", "proj-42")

    async def test_get_missing_key_returns_none(self, store: AsyncPostgresStore) -> None:
        """Given a key that was never stored, when get() is called, then None
        is returned — not an error (LLD: ``get() -> Item | None``)."""
        adapter = StorageAdapter(store)

        assert await adapter.get("project", "proj-42", str(uuid.uuid4())) is None

    async def test_global_scope_requires_sentinel_project_id(
        self, store: AsyncPostgresStore
    ) -> None:
        """Given scope='global' with a real project ID, when put() is called,
        then recall.errors.ValidationError is raised and nothing is persisted
        (Story 1.2 AC4; Issue #89 AC3)."""
        adapter = StorageAdapter(store)
        key = str(uuid.uuid4())

        with pytest.raises(ValidationError):
            await adapter.put("global", "proj-42", key, _memory_value(scope="global"))

        assert await store.aget(("global", "proj-42"), key) is None

    async def test_invariant_enforced_on_get(self, store: AsyncPostgresStore) -> None:
        """Given an invariant-violating (scope, project_id) pair, when get()
        is called, then recall.errors.ValidationError is raised on the read
        path too — defence-in-depth applies to both operations (Issue #89
        AC3)."""
        adapter = StorageAdapter(store)
        key = str(uuid.uuid4())

        with pytest.raises(ValidationError):
            await adapter.get("project", GLOBAL_SENTINEL, key)
        with pytest.raises(ValidationError):
            await adapter.get("global", "proj-42", key)

    async def test_invalid_scope_raises_validation_error(self, store: AsyncPostgresStore) -> None:
        """Given a scope outside {'project', 'global'}, when put() or get() is
        called, then recall.errors.ValidationError is raised (Story 1.2 AC5)."""
        adapter = StorageAdapter(store)
        key = str(uuid.uuid4())

        with pytest.raises(ValidationError):
            await adapter.put("team", "proj-42", key, _memory_value())
        with pytest.raises(ValidationError):
            await adapter.get("team", "proj-42", key)

    async def test_cross_project_isolation(self, store: AsyncPostgresStore) -> None:
        """Given a memory stored under project A, when get() is called with
        project B, then None is returned — a memory is never visible outside
        its project namespace (Story 5.4 AC3)."""
        adapter = StorageAdapter(store)
        key = str(uuid.uuid4())
        await adapter.put("project", "proj-a", key, _memory_value(project_id="proj-a"))

        assert await adapter.get("project", "proj-b", key) is None
        assert await adapter.get("project", "proj-a", key) is not None

    async def test_index_false_skips_embedding(
        self, store: AsyncPostgresStore, pg_conn_string: str
    ) -> None:
        """Given index=False passed through put(), when the record is stored,
        then no embedding row is created in store_vectors; given
        index=["content"], then one row is created for that field — the
        three-state index signature (list | False | None) is forwarded to
        store.aput() verbatim (LLD §E1.4 put() signature; the E1.5 reverse
        index design relies on index=False)."""
        adapter = StorageAdapter(store)
        no_index_key = str(uuid.uuid4())
        embedded_key = str(uuid.uuid4())

        await adapter.put("project", "proj-42", no_index_key, _memory_value(), index=False)
        await adapter.put("project", "proj-42", embedded_key, _memory_value(), index=["content"])

        async def _vector_row_count(key: str) -> int:
            async with (
                await psycopg.AsyncConnection.connect(pg_conn_string, autocommit=True) as conn,
                conn.cursor() as cur,
            ):
                await cur.execute("SELECT COUNT(*) FROM store_vectors WHERE key = %s", (key,))
                row = await cur.fetchone()
                return int(row[0]) if row else 0

        assert await _vector_row_count(no_index_key) == 0
        assert await _vector_row_count(embedded_key) == 1

    async def test_memory_record_flat_dict_round_trip(self, store: AsyncPostgresStore) -> None:
        """Given a MemoryRecord, when its flat dict is put() and the result is
        get(), then the returned value reconstructs an equal MemoryRecord —
        the model IS the stored shape, no hoist/unhoist (ADR-0001; Issue #89
        AC4)."""
        adapter = StorageAdapter(store)
        key = str(uuid.uuid4())
        record = MemoryRecord(**_memory_value())

        await adapter.put("project", "proj-42", key, record.model_dump())
        item = await adapter.get("project", "proj-42", key)

        assert item is not None
        assert MemoryRecord(**item.value) == record


class TestMemoryRecordModel:
    """Flat value schema (ADR-0001) — LLD §E1 ``MemoryRecord`` (Issue #89 AC4)."""

    def test_all_flat_fields_present(self) -> None:
        """Given a fully-populated record, when inspecting its fields, then all
        ten flat fields of the stored shape are present at the root with the
        given values (LLD §E1-models)."""
        record = MemoryRecord(**_memory_value())

        assert record.scope == "project"
        assert record.project_id == "proj-42"
        assert record.user_id == "alice"
        assert record.kind == "decision"
        assert record.title == "Use event sourcing"
        assert record.content == "The billing service uses event sourcing."
        assert record.tags == ["architecture"]
        assert record.metadata == {"source": "adr-0001"}
        assert record.created_at == "2026-08-09T10:00:00+00:00"
        assert record.updated_at == "2026-08-09T10:00:00+00:00"

    def test_tags_and_metadata_default_to_empty(self) -> None:
        """Given tags and metadata omitted, when a MemoryRecord is built, then
        tags defaults to [] and metadata to {} — default factories, not None
        (LLD: ``default_factory=list`` / ``default_factory=dict``)."""
        fields = _memory_value()
        del fields["tags"]
        del fields["metadata"]

        record = MemoryRecord(**fields)

        assert record.tags == []
        assert record.metadata == {}

    @pytest.mark.parametrize(
        "missing",
        [
            "scope",
            "project_id",
            "user_id",
            "kind",
            "title",
            "content",
            "created_at",
            "updated_at",
        ],
    )
    def test_required_fields_cannot_be_omitted(self, missing: str) -> None:
        """Given any required field omitted, when a MemoryRecord is built, then
        pydantic ValidationError is raised — only tags/metadata have defaults
        (LLD §E1-models; Story 1.1 AC4)."""
        fields = _memory_value()
        del fields[missing]

        with pytest.raises(PydanticValidationError):
            MemoryRecord(**fields)

    def test_kind_is_free_form(self) -> None:
        """Given a kind outside the documented vocabulary, when a MemoryRecord
        is built, then it is accepted — kind is data, not a server-side enum
        (Story 1.1 AC5)."""
        record = MemoryRecord(**{**_memory_value(), "kind": "custom-kind"})

        assert record.kind == "custom-kind"


class TestMemoryResponseModel:
    """Full record returned by memory_get — LLD §E1 ``MemoryResponse``
    (Issue #89 AC5)."""

    def test_includes_id_as_first_field(self) -> None:
        """Given a response with an id, when inspecting its fields, then id is
        present and declared first (LLD: ``id: str`` is the first field;
        Issue #89 AC5)."""
        response = MemoryResponse(id="mem-1", **_memory_value())

        assert response.id == "mem-1"
        assert next(iter(MemoryResponse.model_fields)) == "id"

    def test_built_from_memory_record_dict_plus_id(self) -> None:
        """Given a MemoryRecord's flat dict, when a MemoryResponse is built
        with an id on top, then all record fields carry through — memory_get
        returns the full record including id (Story 2.4 AC1; Issue #89 AC5)."""
        record = MemoryRecord(**_memory_value())

        response = MemoryResponse(**record.model_dump(), id="mem-1")

        assert response.model_dump() == {"id": "mem-1", **record.model_dump()}

    def test_id_is_required(self) -> None:
        """Given no id, when a MemoryResponse is built, then pydantic
        ValidationError is raised (LLD: ``id: str`` has no default)."""
        with pytest.raises(PydanticValidationError):
            MemoryResponse(**_memory_value())
