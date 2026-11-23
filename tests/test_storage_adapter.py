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
from tests.test_memory_service import _vector_row_count

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


# ---------------------------------------------------------------------------
# REC-3 — StorageAdapter.search (E2.1)
# ---------------------------------------------------------------------------
# Planting recipe: StubEmbeddingsProvider is a hash embedder with no semantic
# structure. Cosine is ~1.0 only for byte-identical text, so every ranking
# assertion sets the query byte-identical to one memory's ``content``.


async def _plant(
    adapter: StorageAdapter,
    scope: str,
    project_id: str,
    content: str,
    **overrides: Any,
) -> str:
    """Store one memory indexed on ``content`` (as E1's save does); return its key."""
    key = str(uuid.uuid4())
    value = _memory_value(scope=scope, project_id=project_id, content=content, **overrides)
    await adapter.put(scope, project_id, key, value, index=["content"])
    return key


@pytest.mark.integration
class TestStorageAdapterSearch:
    """BDD spec (REC-3) — namespace-exact semantic search."""

    async def test_exact_content_match_scores_highest(self, store: AsyncPostgresStore) -> None:
        """Given a query byte-identical to one memory's content, it ranks first at ~1.0."""
        adapter = StorageAdapter(store)
        await _plant(adapter, "project", "app", "alpha content")
        target = await _plant(adapter, "project", "app", "beta content")
        await _plant(adapter, "project", "app", "gamma content")

        results = await adapter.search("project", "app", "beta content")

        assert results[0].key == target
        assert results[0].score == pytest.approx(1.0, abs=1e-3)
        assert all(r.score is not None and r.score < 0.5 for r in results[1:])

    async def test_scores_are_passed_through_unmodified(self, store: AsyncPostgresStore) -> None:
        """Given a planted memory, the adapter's score equals the raw store score."""
        adapter = StorageAdapter(store)
        key = await _plant(adapter, "project", "app", "score passthrough")

        results = await adapter.search("project", "app", "score passthrough")
        raw = await store.asearch(("project", "app"), query="score passthrough", limit=10)

        raw_score = next(r.score for r in raw if r.key == key)
        adapter_score = next(r.score for r in results if r.key == key)
        assert adapter_score == raw_score

    async def test_prefix_overlapping_project_is_isolated(self, store: AsyncPostgresStore) -> None:
        """Given memories in 'app' and 'app-v2', a search in 'app' returns only 'app'."""
        adapter = StorageAdapter(store)
        in_app = await _plant(adapter, "project", "app", "shared text")
        in_v2 = await _plant(adapter, "project", "app-v2", "shared text")
        in_foo = await _plant(adapter, "project", "appfoo", "shared text")

        results = await adapter.search("project", "app", "shared text")

        keys = {r.key for r in results}
        assert keys == {in_app}
        assert in_v2 not in keys and in_foo not in keys
        assert all(r.namespace == ("project", "app") for r in results)

    async def test_global_namespace_search(self, store: AsyncPostgresStore) -> None:
        """Given scope=global, only the ('global', '_') namespace is searched."""
        adapter = StorageAdapter(store)
        glob = await _plant(adapter, "global", GLOBAL_SENTINEL, "same text")
        await _plant(adapter, "project", "app", "same text")

        results = await adapter.search("global", GLOBAL_SENTINEL, "same text")

        assert [r.key for r in results] == [glob]
        assert results[0].namespace == ("global", GLOBAL_SENTINEL)

    async def test_empty_result_is_not_an_error(self, store: AsyncPostgresStore) -> None:
        """Given no matching memories, an empty list is returned."""
        adapter = StorageAdapter(store)

        assert await adapter.search("project", "nothing-here", "anything") == []

    async def test_kind_filter_applied(self, store: AsyncPostgresStore) -> None:
        """Given filter={'kind': 'decision'}, only decision memories return."""
        adapter = StorageAdapter(store)
        decision = await _plant(adapter, "project", "app", "one", kind="decision")
        await _plant(adapter, "project", "app", "two", kind="note")

        results = await adapter.search("project", "app", "one", filter={"kind": "decision"})

        assert [r.key for r in results] == [decision]

    async def test_user_id_filter_applied(self, store: AsyncPostgresStore) -> None:
        """Given filter={'user_id': 'alice'}, only alice's memories return."""
        adapter = StorageAdapter(store)
        alice = await _plant(adapter, "project", "app", "one", user_id="alice")
        await _plant(adapter, "project", "app", "two", user_id="bob")

        results = await adapter.search("project", "app", "one", filter={"user_id": "alice"})

        assert [r.key for r in results] == [alice]

    async def test_kind_and_user_id_filters_are_conjunctive(
        self, store: AsyncPostgresStore
    ) -> None:
        """Given both keys in one filter dict, they AND together (ADR-0004)."""
        adapter = StorageAdapter(store)
        both = await _plant(adapter, "project", "app", "t1", kind="decision", user_id="alice")
        await _plant(adapter, "project", "app", "t2", kind="decision", user_id="bob")
        await _plant(adapter, "project", "app", "t3", kind="note", user_id="alice")

        results = await adapter.search(
            "project", "app", "t1", filter={"kind": "decision", "user_id": "alice"}
        )

        assert [r.key for r in results] == [both]

    async def test_unsupported_filter_key_rejected(self, store: AsyncPostgresStore) -> None:
        """Given filter={'tags': [...]}, ValidationError names the key (ADR-0004)."""
        adapter = StorageAdapter(store)

        with pytest.raises(ValidationError, match="tags"):
            await adapter.search("project", "app", "q", filter={"tags": ["architecture"]})

    async def test_caller_cannot_override_scoping_via_filter(
        self, store: AsyncPostgresStore
    ) -> None:
        """Given a filter naming project_id/scope, it is rejected (not in {kind, user_id})
        so a caller cannot widen the namespace."""
        adapter = StorageAdapter(store)
        await _plant(adapter, "project", "other", "leak me")

        with pytest.raises(ValidationError, match="project_id"):
            await adapter.search("project", "app", "leak me", filter={"project_id": "other"})
        with pytest.raises(ValidationError, match="scope"):
            await adapter.search("project", "app", "leak me", filter={"scope": "global"})

    async def test_scope_invariant_enforced(self, store: AsyncPostgresStore) -> None:
        """Given scope=global with a real project_id, ValidationError propagates."""
        adapter = StorageAdapter(store)

        with pytest.raises(ValidationError):
            await adapter.search("global", "app", "q")
        with pytest.raises(ValidationError):
            await adapter.search("project", GLOBAL_SENTINEL, "q")

    async def test_limit_forwarded(self, store: AsyncPostgresStore) -> None:
        """Given limit=2 and three matches, exactly two results return."""
        adapter = StorageAdapter(store)
        for i in range(3):
            await _plant(adapter, "project", "app", f"memory {i}")

        results = await adapter.search("project", "app", "memory 0", limit=2)

        assert len(results) == 2

    async def test_single_round_trip(self, counting_adapter: Any) -> None:
        """Given one search call, exactly one asearch reaches the store."""
        await _plant(counting_adapter, "project", "app", "round trip")

        results = await counting_adapter.search("project", "app", "round trip")

        assert len(results) == 1
        assert counting_adapter.counting_store.asearch_calls == 1


class TestScopingFilter:
    """Pure unit tests — no DB."""

    def test_injects_scope_and_project_id(self) -> None:
        """Given any inputs, the returned filter carries both keys."""
        result = StorageAdapter._scoping_filter("project", "app", None)

        assert result["scope"] == "project"
        assert result["project_id"] == "app"

    def test_preserves_caller_filter_keys(self) -> None:
        """Given filter={'kind': 'x'}, the result carries kind, scope and project_id."""
        result = StorageAdapter._scoping_filter("project", "app", {"kind": "x"})

        assert result["kind"] == "x"
        assert result["scope"] == "project"
        assert result["project_id"] == "app"

    def test_injected_keys_win_over_caller_keys(self) -> None:
        """Given a caller filter containing scope/project_id, injected values win."""
        result = StorageAdapter._scoping_filter(
            "project", "app", {"scope": "global", "project_id": "other"}
        )

        assert result["scope"] == "project"
        assert result["project_id"] == "app"

    def test_does_not_mutate_caller_filter(self) -> None:
        """Given a caller filter dict, it is left unchanged."""
        caller = {"kind": "x"}

        StorageAdapter._scoping_filter("project", "app", caller)

        assert caller == {"kind": "x"}

    def test_validate_filter_keys_accepts_none_and_allowed(self) -> None:
        """None, {} and {kind, user_id} pass the ADR-0004 key guard."""
        StorageAdapter._validate_filter_keys(None)
        StorageAdapter._validate_filter_keys({})
        StorageAdapter._validate_filter_keys({"kind": "a", "user_id": "b"})

    def test_validate_filter_keys_rejects_unknown_key_by_name(self) -> None:
        """Given a key outside {kind, user_id}, ValidationError names it."""
        with pytest.raises(ValidationError, match="tags"):
            StorageAdapter._validate_filter_keys({"kind": "a", "tags": ["x"]})


# ---------------------------------------------------------------------------
# delete() — REC-11 (E3.2), LLD §3.3 anchor LLD-e3-delete
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStorageAdapterDelete:
    """REC-11 — delete via _build_namespace then adelete; idempotent; namespace-exact."""

    async def test_deleted_memory_absent_from_get_and_search(
        self, store: AsyncPostgresStore
    ) -> None:
        """REC-11 invariant 1 — after delete, get is None and search never returns the key."""
        adapter = StorageAdapter(store)
        key = await _plant(adapter, "project", "proj-42", "delete me please")

        await adapter.delete("project", "proj-42", key)

        assert await adapter.get("project", "proj-42", key) is None
        hits = await adapter.search("project", "proj-42", "delete me please")
        assert key not in [h.key for h in hits]

    async def test_delete_removes_embedding_row(
        self, store: AsyncPostgresStore, pg_conn_string: str
    ) -> None:
        """REC-11 invariant 2 — the store_vectors row goes with the store row (FK cascade)."""
        adapter = StorageAdapter(store)
        key = await _plant(adapter, "project", "proj-42", "embedded content")
        assert await _vector_row_count(pg_conn_string, key, "project.proj-42") == 1

        await adapter.delete("project", "proj-42", key)

        assert await _vector_row_count(pg_conn_string, key, "project.proj-42") == 0

    async def test_delete_is_idempotent(self, store: AsyncPostgresStore) -> None:
        """REC-11 invariant 3 — deleting an absent key twice is a no-op, never an error."""
        adapter = StorageAdapter(store)
        key = str(uuid.uuid4())

        await adapter.delete("project", "proj-42", key)
        await adapter.delete("project", "proj-42", key)

    async def test_delete_twice_after_save(self, store: AsyncPostgresStore) -> None:
        """REC-11 — a second delete of an already-deleted key is still a no-op."""
        adapter = StorageAdapter(store)
        key = await _plant(adapter, "global", GLOBAL_SENTINEL, "global text")

        await adapter.delete("global", GLOBAL_SENTINEL, key)
        await adapter.delete("global", GLOBAL_SENTINEL, key)

        assert await adapter.get("global", GLOBAL_SENTINEL, key) is None

    async def test_delete_wrong_namespace_leaves_memory(self, store: AsyncPostgresStore) -> None:
        """REC-11 invariant 4 — delete in namespace A never removes the same key in B."""
        adapter = StorageAdapter(store)
        key = str(uuid.uuid4())
        await adapter.put("project", "proj-a", key, _memory_value(project_id="proj-a"))
        await adapter.put("project", "proj-b", key, _memory_value(project_id="proj-b"))
        await adapter.put(
            "global", GLOBAL_SENTINEL, key,
            _memory_value(scope="global", project_id=GLOBAL_SENTINEL),
        )  # fmt: skip

        await adapter.delete("project", "proj-a", key)

        assert await adapter.get("project", "proj-a", key) is None
        assert await adapter.get("project", "proj-b", key) is not None
        assert await adapter.get("global", GLOBAL_SENTINEL, key) is not None

    async def test_delete_prefix_namespace_does_not_match(self, store: AsyncPostgresStore) -> None:
        """REC-11 invariant 4 — 'app' must not delete the same key under 'app-v2'."""
        adapter = StorageAdapter(store)
        key = str(uuid.uuid4())
        await adapter.put("project", "app-v2", key, _memory_value(project_id="app-v2"))

        await adapter.delete("project", "app", key)

        assert await adapter.get("project", "app-v2", key) is not None

    @pytest.mark.parametrize(
        ("scope", "project_id"),
        [("global", "proj-42"), ("project", GLOBAL_SENTINEL), ("team", "proj-42")],
    )
    async def test_delete_scope_invariant_enforced(
        self, counting_adapter: Any, scope: str, project_id: str
    ) -> None:
        """REC-11 invariant 5 — an invalid namespace raises ValidationError before adelete."""
        with pytest.raises(ValidationError):
            await counting_adapter.delete(scope, project_id, str(uuid.uuid4()))

        assert counting_adapter.counting_store.adelete_calls == 0

    async def test_delete_single_round_trip(self, counting_adapter: Any) -> None:
        """REC-11 — one adelete reaches the store; no get-then-delete existence check."""
        key = await _plant(counting_adapter, "project", "proj-42", "round trip")

        await counting_adapter.delete("project", "proj-42", key)

        assert counting_adapter.counting_store.adelete_calls == 1
        assert counting_adapter.counting_store.aget_calls == 0
