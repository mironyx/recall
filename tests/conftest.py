"""Shared pytest fixtures for the Recall test suite.

Session-scoped Postgres+pgvector container (ADR-0012), function-scoped
clean-DB fixtures for schema tests, session-scoped store fixture with stub
embeddings (ADR-0008), per-test TRUNCATE isolation (E0.5), and logging-reset
helpers. Tests that need a running container must be marked
``@pytest.mark.integration``.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator, Generator, Iterator
from typing import TYPE_CHECKING

import psycopg
import pytest
import pytest_asyncio

if TYPE_CHECKING:
    # testcontainers ships without a py.typed marker; silence mypy's import-untyped check.
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

# psycopg async requires a selector-based event loop on Windows.
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


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

_TABLES_TO_DROP = (
    "store_vectors",
    "store",
    "store_migrations",
    "vector_migrations",
)


async def _drop_all(conn_string: str) -> None:
    """Drop every table that ensure_schema could have created."""
    async with (
        await psycopg.AsyncConnection.connect(conn_string, autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        for table in _TABLES_TO_DROP:
            await cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


@pytest.fixture
async def pg_conn(postgres_dsn: str) -> AsyncIterator[str]:
    """Connection string pointing at a freshly-cleaned database.

    Drops all schema tables before and after each test so every test
    starts from a blank slate without paying container-boot cost.
    """
    await _drop_all(postgres_dsn)
    try:
        yield postgres_dsn
    finally:
        await _drop_all(postgres_dsn)


@pytest.fixture
async def migrated_db(pg_conn: str) -> str:
    """A connection string for a database with ensure_schema already applied."""
    from recall.db.schema import ensure_schema

    await ensure_schema(pg_conn)
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

    await ensure_schema(pg_conn_string)


@pytest_asyncio.fixture(scope="session")
async def _store_session(pg_conn_string: str, _migrated_db_sess: None) -> AsyncIterator[None]:
    """Session-scoped marker — ``_migrated_db_sess`` ensures schema is ready."""
    yield


@pytest_asyncio.fixture
async def store(pg_conn_string: str, _store_session: None) -> AsyncIterator[object]:
    """Per-test store fixture. TRUNCATEs data tables, yields an AsyncPostgresStore
    backed by the StubEmbeddingsProvider (ADR-0008)."""
    from collections.abc import Sequence

    from langgraph.store.postgres import AsyncPostgresStore
    from langgraph.store.postgres.base import PostgresIndexConfig

    from recall.embeddings.stub import StubEmbeddingsProvider

    await _truncate_all(pg_conn_string)
    # The store_vectors column dim is baked into the schema by ensure_schema
    # (schema.py: RECALL_EMBEDDING_DIMS, default 1536). The stub embedder must
    # match it, or any index-enabled aput fails ("expected N dimensions").
    # TODO(#89): share the dim resolution with schema.py (promote _DEFAULT_DIMS
    # to a public constant or a resolve_embedding_dims() helper) — the literal
    # 1536 here can drift from schema.py's default. Deferred from PR review
    # (PR #114); failures are loud (dim mismatch at aput) so the risk is low.
    raw_dims = os.environ.get("RECALL_EMBEDDING_DIMS")
    dims = int(raw_dims) if raw_dims else 1536
    stub = StubEmbeddingsProvider(dim=dims)

    def _embed(texts: Sequence[str]) -> list[list[float]]:
        return stub.embed(list(texts))

    config = PostgresIndexConfig(dims=stub.dim, embed=_embed)
    async with AsyncPostgresStore.from_conn_string(pg_conn_string, index=config) as s:
        yield s


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
