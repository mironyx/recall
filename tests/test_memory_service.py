"""Integration tests for the Memory Service — save + get_by_id (Issue #90, E1.5).

Contract sources:
- ``docs/design/v2/lld-e1-one-memory-e2e.md`` §E1.5 (anchor ``LLD-e1-memory-service``)
  — save (flat value + index=["content"]) and scope-explicit get_by_id (ADR-0015)
- ``docs/requirements/v2-requirements.md`` — Story 1.1 (store), Story 1.2 (scope
  invariant), Story 1.3 AC1/AC4 (embedding on save), Story 2.4 (get full record),
  Story 5.4 (storage namespace)
- Issue #90 acceptance criteria and BDD specs

Design notes:
- The unit under test is ``recall.memory_service.MemoryService``. Integration
  tests hit real Postgres+pgvector via the session-scoped ``store`` fixture
  (ADR-0012); the store is never mocked (CLAUDE.md). Embedding state is
  observed through the raw store and SQL, following the
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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import psycopg
import pytest
import pytest_asyncio
from langgraph.store.base import SearchItem

from recall.config import SearchConfig
from recall.errors import NotFoundError, ValidationError
from recall.memory_service import MemoryService
from recall.models import MemoryResponse, SearchResult
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
    """Issue #90 AC1/AC5 — save() builds the flat value, embeds content, and
    enforces the scope invariant (single write, ADR-0015)."""

    async def test_save_returns_generated_uuid_id(self, service: MemoryService) -> None:
        """Given a valid project-scoped request, when save() is called, then a
        UUIDv4 string id is returned and the memory is retrievable by that id
        (Issue #90 AC1; Story 1.1 AC1; LLD BDD
        test_save_delegates_to_storage_and_returns_id)."""
        first_id = await service.save(**_save_args())
        second_id = await service.save(**_save_args())

        assert uuid.UUID(first_id).version == 4
        assert first_id != second_id
        assert (await service.get_by_id("project", "proj-42", first_id))["id"] == first_id

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

        record = await service.get_by_id("project", "proj-42", memory_id)
        assert record["kind"] == "custom-schema-2026"

    async def test_save_embeds_content(self, service: MemoryService, pg_conn_string: str) -> None:
        """Given a save(), then exactly one store_vectors row exists for the
        memory (prefix 'project.proj-42') — index=["content"] on the single
        write (Issue #90 AC1; Story 1.3 AC1)."""
        memory_id = await service.save(**_save_args())

        assert await _vector_row_count(pg_conn_string, memory_id, "project.proj-42") == 1

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
        the memory is stored under ('global', '_') and get_by_id reads it
        directly — cross-scope get works (Story 5.4 AC2; LLD BDD
        test_save_global_memory)."""
        memory_id = await service.save(**_save_args(scope="global", project_id=GLOBAL_SENTINEL))

        item = await store.aget(("global", GLOBAL_SENTINEL), memory_id)
        assert item is not None
        assert item.value["scope"] == "global"
        assert item.value["project_id"] == GLOBAL_SENTINEL

        record = await service.get_by_id("global", GLOBAL_SENTINEL, memory_id)
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
        persisted — no memory row (Issue #90 AC5;
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
    """Issue #90 AC4 — get_by_id takes (scope, project_id, id) and returns
    the full record directly (ADR-0015)."""

    async def test_get_by_id_returns_full_record(self, service: MemoryService) -> None:
        """Given a saved memory, when get_by_id is called with its scope,
        project_id and id, then the full record is returned — id plus all ten
        flat fields with the stored values, satisfying the MemoryResponse
        model (Story 2.4 AC1; LLD invariant I6; BDD
        test_get_by_id_returns_full_record)."""
        memory_id = await service.save(
            **_save_args(tags=["architecture"], metadata={"source": "adr-0001"})
        )

        record = await service.get_by_id("project", "proj-42", memory_id)

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
        """Given an id that was never saved, when get_by_id is called with a
        known namespace, then NotFoundError is raised with the structured
        not_found shape; a non-UUID string id is treated the same (Story 2.4
        AC2; Issue #90 AC4; BDD test_get_by_id_not_found)."""
        for unknown_id in (str(uuid.uuid4()), "not-a-uuid"):
            with pytest.raises(NotFoundError) as exc_info:
                await service.get_by_id("project", "proj-42", unknown_id)
            assert exc_info.value.error == "not_found"
            assert unknown_id in exc_info.value.hint


# ---------------------------------------------------------------------------
# search() — REC-4 (E2.2), LLD §2.2 anchor LLD-e2-service-search
# ---------------------------------------------------------------------------

_PROJECT = "proj-42"


class _RecordingAdapter:
    """Delegating decorator over a real ``StorageAdapter`` that records the
    arguments of every ``search`` call. Every call is forwarded to the real
    adapter/store — nothing is stubbed (CLAUDE.md: never mock the store)."""

    def __init__(self, inner: StorageAdapter) -> None:
        self._inner = inner
        self.search_calls: list[dict[str, Any]] = []

    async def search(self, **kwargs: Any) -> list[SearchItem]:
        self.search_calls.append(kwargs)
        return await self._inner.search(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def _save(
    service: MemoryService,
    *,
    scope: str = "project",
    user_id: str = "alice",
    kind: str = "decision",
    title: str = "Use event sourcing",
    content: str = "The billing service uses event sourcing.",
) -> str:
    project_id = _PROJECT if scope == "project" else GLOBAL_SENTINEL
    return await service.save(
        scope=scope,
        project_id=project_id,
        user_id=user_id,
        kind=kind,
        title=title,
        content=content,
    )


@pytest.mark.integration
class TestMemoryServiceSearchScoped:
    """REC-4 — one explicit scope, no merge, no boost, no over-fetch."""

    async def test_scope_project_excludes_global(self, service: MemoryService) -> None:
        """Given scope='project', no global memory appears."""
        project_id = await _save(service, scope="project")
        global_id = await _save(service, scope="global")

        results = await service.search(_PROJECT, "event sourcing", scope="project")

        ids = {r.id for r in results}
        assert project_id in ids
        assert global_id not in ids
        assert all(r.scope == "project" for r in results)

    async def test_scope_global_excludes_project(self, service: MemoryService) -> None:
        """Given scope='global', no project memory appears."""
        project_id = await _save(service, scope="project")
        global_id = await _save(service, scope="global")

        results = await service.search(GLOBAL_SENTINEL, "event sourcing", scope="global")

        ids = {r.id for r in results}
        assert global_id in ids
        assert project_id not in ids
        assert all(r.scope == "global" for r in results)

    async def test_other_project_is_isolated(self, service: MemoryService) -> None:
        """Given a memory in another project, a project search never returns it
        (Story 5.4 AC3)."""
        await service.save(
            scope="project",
            project_id="other-proj",
            user_id="alice",
            kind="decision",
            title="t",
            content="The billing service uses event sourcing.",
        )

        assert await service.search(_PROJECT, "event sourcing", scope="project") == []

    async def test_explicit_scope_applies_no_boost(
        self, service: MemoryService, store: AsyncPostgresStore
    ) -> None:
        """Given scope='project', the score equals the raw store score."""
        memory_id = await _save(service)

        raw = await store.asearch(("project", _PROJECT), query="event sourcing billing")
        raw_score = next(i.score for i in raw if i.key == memory_id)
        results = await service.search(_PROJECT, "event sourcing billing", scope="project")

        score = next(r.score for r in results if r.id == memory_id)
        assert raw_score is not None
        assert score == pytest.approx(raw_score)

    async def test_explicit_scope_issues_one_query(self, counting_adapter: StorageAdapter) -> None:
        """Given an explicit scope, exactly one adapter search call is made."""
        service = MemoryService(counting_adapter)
        await _save(service)
        counting_store = counting_adapter.counting_store  # type: ignore[attr-defined]
        before = counting_store.asearch_calls

        await service.search(_PROJECT, "event sourcing", scope="project")

        assert counting_store.asearch_calls - before == 1

    async def test_explicit_scope_does_not_over_fetch(self, store: AsyncPostgresStore) -> None:
        """Given an explicit scope, the adapter is called with limit, not limit + window."""
        recorder = _RecordingAdapter(StorageAdapter(store))
        service = MemoryService(recorder)  # type: ignore[arg-type]
        for i in range(8):
            await _save(service, title=f"m{i}", content=f"event sourcing note {i}")

        results = await service.search(_PROJECT, "event sourcing", scope="project", limit=3)

        assert len(recorder.search_calls) == 1
        assert recorder.search_calls[0]["limit"] == 3
        assert len(results) == 3

    async def test_scope_invariant_violation_propagates(self, service: MemoryService) -> None:
        """Given a (scope, project_id) pair violating the invariant, the adapter's
        ValidationError propagates unchanged (LLD error handling)."""
        with pytest.raises(ValidationError):
            await service.search(_PROJECT, "x", scope="global")

    def test_search_signature_has_no_tags_or_project_ids(self) -> None:
        """No `tags` (ADR-0004) and no `project_ids` parameter; the author filter is
        named author_user_id, never user_id; scope is required."""
        import inspect

        params = inspect.signature(MemoryService.search).parameters

        assert "tags" not in params
        assert "project_ids" not in params
        assert "user_id" not in params
        assert params["author_user_id"].default is None
        assert params["scope"].default is inspect.Parameter.empty


@pytest.mark.integration
class TestMemoryServiceSearchFilters:
    """REC-4 — kind / author_user_id become conjunctive storage filters (Story 2.3)."""

    async def test_kind_filter(self, service: MemoryService) -> None:
        """Given kind='decision', only decision memories return."""
        await _save(service, kind="decision")
        await _save(service, kind="gotcha")

        results = await service.search(_PROJECT, "event sourcing", "project", kind="decision")

        assert results
        assert {r.kind for r in results} == {"decision"}

    async def test_author_user_id_filter(self, service: MemoryService) -> None:
        """Given author_user_id='alice', only alice's memories return."""
        alice_id = await _save(service, user_id="alice")
        bob_id = await _save(service, user_id="bob")

        results = await service.search(
            _PROJECT, "event sourcing", "project", author_user_id="alice"
        )

        ids = {r.id for r in results}
        assert ids == {alice_id}
        assert bob_id not in ids

    async def test_kind_and_author_filters_are_conjunctive(self, service: MemoryService) -> None:
        """Given kind='convention' and author_user_id='alice', both constraints hold."""
        wanted = await _save(service, user_id="alice", kind="convention")
        await _save(service, user_id="alice", kind="decision")
        await _save(service, user_id="bob", kind="convention")
        await _save(service, user_id="bob", kind="decision")

        results = await service.search(
            _PROJECT, "event sourcing", "project", kind="convention", author_user_id="alice"
        )

        assert [r.id for r in results] == [wanted]

    async def test_kind_and_scope_are_conjunctive(self, service: MemoryService) -> None:
        """Given kind='convention' and scope='project', a global convention is excluded
        (Story 2.3 AC6)."""
        wanted = await _save(service, scope="project", kind="convention")
        await _save(service, scope="global", kind="convention")

        results = await service.search(_PROJECT, "event sourcing", "project", kind="convention")

        assert [r.id for r in results] == [wanted]

    async def test_other_users_memories_visible_by_default(self, service: MemoryService) -> None:
        """Given memories by alice and bob and no author filter, both appear (Story 5.2 AC3)."""
        alice_id = await _save(service, user_id="alice")
        bob_id = await _save(service, user_id="bob")

        results = await service.search(_PROJECT, "event sourcing", "project")

        assert {alice_id, bob_id} <= {r.id for r in results}

    async def test_no_filters_returns_all_kinds(self, service: MemoryService) -> None:
        """Given only a query and scope, results span kinds."""
        await _save(service, kind="decision")
        await _save(service, kind="gotcha")
        await _save(service, kind="component")

        results = await service.search(_PROJECT, "event sourcing", "project")

        assert {r.kind for r in results} == {"decision", "gotcha", "component"}


@pytest.mark.integration
class TestMemoryServiceSearchSnippets:
    """REC-4 / Story 2.5 — snippet = content[:cap], no ellipsis; full result shape."""

    async def test_long_content_truncated_to_cap(self, service: MemoryService) -> None:
        """Given content longer than 200 chars, the snippet is exactly 200 and is
        the content prefix with no ellipsis."""
        content = "".join(chr(ord("a") + (i % 26)) for i in range(500))
        await _save(service, content=content)

        results = await service.search(_PROJECT, "abc", "project")

        assert len(results) == 1
        assert len(results[0].snippet) == 200
        assert results[0].snippet == content[:200]
        assert "..." not in results[0].snippet
        assert "\u2026" not in results[0].snippet

    async def test_content_of_exactly_cap_is_unaltered(self, service: MemoryService) -> None:
        """Given content exactly 200 chars long, the snippet is the whole content."""
        content = "x" * 200
        await _save(service, content=content)

        results = await service.search(_PROJECT, "x", "project")

        assert results[0].snippet == content

    async def test_short_content_returned_unaltered(self, service: MemoryService) -> None:
        """Given content shorter than the cap, snippet == content byte-for-byte
        (no padding, no stripping)."""
        content = "  Short note with  spaces,\nnewline and unicode: caf\u00e9 \u2713  "
        await _save(service, content=content)

        results = await service.search(_PROJECT, "short note", "project")

        assert results[0].snippet == content

    async def test_snippet_cap_comes_from_injected_config(self, store: AsyncPostgresStore) -> None:
        """Given SearchConfig(snippet_max_chars=20), snippets are capped at 20."""
        service = MemoryService(StorageAdapter(store), SearchConfig(snippet_max_chars=20))
        content = "0123456789" * 10
        await _save(service, content=content)

        results = await service.search(_PROJECT, "0123", "project")

        assert results[0].snippet == content[:20]

    async def test_result_shape(self, service: MemoryService) -> None:
        """Given any result, it carries id, scope, project_id, kind, title, snippet, score."""
        memory_id = await _save(service, kind="gotcha", title="A title")

        results = await service.search(_PROJECT, "event sourcing", "project")

        assert len(results) == 1
        result = results[0]
        assert isinstance(result, SearchResult)
        assert result.id == memory_id
        assert result.scope == "project"
        assert result.project_id == _PROJECT
        assert result.kind == "gotcha"
        assert result.title == "A title"
        assert result.snippet == "The billing service uses event sourcing."
        assert isinstance(result.score, float)
        assert "content" not in result.model_dump()

    async def test_global_result_carries_sentinel_project_id(self, service: MemoryService) -> None:
        """Given a global hit, project_id is '_' so ADR-0015 tools can act on it."""
        memory_id = await _save(service, scope="global")

        results = await service.search(GLOBAL_SENTINEL, "event sourcing", "global")

        assert [r.id for r in results] == [memory_id]
        assert results[0].project_id == GLOBAL_SENTINEL
        assert results[0].scope == "global"

    async def test_none_score_maps_to_zero(self) -> None:
        """Given a store item whose score is None (store parse failure), the result
        score is 0.0 (invariant 6). Uses a fixed-result adapter because a real
        store never yields None on demand; no database is involved."""
        now = datetime.now(UTC)
        item = SearchItem(
            namespace=("project", _PROJECT),
            key=str(uuid.uuid4()),
            value={
                "scope": "project",
                "project_id": _PROJECT,
                "user_id": "alice",
                "kind": "decision",
                "title": "t",
                "content": "c",
            },
            created_at=now,
            updated_at=now,
            score=None,
        )

        class _FixedAdapter:
            async def search(self, **kwargs: Any) -> list[SearchItem]:
                return [item]

        service = MemoryService(_FixedAdapter())  # type: ignore[arg-type]

        results = await service.search(_PROJECT, "q", "project")

        assert len(results) == 1
        assert results[0].score == 0.0


@pytest.mark.integration
class TestMemoryServiceSearchLimits:
    """REC-4 — limit defaults to 10 and clamps to [1, max_limit] (Story 2.1 AC4)."""

    async def _seed(self, service: MemoryService, n: int) -> None:
        for i in range(n):
            await _save(service, title=f"m{i}", content=f"event sourcing note {i}")

    async def test_default_limit_applied(self, service: MemoryService) -> None:
        """Given no limit and 20 matches, 10 results return."""
        await self._seed(service, 20)

        results = await service.search(_PROJECT, "event sourcing", "project")

        assert len(results) == 10

    async def test_limit_respected(self, service: MemoryService) -> None:
        """Given limit=5 and 20 matches, 5 results return."""
        await self._seed(service, 20)

        results = await service.search(_PROJECT, "event sourcing", "project", limit=5)

        assert len(results) == 5

    async def test_limit_clamped_to_max(self, service: MemoryService) -> None:
        """Given limit=5000, at most max_limit (50) results return."""
        await self._seed(service, 60)

        results = await service.search(_PROJECT, "event sourcing", "project", limit=5000)

        assert len(results) == 50

    @pytest.mark.parametrize("limit", [0, -3])
    async def test_limit_below_one_clamps_to_one(self, service: MemoryService, limit: int) -> None:
        """Given limit<=0, the effective limit is 1."""
        await self._seed(service, 5)

        results = await service.search(_PROJECT, "event sourcing", "project", limit=limit)

        assert len(results) == 1

    async def test_limits_come_from_injected_config(self, store: AsyncPostgresStore) -> None:
        """Given SearchConfig(default_limit=3, max_limit=4), default is 3 and the
        clamp is 4 — config is injected, not hard-coded."""
        service = MemoryService(StorageAdapter(store), SearchConfig(default_limit=3, max_limit=4))
        await self._seed(service, 10)

        default = await service.search(_PROJECT, "event sourcing", "project")
        clamped = await service.search(_PROJECT, "event sourcing", "project", limit=100)

        assert len(default) == 3
        assert len(clamped) == 4

    async def test_empty_result_is_not_an_error(self, service: MemoryService) -> None:
        """Given no matches, an empty list is returned."""
        assert await service.search(_PROJECT, "anything at all", "project") == []


class TestMemoryServiceSourceHygiene:
    """REC-4 invariant 5 — the service never reads the environment."""

    def test_memory_service_does_not_read_environ(self) -> None:
        """`environ` does not appear in memory_service.py (grep -c == 0)."""
        import recall.memory_service as module

        assert module.__file__ is not None
        with open(module.__file__, encoding="utf-8") as fh:
            assert "environ" not in fh.read()
