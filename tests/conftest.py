"""Shared pytest fixtures for the Recall test suite.

Session-scoped Postgres+pgvector container is shared across tests for speed.
A function-scoped ``pg_conn`` fixture hands out a connection string pointing at
a freshly-reset database (all relevant tables dropped) so each test starts from
a clean schema without paying container-boot cost per test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Session-scoped container
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _pg_container() -> Iterator[PostgresContainer]:
    """Start a single pgvector-enabled Postgres container for the session.

    The ``pgvector/pgvector:pg16`` image ships with the ``vector`` extension
    pre-installed; AsyncPostgresStore.setup() calls
    ``CREATE EXTENSION IF NOT EXISTS vector`` and requires that extension.
    """
    with PostgresContainer("pgvector/pgvector:pg16") as container:
        yield container


@pytest.fixture(scope="session")
def _base_conn_string(_pg_container: PostgresContainer) -> str:
    """Driverless connection URL (``postgresql://user:pw@host:port/db``)."""
    url: str = _pg_container.get_connection_url(driver=None)
    return url


# ---------------------------------------------------------------------------
# Function-scoped clean-DB fixture
# ---------------------------------------------------------------------------


_RELEVANT_TABLES = (
    # Project registry (ADR-0009, 0002_projects.sql)
    "projects",
    # Migration ledger (ADR-0013)
    "schema_migrations",
    # LangGraph store tables (created by AsyncPostgresStore.setup())
    "store_vectors",
    "store",
    "store_migrations",
    "vector_migrations",
)


async def _drop_all(conn_string: str) -> None:
    """Drop every table that a migration could have created. Safe on an empty DB."""
    async with (
        await psycopg.AsyncConnection.connect(conn_string, autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        for table in _RELEVANT_TABLES:
            await cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


@pytest.fixture
async def pg_conn(_base_conn_string: str) -> AsyncIterator[str]:
    """Connection string pointing at a freshly-cleaned database.

    The container persists across the session but the relevant tables are
    dropped before and after each test, giving every test a blank schema.
    """
    await _drop_all(_base_conn_string)
    try:
        yield _base_conn_string
    finally:
        await _drop_all(_base_conn_string)


@pytest.fixture
async def migrated_db(pg_conn: str) -> str:
    """A connection string for a database with all migrations applied.

    Runs ``apply_pending`` once then hands the URL to the test. Tests that
    consume this fixture can assume both ``0001_initial`` and ``0002_projects``
    have been applied.
    """
    from recall.db.migrations import apply_pending

    await apply_pending(pg_conn)
    return pg_conn
