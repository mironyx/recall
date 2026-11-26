"""Shared pytest fixtures for the Recall test suite.

Session-scoped Postgres+pgvector container (ADR-0012), function-scoped
clean-DB fixtures for schema tests, session-scoped store fixture with stub
embeddings (ADR-0008), per-test TRUNCATE isolation (E0.5), and logging-reset
helpers. Tests that need a running container must be marked
``@pytest.mark.integration``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from collections.abc import (
    AsyncIterator,
    Callable,
    Generator,
    Iterator,
    MutableMapping,
    Sequence,
)
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg
import pytest
import pytest_asyncio

from recall.config import SearchConfig
from recall.embeddings.provider import EmbeddingsProvider
from recall.settings import EmbeddingsSettings, Settings

if TYPE_CHECKING:
    from langgraph.store.postgres import AsyncPostgresStore
    from starlette.applications import Starlette
    from testcontainers.postgres import PostgresContainer

# psycopg async requires a selector-based event loop on Windows.
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


_EMPTY_AUTH_FILE = Path(__file__).parent / "fixtures" / "empty-auth.json"

# ---------------------------------------------------------------------------
# Postgres container — real DB per ADR-0012
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Spin up a session-scoped Postgres+pgvector container.

    Yields the container so tests can derive either the DSN or the raw
    connection parameters.
    """
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("pgvector/pgvector:pg16")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def postgres_dsn(postgres_container: PostgresContainer) -> str:
    """Return a plain ``postgresql://...`` DSN (no SQLAlchemy driver prefix).

    ``testcontainers`` emits ``postgresql+psycopg2://`` by default; asyncpg
    and the Recall server want a bare ``postgresql://`` URL.
    """
    url: str = postgres_container.get_connection_url()
    # Normalise "postgresql+psycopg2://..." -> "postgresql://..."
    if "+" in url.split("://", 1)[0]:
        scheme, rest = url.split("://", 1)
        url = f"{scheme.split('+')[0]}://{rest}"
    return url


# ---------------------------------------------------------------------------
# Function-scoped clean-DB fixtures for schema tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def pg_conn(postgres_dsn: str) -> AsyncIterator[str]:
    """Connection string for a dedicated per-test database (schema tests only).

    Schema tests drop and recreate all tables; on the shared container
    database that churn would destroy the tables the session-scoped
    ``store`` / ``_migrated_db_sess`` fixtures rely on. The suite only
    stayed green because every ``store`` user happened to sort after
    ``tests/test_schema.py`` — a per-test database makes the order
    irrelevant (exposed by issue #90's ``test_memory_service.py``).
    """
    db_name = f"recall_schema_{uuid.uuid4().hex}"
    admin = await psycopg.AsyncConnection.connect(postgres_dsn, autocommit=True)
    try:
        await admin.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await admin.close()
    dsn = f"{postgres_dsn.rsplit('/', 1)[0]}/{db_name}"
    try:
        yield dsn
    finally:
        # Every consumer uses context-managed connections, so the per-test
        # database has no open connections by teardown time.
        admin = await psycopg.AsyncConnection.connect(postgres_dsn, autocommit=True)
        try:
            await admin.execute(f'DROP DATABASE "{db_name}"')
        finally:
            await admin.close()


@pytest.fixture
async def migrated_db(pg_conn: str) -> str:
    """A connection string for a database with ensure_schema already applied."""
    from recall.db.schema import ensure_schema

    await ensure_schema(pg_conn, _embedding_dims())
    return pg_conn


@pytest.fixture
def bad_dsn() -> str:
    """An unreachable Postgres DSN used to exercise the ``/readyz`` 503 path.

    Port 1 on localhost is guaranteed to refuse connections quickly; asyncpg
    will raise ``OSError``/``ConnectionError`` without any mocking.
    """
    return "postgresql://nouser:nopass@127.0.0.1:1/nodb"


# ---------------------------------------------------------------------------
# E0.5 — Session-scoped store + per-test TRUNCATE (ADR-0012, ADR-0008)
# ---------------------------------------------------------------------------

_TRUNCATE_TABLES = ("store", "store_vectors")


async def _truncate_all(conn_string: str) -> None:
    """Truncate data tables between tests."""
    async with await psycopg.AsyncConnection.connect(conn_string, autocommit=True) as conn:
        await conn.execute(f"TRUNCATE {', '.join(_TRUNCATE_TABLES)} CASCADE")


@pytest.fixture(scope="session")
def pg_conn_string(postgres_dsn: str) -> str:
    """Alias for ``postgres_dsn`` — the session's Postgres connection string."""
    return postgres_dsn


@pytest_asyncio.fixture(scope="session")
async def _migrated_db_sess(pg_conn_string: str) -> None:
    """Run ``ensure_schema`` once per test session (E0.5 contract)."""
    from recall.db.schema import ensure_schema

    await ensure_schema(pg_conn_string, _embedding_dims())


@pytest_asyncio.fixture(scope="session")
async def _store_session(pg_conn_string: str, _migrated_db_sess: None) -> AsyncIterator[None]:
    """Session-scoped marker — ``_migrated_db_sess`` ensures schema is ready."""
    yield


@pytest.fixture
def embed_calls() -> list[list[str]]:
    """Texts passed to each embedding call made through the ``store`` fixture."""
    return []


def _embedding_dims() -> int:
    """The test suite's vector dim: ``EMBEDDINGS_DIM``, default 1536.

    Schema setup, test embedders and ``make_settings`` all read it from here.
    """
    raw_dims = os.environ.get("EMBEDDINGS_DIM")
    return int(raw_dims) if raw_dims else 1536


def make_settings(
    database_url: str,
    *,
    auth_file: str | Path | None = None,
    dim: int | None = None,
) -> Settings:
    """Stub-provider ``Settings`` for tests. ``auth_file`` defaults to an empty token map."""
    return Settings(
        database_url=database_url,
        auth_file=str(auth_file or _EMPTY_AUTH_FILE),
        embeddings=EmbeddingsSettings(
            provider="stub", dim=_embedding_dims() if dim is None else dim
        ),
        search=SearchConfig(),
    )


def stub_env(database_url: str) -> dict[str, str]:
    """A minimal subprocess environment that ``recall serve`` accepts."""
    return {
        "PATH": os.environ.get("PATH", ""),
        "DATABASE_URL": database_url,
        "RECALL_AUTH_FILE": str(_EMPTY_AUTH_FILE),
        "EMBEDDINGS_PROVIDER": "stub",
        "EMBEDDINGS_DIM": str(_embedding_dims()),
    }


@asynccontextmanager
async def _open_store(
    dsn: str, embed: Callable[[Sequence[str]], list[list[float]]], dims: int
) -> AsyncIterator[AsyncPostgresStore]:
    """Open an AsyncPostgresStore over ``dsn`` whose index embeds through ``embed``.

    Shared by ``store`` and ``failing_embedding_store`` (LLD §3.4 refactor note) so
    both run the production wiring: ``embed`` is ``guarded_embed(provider)``.
    """
    from langgraph.store.postgres import AsyncPostgresStore
    from langgraph.store.postgres.base import PostgresIndexConfig

    config = PostgresIndexConfig(dims=dims, embed=embed)
    async with AsyncPostgresStore.from_conn_string(dsn, index=config) as s:
        yield s


class _RecordingProvider(EmbeddingsProvider):
    """Provider double over the stub that records every batch it embeds."""

    def __init__(self, inner: EmbeddingsProvider, calls: list[list[str]]) -> None:
        self._inner = inner
        self._calls = calls

    @property
    def dim(self) -> int:
        return self._inner.dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._calls.append(list(texts))
        return self._inner.embed(texts)


FAILING_PROVIDER_DETAIL = "secret provider detail"


class _FailingProvider(EmbeddingsProvider):
    """Provider double whose ``embed`` always raises (LLD §3.4; not a store mock,
    ADR-0012). The message must never reach an agent."""

    def __init__(self, dim: int) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError(FAILING_PROVIDER_DETAIL)


@pytest_asyncio.fixture
async def store(
    pg_conn_string: str, _store_session: None, embed_calls: list[list[str]]
) -> AsyncIterator[AsyncPostgresStore]:
    """Per-test store fixture. TRUNCATEs data tables, yields an AsyncPostgresStore
    backed by the StubEmbeddingsProvider (ADR-0008) through ``guarded_embed``
    (the production path, LLD §3.4); each embed batch is recorded in ``embed_calls``."""
    from recall.embeddings.provider import guarded_embed
    from recall.embeddings.stub import StubEmbeddingsProvider

    await _truncate_all(pg_conn_string)
    dims = _embedding_dims()
    provider = _RecordingProvider(StubEmbeddingsProvider(dim=dims), embed_calls)
    async with _open_store(pg_conn_string, guarded_embed(provider), dims) as s:
        yield s


@pytest_asyncio.fixture
async def failing_embedding_store(
    pg_conn_string: str, _store_session: None
) -> AsyncIterator[AsyncPostgresStore]:
    """A real AsyncPostgresStore whose embedding provider raises
    ``RuntimeError(FAILING_PROVIDER_DETAIL)``, wired through ``guarded_embed``
    (LLD §3.4). Does not TRUNCATE: tests pair it with ``store`` to seed data
    through a working embedder, and ``store`` owns the per-test TRUNCATE."""
    from recall.embeddings.provider import guarded_embed

    dims = _embedding_dims()
    async with _open_store(pg_conn_string, guarded_embed(_FailingProvider(dims)), dims) as s:
        yield s


class _CountingStore:
    """Decorator over a real AsyncPostgresStore that counts calls.

    Not a subclass and not a mock: every call is forwarded to the real store
    (ADR-0012); the only additions are the ``asearch_calls``, ``aget_calls``,
    ``aput_calls`` and ``adelete_calls`` counters.
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.asearch_calls = 0
        self.aget_calls = 0
        self.aput_calls = 0
        self.adelete_calls = 0

    async def aget(self, *args: object, **kwargs: object) -> object:
        self.aget_calls += 1
        return await self._inner.aget(*args, **kwargs)  # type: ignore[attr-defined]

    async def aput(self, *args: object, **kwargs: object) -> object:
        self.aput_calls += 1
        return await self._inner.aput(*args, **kwargs)  # type: ignore[attr-defined]

    async def adelete(self, *args: object, **kwargs: object) -> object:
        self.adelete_calls += 1
        return await self._inner.adelete(*args, **kwargs)  # type: ignore[attr-defined]

    async def asearch(self, *args: object, **kwargs: object) -> object:
        self.asearch_calls += 1
        return await self._inner.asearch(*args, **kwargs)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


@pytest.fixture
def counting_adapter(store: object) -> object:
    """A ``StorageAdapter`` over a call-counting decorator of the real store.

    The returned adapter exposes ``counting_store`` (with ``asearch_calls``)
    so tests can assert how many ``asearch`` calls reached the real store.
    """
    from recall.storage_adapter import StorageAdapter

    counting_store = _CountingStore(store)
    adapter = StorageAdapter(counting_store)  # type: ignore[arg-type]
    adapter.counting_store = counting_store  # type: ignore[attr-defined]
    return adapter


class _FailingGlobalAdapter:
    """Decorator over a real ``StorageAdapter`` whose ``search`` raises on the
    ``("global", "_")`` namespace only. Everything else is forwarded (ADR-0012)."""

    def __init__(self, inner: object) -> None:
        self._inner = inner

    async def search(self, **kwargs: object) -> object:
        if kwargs.get("scope") == "global":
            raise RuntimeError("global namespace query failed")
        return await self._inner.search(**kwargs)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


@pytest.fixture
def failing_adapter(store: object) -> object:
    """A real-store adapter that raises when the global namespace is searched."""
    from recall.storage_adapter import StorageAdapter

    return _FailingGlobalAdapter(StorageAdapter(store))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Logging reset — configure_logging must be reversible across tests
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_logging() -> Iterator[None]:
    """Snapshot the root logger + structlog config, restore after the test.

    Tests that call ``configure_logging()`` MUST use this fixture so they do
    not poison sibling tests' stdout capture or structlog defaults.
    """
    import structlog

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level

    yield

    # Remove any handlers installed by configure_logging and restore the snapshot.
    for h in root.handlers[:]:
        root.removeHandler(h)
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)

    # Reset structlog defaults. reset_defaults() is idempotent and safe.
    structlog.reset_defaults()
    # Clear any lingering contextvars.
    structlog.contextvars.clear_contextvars()


@pytest.fixture
def captured_logs() -> Iterator[list[MutableMapping[str, Any]]]:
    """Capture structlog events as dicts (REC-7). Includes bound contextvars."""
    import structlog

    cap = structlog.testing.LogCapture()
    # merge_contextvars so request-scoped fields (request_id) appear as in prod.
    old = structlog.get_config()["processors"]
    structlog.configure(processors=[structlog.contextvars.merge_contextvars, cap])
    try:
        yield cap.entries
    finally:
        structlog.configure(processors=old)


# ---------------------------------------------------------------------------
# MCP e2e fixtures (REC-6) — app factory, project_id, per-call MCP clients
# ---------------------------------------------------------------------------

ALICE_HEADERS = {"Authorization": "Bearer test-token"}
BOB_HEADERS = {"Authorization": "Bearer bob-token"}


@pytest.fixture
def project_id() -> str:
    """A well-formed project identifier for e2e tests."""
    return "proj-e2e"


@pytest.fixture
def app_factory(
    pg_conn_string: str,
    _migrated_db_sess: None,
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[], Starlette]:
    """Factory of Starlette apps (lifespan NOT entered) over the test Postgres.

    ``create_app``'s store is single-use, so each lifespan entry needs a fresh
    app. The auth file maps ``test-token`` to alice and ``bob-token`` to bob
    (Story 5.6). The lifespan is entered per client inside the test's own task
    (anyio task groups cannot cross fixture tasks).
    """
    from recall.server import create_app

    auth_file = tmp_path_factory.mktemp("e2e-auth") / "auth.json"
    auth_file.write_text(
        json.dumps({"test-token": {"user_id": "alice"}, "bob-token": {"user_id": "bob"}})
    )
    settings = make_settings(pg_conn_string, auth_file=auth_file)
    return lambda: create_app(settings)


@pytest.fixture
def app(app_factory: Callable[[], Starlette]) -> Starlette:
    """A single Starlette app (lifespan NOT entered), for one-client tests."""
    return app_factory()


# TODO(REC-6): move _e2e_client/_unpack_result into a shared tests helper module so
# conftest does not import from test_e2e_phase1 or touch client._session.
class _PerCallClient:
    """MCP client that opens lifespan + transport around each call.

    A client held open across fixture setup/teardown breaks anyio task groups
    (see test_e2e_phase1 docstring), so each ``call_tool`` / ``list_tools``
    enters a fresh app and client inside the calling test's task. Data persists
    in Postgres between calls; ``as_user`` switches the bearer token.
    """

    def __init__(self, factory: Callable[[], Starlette], headers: dict[str, str]) -> None:
        self._factory = factory
        self._headers = headers

    def as_user(self, headers: dict[str, str]) -> _PerCallClient:
        return _PerCallClient(self._factory, headers)

    async def call_tool(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a tool and return its decoded JSON payload."""
        from tests.test_e2e_phase1 import _e2e_client, _unpack_result

        async with _e2e_client(self._factory(), self._headers) as client:
            return _unpack_result(await client.call_tool(name, params))

    async def list_tools(self) -> list[Any]:
        from tests.test_e2e_phase1 import _e2e_client

        async with _e2e_client(self._factory(), self._headers) as client:
            return list((await client._session.list_tools()).tools)


@pytest_asyncio.fixture
async def mcp_client(app_factory: Callable[[], Starlette], pg_conn_string: str) -> _PerCallClient:
    """Authenticated (alice) MCP client over a TRUNCATEd database."""
    await _truncate_all(pg_conn_string)
    return _PerCallClient(app_factory, ALICE_HEADERS)


@pytest_asyncio.fixture
async def unauthenticated_client(
    app_factory: Callable[[], Starlette], pg_conn_string: str
) -> _PerCallClient:
    """MCP client sending no bearer token."""
    await _truncate_all(pg_conn_string)
    return _PerCallClient(app_factory, {})
