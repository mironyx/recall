"""Adversarial evaluation tests for Issue #91 — E1.6: Tool Router + MCP wiring.

Probes three gaps left by tests/test_tool_router.py and tests/test_e2e_phase1.py:

1. **Scope-explicit namespace isolation (ADR-0015).** Every existing
   not-found test (unit and e2e) uses a genuinely unknown id, so a regression
   that dropped the ``project_id`` from ``get_by_id`` (e.g. a namespace-less
   lookup) would pass the whole suite while silently leaking memories across
   projects — the one isolation guarantee the cross-cutting "Scope isolation"
   section of the requirements promises. These tests fetch an *existing* id
   through a *wrong* namespace and assert not_found.

2. **BDD ``TestStoreWiring.test_dim_mismatch_fails_fast`` (issue #91 AC7) is
   absent.** ``validate_dim`` is unit-tested in tests/test_embeddings.py, but
   nothing exercises the startup call site (``create_app`` → ``_build_store``):
   a mismatch must fail fast before any memory operation. Note the probe uses a
   stand-in provider whose ``dim`` ignores construction — through the real
   path (stub built from the same env var the check reads) the mismatch is
   structurally impossible, which is itself a finding (see module note in the
   report).

3. **BDD ``TestStoreWiring.test_store_built_with_real_embedder`` (issue #91
   AC6) is absent.** The composition root must wire the E1.3 stub provider
   into ``PostgresIndexConfig``, not schema.py's ``_noop_embed`` (raises by
   design). The e2e round-trip covers this only indirectly (a save would
   raise); the wiring property itself is never asserted directly.

Reuses conftest fixtures and the project's real-store convention — the
database is never mocked (CLAUDE.md, ADR-0012).
"""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from tests.conftest import _truncate_all

from recall.memory_service import MemoryService
from recall.server import _build_store, create_app
from recall.storage_adapter import StorageAdapter
from recall.tool_router import ToolRouter

if TYPE_CHECKING:
    from langgraph.store.postgres import AsyncPostgresStore


def _save_args(**overrides: Any) -> dict[str, Any]:
    """Valid MemoryService.save() kwargs for a project-scoped memory."""
    args: dict[str, Any] = {
        "scope": "project",
        "project_id": "proj-eval",
        "user_id": "alice",
        "kind": "decision",
        "title": "Use event sourcing",
        "content": "The billing service uses event sourcing.",
    }
    args.update(overrides)
    return args


@pytest_asyncio.fixture
async def service(store: AsyncPostgresStore) -> MemoryService:
    """MemoryService over the real store fixture (conftest; per-test TRUNCATE)."""
    return MemoryService(StorageAdapter(store))


# ---------------------------------------------------------------------------
# Gap 1 — ADR-0015 scope-explicit namespace isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestNamespaceIsolation:
    """memory_get resolves within the (scope, project_id) namespace (ADR-0015).

    A memory that exists in the DB must be unreachable through any namespace
    other than its own — wrong project_id, or the wrong scope. Existing
    not-found tests only use ids that were never saved, so they cannot catch a
    regression where get_by_id ignores the namespace.
    """

    async def test_existing_memory_hidden_from_other_project(self, service: MemoryService) -> None:
        """Given a memory saved under project A, when memory_get is called with
        project B's namespace and the same id, then {error: 'not_found'} is
        returned — and the memory is still retrievable under its own namespace
        (the miss is a namespace miss, not data loss)."""
        memory_id = await service.save(**_save_args())
        router = ToolRouter(service)

        result = await router.handle_tool_call(
            "memory_get",
            {"scope": "project", "project_id": "other-project", "id": memory_id},
            "alice",
        )

        assert result["error"] == "not_found"
        assert memory_id in result["hint"]

        own = await router.handle_tool_call(
            "memory_get",
            {"scope": "project", "project_id": "proj-eval", "id": memory_id},
            "alice",
        )
        assert own["id"] == memory_id

    async def test_project_memory_hidden_from_global_scope(self, service: MemoryService) -> None:
        """Given a project-scoped memory, when memory_get is called with
        scope=global, then {error: 'not_found'} is returned."""
        memory_id = await service.save(**_save_args())

        result = await ToolRouter(service).handle_tool_call(
            "memory_get",
            {"scope": "global", "project_id": "_", "id": memory_id},
            "alice",
        )

        assert result["error"] == "not_found"

    async def test_global_memory_hidden_from_project_scope(self, service: MemoryService) -> None:
        """Given a global-scoped memory, when memory_get is called with a
        project namespace, then {error: 'not_found'} is returned."""
        memory_id = await service.save(
            scope="global",
            project_id="_",
            user_id="alice",
            kind="preference",
            title="Terse PRs",
            content="Prefer terse PR descriptions.",
        )

        result = await ToolRouter(service).handle_tool_call(
            "memory_get",
            {"scope": "project", "project_id": "proj-eval", "id": memory_id},
            "alice",
        )

        assert result["error"] == "not_found"


# ---------------------------------------------------------------------------
# Gap 2 — Issue #91 AC7 / BDD test_dim_mismatch_fails_fast at the call site
# ---------------------------------------------------------------------------


class _FixedDimProvider:
    """Stand-in provider whose dim ignores construction — forces a mismatch.

    The real ``StubEmbeddingsProvider`` is constructed from the same env var
    ``_build_store`` validates against, so through the public path the
    mismatch can never arise. The BDD property ("EMBEDDINGS_DIM != provider.dim
    raises at startup") therefore requires a provider whose dim differs from
    the configured value.
    """

    def __init__(self, dim: int) -> None:
        pass

    @property
    def dim(self) -> int:
        return 1536

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1536 for _ in texts]


class TestStartupDimValidation:
    """create_app must fail fast when the configured dim mismatches the
    provider's dim, before any memory operation (issue #91 AC7; BDD
    TestStoreWiring.test_dim_mismatch_fails_fast; Story 6.4)."""

    def test_dim_mismatch_fails_fast_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Given EMBEDDINGS_DIM=7 with a 1536-dim provider, when create_app is
        called, then ValueError is raised — no app is served."""
        monkeypatch.setenv("RECALL_EMBEDDING_DIMS", "7")
        monkeypatch.delenv("RECALL_AUTH_FILE", raising=False)
        monkeypatch.setattr("recall.server.StubEmbeddingsProvider", _FixedDimProvider)

        with pytest.raises(ValueError, match="EMBEDDINGS_DIM=7 does not match"):
            create_app("postgresql://nouser:nopass@127.0.0.1:1/nodb")

    def test_matching_dim_constructs_app(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Given the configured dim matching the provider's dim, when
        create_app is called, then construction succeeds (positive control for
        the fail-fast branch — the check must not raise unconditionally)."""
        monkeypatch.setenv("RECALL_EMBEDDING_DIMS", "1536")
        monkeypatch.delenv("RECALL_AUTH_FILE", raising=False)

        app = create_app("postgresql://nouser:nopass@127.0.0.1:1/nodb")

        assert app.state.conn_string  # the app was built and wired


# ---------------------------------------------------------------------------
# Gap 3 — Issue #91 AC6 / BDD test_store_built_with_real_embedder
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCompositionRootStoreWiring:
    """The composition root's store embeds through the real provider, not
    schema.py's ``_noop_embed`` (issue #91 AC6; BDD
    TestStoreWiring.test_store_built_with_real_embedder)."""

    async def test_store_index_embeds_without_raising(
        self, pg_conn_string: str, _migrated_db_sess: None
    ) -> None:
        """Given the store built by the composition root over a real database,
        when an index-enabled put is performed, then embedding runs and the
        record round-trips — ``_noop_embed`` would raise RuntimeError here."""
        saved_env = {
            var: os.environ.get(var) for var in ("RECALL_EMBEDDING_DIMS", "RECALL_EMBEDDINGS_DIM")
        }
        try:
            # Server defaults must match the schema default dim (1536) that
            # ensure_schema used, exactly as the e2e ``app`` fixture does.
            for var in ("RECALL_EMBEDDING_DIMS", "RECALL_EMBEDDINGS_DIM"):
                os.environ.pop(var, None)
            await _truncate_all(pg_conn_string)

            async with _build_store(pg_conn_string) as store:
                key = str(uuid.uuid4())
                await store.aput(
                    ("project", "proj-eval"),
                    key,
                    {"content": "embed me via the composition root"},
                    index=["content"],
                )
                item = await store.aget(("project", "proj-eval"), key)

            assert item is not None
            assert item.value["content"] == "embed me via the composition root"
        finally:
            await _truncate_all(pg_conn_string)
            for var, value in saved_env.items():
                if value is None:
                    os.environ.pop(var, None)
                else:
                    os.environ[var] = value
