"""Shared pytest fixtures for the Recall test suite.

Session-scoped Postgres+pgvector container (ADR-0012), function-scoped
clean-DB fixtures for schema tests, and logging-reset helpers.
Tests that need a running container must be marked ``@pytest.mark.integration``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Generator, Iterator
from typing import TYPE_CHECKING

import psycopg
import pytest

if TYPE_CHECKING:
    # testcontainers ships without a py.typed marker; silence mypy's import-untyped check.
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]


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
    "projects",
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
